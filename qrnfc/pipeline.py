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

    # One row may yield several files: identical copies (item_quantity>1) share
    # content, so render once and copy to the remaining names.
    os.makedirs(cfg.output_root, exist_ok=True)
    names = _out_names(order)
    order.output_paths = []
    first = os.path.join(cfg.output_root, names[0])
    build_pdf(first, rgb, white, layout.page_w_pt, layout.page_h_pt)
    order.output_paths.append(first)
    for nm in names[1:]:
        dst = os.path.join(cfg.output_root, nm)
        shutil.copyfile(first, dst)
        order.output_paths.append(dst)
    order.output_path = first
    return first


def _base_name(order: Order) -> str:
    """<lang>_<SKU>_<tracking>_<material> (material omitted if none)."""
    lang = order.language or (order.variant.language if order.variant else "")
    parts = [lang, order.sku, order.tracking]
    if order.variant and order.variant.material_code:
        parts.append(order.variant.material_code)
    stem = "_".join(p for p in parts if p)
    return "".join(c for c in stem if c.isalnum() or c in "-_").strip("_")


def _out_names(order: Order) -> list[str]:
    """Filenames for an order's sign(s).

    - single-sign order:  <qty>x_<base>.pdf   (e.g. 1x_DE_NFC_D02_WHT-A5_..._OAK.pdf)
    - multi-sign order:   <Letter><seq>_<base>.pdf for each sign, marking that they
      belong to one order (A1, A2, … / B1, B2 …). Covers both item_quantity>1
      (identical) and several rows with the same order_number (different addresses).
    """
    base = _base_name(order)
    if order.group_prefix:
        return [f"{order.group_prefix}{seq}_{base}.pdf" for seq in order.sign_seqs]
    return [f"{order.quantity}x_{base}.pdf"]


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
    """Group rows by order_number; orders with >1 total sign get a letter prefix
    and each sign a sequence number (in CSV order). item_quantity expands a row
    into that many signs."""
    from collections import OrderedDict
    groups: "OrderedDict[str, list[Order]]" = OrderedDict()
    for o in orders:
        groups.setdefault(o.order_number, []).append(o)

    letters = _letter_sequence()
    prefix_of, counter = {}, {}
    for onum, rows in groups.items():
        total = sum(max(1, r.quantity) for r in rows)
        prefix_of[onum] = next(letters) if total > 1 else None
        counter[onum] = 0

    for o in orders:                       # CSV order -> sequence 1,2,3,…
        o.group_prefix = prefix_of[o.order_number]
        seqs = []
        for _ in range(max(1, o.quantity)):
            counter[o.order_number] += 1
            seqs.append(counter[o.order_number])
        o.sign_seqs = seqs


def run_batch(orders: list[Order], cfg: AppConfig, places, manual_cb,
              progress_cb: ProgressCb = lambda *a: None, resolver=http_resolver):
    _assign_sign_groups(orders)
    unresolved: list[Order] = []
    total = len(orders)
    for i, order in enumerate(orders, 1):
        variants.decode_variant(order)
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
    return unresolved
