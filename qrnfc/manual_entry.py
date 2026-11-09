"""Create a single print file by hand, without a shipping CSV.

For orders that arrive by email, eBay, phone — anything not in the Amazon CSV.
The operator picks a template, types the company/address (and optionally a
Place ID or review link), plus a free-text **reference** (a name or order ID)
that goes into the filename so the file can be matched back to the order.

Deliberately builds a normal ``Order`` and runs it through the SAME
resolve_link / render_order path as a CSV batch, so the print output is
identical — spot channel, overprint, QR ink and geometry all unchanged.
"""
from __future__ import annotations

import os

from . import link_export, order_export, variants
from .models import Order
from .review_link import link_from_place_id, looks_like_place_id


def safe_reference(text: str) -> str:
    """Filename-safe reference. Keeps letters/digits/-/_ , collapses the rest."""
    out = "".join(c if (c.isalnum() or c in "-_") else "_" for c in (text or "").strip())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_") or "manual"


def build_order(reference: str, language: str, shape: str, code: str, size: str,
                company: str, address: str, link: str = "",
                material_text: str = "", country: str = "") -> Order:
    """Assemble an Order equivalent to one parsed from a CSV row."""
    order = Order(
        row_index=0,
        order_number=(reference or "").strip(),
        sku=f"NFC_{shape}_{code}-{size}",
        raw_note="",
        quantity=1,
        tracking="",
    )
    order.language = language
    # There is no marketplace behind a hand-made order, so the operator states
    # the country; it lands in the filename exactly as a CSV order's does, so
    # manual files follow the same naming scheme.
    order.form_language = (country or "").strip().upper() or None
    order.company = (company or "").strip()
    order.address = (address or "").strip()

    # The dialog's box takes EITHER a full review link or a bare Place ID. Turn
    # an ID into its review link here, so everything downstream only ever sees
    # a URL. This is the operator's fallback for the case the Places lookup
    # cannot resolve from company + address, so the loose (non-strict) test is
    # right: they looked the ID up by hand and typed it in deliberately.
    typed = (link or "").strip()
    if typed and looks_like_place_id(typed):
        order.place_id = typed
        typed = link_from_place_id(typed)
    order.provided_link = typed
    order.material_text = material_text or ""
    # The reference takes the place of the batch prefix, so the file comes out
    # as <reference>_<lang>_<SKU>[_<material>-<country>].pdf
    order.file_prefix = safe_reference(reference)
    order.copies = 1
    order.emits_file = True
    return order


def create(reference, language, shape, code, size, company, address, cfg,
           places=None, link="", material_text="", manual_cb=None, resolver=None,
           country=""):
    """Resolve the link and render one print file. Returns the finished Order.

    Raises whatever render_order raises (missing template, no layout) so the UI
    can report it verbatim rather than silently producing nothing.
    """
    from .pipeline import render_order, resolve_link
    from .review_link import http_resolver

    order = build_order(reference, language, shape, code, size,
                        company, address, link, material_text, country)
    if variants.decode_variant(order, cfg.colour_codes) is None:
        raise ValueError(f"cannot decode variant for SKU '{order.sku}'")

    resolve_link(order, cfg, places, manual_cb or (lambda o: ""),
                 resolver=http_resolver if resolver is None else resolver)
    if not order.is_resolved:
        raise ValueError(
            "no review link could be resolved — paste the business's Place ID "
            "(or its full review link) into the Place ID / review link box"
            + (" [" + "; ".join(order.notes) + "]" if order.notes else ""))

    render_order(order, cfg)
    _append_to_link_list(order, cfg)
    _append_to_export(order, cfg)
    return order


def _append_to_export(order: Order, cfg) -> None:
    """Add the order to the per-order export so it stays complete."""
    path = os.path.join(cfg.output_root, order_export.FILENAME)
    try:
        order_export.append_rows(path, order_export.rows_from_orders([order]))
    except Exception:
        pass          # the print file is the deliverable; the export is a record


def _append_to_link_list(order: Order, cfg) -> None:
    """Add the order to links.csv so the NFC writer worklist stays complete."""
    path = os.path.join(cfg.output_root, link_export.FILENAME)
    rows = link_export.rows_from_orders([order])
    try:
        link_export.append_rows(path, rows)
    except Exception:
        pass          # the print file is the deliverable; the list is a convenience
