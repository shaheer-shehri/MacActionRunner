"""Orchestrates: parse -> variant -> link -> QR -> PDF, per order and per batch.

UI concerns (confirmation dialogs, manual entry) are injected as callbacks so the
same pipeline works headless (CLI/tests) or behind Tkinter.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from . import csv_parser, variants
from .config import AppConfig
from .matching import address_matches
from .models import LinkSource, Order
from .places import PlaceCandidate, PlacesClient
from .qr import compose
from .pdf_export import build_pdf
from .review_link import canonicalize, http_resolver

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
    typed = manual_cb(order)
    if typed:
        res = canonicalize(typed, resolver=resolver)
        if res.valid:
            order.final_link = res.canonical
            order.link_source = LinkSource.MANUAL
            order.place_id = res.place_id
            return
        order.log("manual link invalid")

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

    os.makedirs(cfg.output_root, exist_ok=True)
    order.output_path = os.path.join(cfg.output_root, _out_name(order))
    build_pdf(order.output_path, rgb, white, layout.page_w_pt, layout.page_h_pt)
    return order.output_path


def _out_name(order: Order) -> str:
    """Filename: <qty>x_<SKU>_<tracking>_<material>.pdf  (material omitted if none).
    Example: 1x_NFC_D02_WHT-A5_00340434888052019115_OAK.pdf
    """
    parts = [f"{order.quantity}x", order.sku, order.tracking]
    if order.variant and order.variant.material_code:
        parts.append(order.variant.material_code)
    stem = "_".join(p for p in parts if p)
    safe = "".join(c for c in stem if c.isalnum() or c in "-_").strip("_")
    return f"{safe}.pdf"


def run_batch(orders: list[Order], cfg: AppConfig, places, manual_cb,
              progress_cb: ProgressCb = lambda *a: None, resolver=http_resolver):
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
