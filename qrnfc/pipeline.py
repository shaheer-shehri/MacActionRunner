"""Orchestrates: parse -> variant -> link -> QR -> PDF, per order and per batch.

UI concerns (confirmation dialogs, manual entry) are injected as callbacks so the
same pipeline works headless (CLI/tests) or behind Tkinter.
"""
from __future__ import annotations

import os
import re
import shutil
from typing import Callable, Optional

from . import csv_parser, variants
from .address_labels import Label, build_label_pdf
from .config import AppConfig
from .matching import address_matches
from .models import LinkSource, Order
from .places import PlaceCandidate, PlacesClient
from .qr import compose
from .pdf_export import build_pdf
from .review_link import canonicalize, http_resolver, link_from_place_id

# A bare Google Place ID (no URL): long token of letters/digits/-/_ .
_PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{15,}$")


def _looks_like_place_id(s: str) -> bool:
    return not s.lower().startswith("http") and bool(_PLACE_ID_RE.match(s))

# UI callbacks -------------------------------------------------------------
# manual_cb(order) -> link string | "" (empty = leave unresolved)
ManualCb = Callable[[Order], str]
ProgressCb = Callable[[int, int, Order], None]


def resolve_link(order: Order, cfg: AppConfig, places: Optional[PlacesClient],
                 manual_cb: ManualCb, resolver=None) -> None:
    # 1. Customer-provided direct review link (recognized by pattern).
    if order.provided_link:
        res = canonicalize(order.provided_link, resolver=resolver)
        if res.valid:
            order.final_link = res.canonical
            order.link_source = LinkSource.PROVIDED
            order.place_id = res.place_id
            return
        order.log(f"provided link rejected: {res.reason}")

    # 2. Places lookup + automatic address disambiguation (no human step).
    if places is not None and order.company:
        cand = _match_place(order, places)
        if cand is not None:
            _accept(order, cand)
            return

    # 3. Manual fallback — the exception (usually: no Place ID exists yet).
    typed = (manual_cb(order) or "").strip()
    if typed:
        # Accept a bare Place ID and build the review link automatically, or a
        # full review link / URL.
        if _looks_like_place_id(typed):
            order.place_id = typed
            order.final_link = link_from_place_id(typed)
            order.link_source = LinkSource.MANUAL
            return
        res = canonicalize(typed, resolver=resolver)
        if res.valid:
            order.final_link = res.canonical
            order.link_source = LinkSource.MANUAL
            order.place_id = res.place_id
            return
        order.log("manual entry invalid (not a Place ID or recognized link)")

    order.link_source = LinkSource.UNRESOLVED


def _match_place(order: Order, places: PlacesClient) -> Optional[PlaceCandidate]:
    """Resolve a unique Place ID automatically.

    - single candidate  -> accept (input was unique enough)
    - many candidates    -> pick the one whose street+city matches the CSV address
    - no address match   -> None (falls through to manual review)
    """
    try:
        cands = places.find_candidates(order.company, order.address)
    except Exception as e:  # network / quota / bad key
        order.log(f"places error: {e}")
        return None
    if not cands:
        order.log("places: no candidates")
        return None
    if len(cands) == 1:
        return cands[0]
    matches = [c for c in cands if address_matches(order.address, c.formatted_address)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        order.log(f"places: {len(matches)} address matches, taking first")
        return matches[0]
    order.log(f"places: {len(cands)} candidates, none matched address")
    return None


def _accept(order: Order, cand: PlaceCandidate) -> None:
    order.final_link = cand.review_link
    order.place_id = cand.place_id
    order.resolved_business_name = cand.name
    order.link_source = LinkSource.PLACES


def render_order(order: Order, cfg: AppConfig) -> str:
    v = order.variant
    tpl = variants.resolve_template_path(cfg.templates_root, v)
    if not tpl:
        raise FileNotFoundError(f"template not found for {v.template_key}")
    layout = cfg.layout_for(v.layout_key)
    if not layout:
        raise KeyError(f"no QR layout configured for {v.layout_key}")

    qr_white = v.colour in cfg.white_qr_colours   # dark stock -> white-ink QR
    rgb, white = compose(tpl, order.final_link, layout.qr_box,
                         white_behind_qr=cfg.white_behind_qr, qr_white=qr_white)

    # One file per distinct sign; identical copies are covered by the quantity
    # in the filename prefix (e.g. 2x), not by duplicate files.
    os.makedirs(cfg.output_root, exist_ok=True)
    order.output_path = os.path.join(cfg.output_root, _out_name(order))
    build_pdf(order.output_path, rgb, white, layout.page_w_pt, layout.page_h_pt)
    order.output_paths = [order.output_path]
    return order.output_path


def _base_name(order: Order) -> str:
    """<lang>_<SKU>_<tracking>_<material> (material omitted if none)."""
    lang = order.language or (order.variant.language if order.variant else "")
    parts = [lang, order.sku, order.tracking]
    if order.variant and order.variant.material_code:
        parts.append(order.variant.material_code)
    stem = "_".join(p for p in parts if p)
    return "".join(c for c in stem if c.isalnum() or c in "-_").strip("_")


def _out_name(order: Order) -> str:
    """<prefix>_<lang>_<SKU>_<tracking>_<material>.pdf — prefix set by
    _assign_sign_groups ("1x"/"2x" for identical signs, "A1"/"A2" when the order
    needs genuinely different print files)."""
    return f"{order.file_prefix}_{_base_name(order)}.pdf"


def _sign_key(order: Order) -> tuple:
    """Signs sharing this key need the SAME print file: same content (language,
    company, address) AND same variant (SKU = shape/colour/size)."""
    return (
        (order.language or "").upper(),
        " ".join((order.company or "").lower().split()),
        " ".join((order.address or "").lower().split()),
        (order.sku or "").upper(),
    )


def _letter_sequence():
    """Yield A, B, … Z, AA, AB, … for labelling multi-sign orders."""
    import string
    n = 0
    while True:
        n += 1
        s, x = "", n
        while x:
            x, r = divmod(x - 1, 26)
            s = string.ascii_uppercase[r] + s
        yield s


def _assign_sign_groups(orders: list[Order]) -> None:
    """Decide each row's filename prefix.

    Rows are grouped by order_number, then bucketed by _sign_key (identical
    content AND variant = one print file).

    Case 1 — the order needs only ONE print file (all signs identical, however
        many were ordered): quantity prefix only -> "1x" / "2x" / "3x".
        Multiple NFC tags, identical content.
    Case 2 — the order needs SEVERAL different print files (different address or
        different variant): one letter for the order + a number per distinct file
        -> "A1", "A2"… A file needed more than once also carries its quantity
        (e.g. "A1_2x"). Multiple NFC tags, different content.
    """
    from collections import OrderedDict
    groups: "OrderedDict[str, list[Order]]" = OrderedDict()
    for o in orders:
        groups.setdefault(o.order_number, []).append(o)

    letters = _letter_sequence()
    for rows in groups.values():
        buckets: "OrderedDict[tuple, list[Order]]" = OrderedDict()
        for o in rows:
            buckets.setdefault(_sign_key(o), []).append(o)

        multi = len(buckets) > 1                    # Case 2 only when they differ
        letter = next(letters) if multi else None
        for n, bucket in enumerate(buckets.values(), start=1):
            copies = sum(max(1, r.quantity) for r in bucket)
            if multi:
                prefix = f"{letter}{n}" + (f"_{copies}x" if copies > 1 else "")
            else:
                prefix = f"{copies}x"
            for i, r in enumerate(bucket):
                r.group_prefix = letter             # None for Case 1
                r.sign_index = n if multi else 0
                r.copies = copies
                r.file_prefix = prefix
                r.emits_file = (i == 0)             # duplicate rows merge into one file


def run_batch(orders: list[Order], cfg: AppConfig, places, manual_cb,
              progress_cb: ProgressCb = lambda *a: None, resolver=http_resolver):
    _assign_sign_groups(orders)
    unresolved: list[Order] = []
    total = len(orders)
    for i, order in enumerate(orders, 1):
        variants.decode_variant(order)
        if not order.emits_file:      # identical duplicate row -> merged into one file
            order.log(f"identical sign, merged into the {order.file_prefix} file")
            progress_cb(i, total, order)
            continue
        if order.variant is None:
            order.log("skipped: no variant")
            unresolved.append(order)
            progress_cb(i, total, order)
            continue
        resolve_link(order, cfg, places, manual_cb, resolver=resolver)
        if not order.is_resolved:
            unresolved.append(order)
        else:
            try:
                render_order(order, cfg)
            except Exception as e:
                order.log(f"render failed: {e}")
                unresolved.append(order)
        progress_cb(i, total, order)

    _generate_labels(orders, cfg)
    return unresolved


def _generate_labels(orders: list[Order], cfg: AppConfig) -> None:
    """For each multi-sign order that ships to more than one distinct address,
    write a 10x15 cm label PDF (one page per sign) into output/labels/."""
    from collections import OrderedDict
    groups: "OrderedDict[str, list[Order]]" = OrderedDict()
    for o in orders:
        if o.group_prefix and o.emits_file:     # Case 2 only, one row per print file
            groups.setdefault(o.order_number, []).append(o)

    label_dir = os.path.join(cfg.output_root, "labels")
    for rows in groups.values():
        rows = sorted(rows, key=lambda r: r.sign_index)
        # only worth printing when the signs go to different locations/companies
        if len({(r.company, r.address) for r in rows}) <= 1:
            continue
        labels: list[Label] = []
        for r in rows:
            marker = f"{r.group_prefix}{r.sign_index}"
            for _ in range(max(1, r.copies)):   # one label per physical sign
                labels.append(Label(marker, r.company, r.address))
        os.makedirs(label_dir, exist_ok=True)
        out = os.path.join(label_dir, f"{rows[0].group_prefix}_labels.pdf")
        try:
            build_label_pdf(out, labels)
        except Exception as e:                  # labels are a convenience, never fatal
            rows[0].log(f"label sheet failed: {e}")
