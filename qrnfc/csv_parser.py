"""Parse the shipping CSV and extract labelled fields from the free-text note.

The note is multi-line. Strategy:
  1. Detect the language first (scan every language's "language" label).
  2. Use that language's label set to slice out company / address / link / material.
  3. Address may span multiple lines until the next known label.
"""
from __future__ import annotations

import csv
from typing import Iterable, Optional

from .labels import DEFAULT_LABELS, language_code_for
from .models import Order

NOTE_COLUMN = "item_note"
SKU_COLUMN = "item_sku"
ORDER_COLUMN = "order_number"
QTY_COLUMN = "item_quantity"
TRACKING_COLUMN = "tracking_numbers"

# The recipient (DHL ship-to) is required by the per-order export but is NOT in
# the current Amazon shipping export -- every column there is either a constant
# (integration/carrier account) or item data. Rather than hard-code one future
# column name, accept any of the usual spellings: the day that column is added
# to the export it is picked up with no code change. Until then the export's
# Recipient cell stays empty, which is visible rather than wrong.
RECIPIENT_COLUMNS = (
    "recipient", "recipient_name", "ship_to_name", "shipto_name", "ship_to",
    "shipto", "shipping_name", "shipping_recipient", "buyer_name", "buyer",
    "customer_name", "consignee", "addressee",
    "empfaenger", "empfänger", "empfaengername", "name",
)

# Customers' checkout forms render apostrophes/quotes typographically (’ “ ”)
# in some locales and plainly (' " ") in others — e.g. the IT form uses
# "dell’azienda" (curly) while the label was written with a straight one. Fold
# both forms together before matching so this doesn't have to be special-cased
# per label/language (previously bit IT; would silently bite ES/EN too).
_QUOTE_FOLD = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    " ": " ",
})


def _normalize(text: str) -> str:
    return text.translate(_QUOTE_FOLD)


def read_orders(csv_path: str, labels: Optional[dict] = None) -> list[Order]:
    labels = labels or DEFAULT_LABELS
    orders: list[Order] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for i, row in enumerate(reader):
            note = (row.get(NOTE_COLUMN) or "").strip()
            order = Order(
                row_index=i,
                order_number=(row.get(ORDER_COLUMN) or "").strip(),
                sku=(row.get(SKU_COLUMN) or "").strip(),
                raw_note=note,
                quantity=_to_int(row.get(QTY_COLUMN), default=1),
                tracking=(row.get(TRACKING_COLUMN) or "").strip(),
                recipient=_first_present(row, RECIPIENT_COLUMNS),
            )
            _extract_fields(order, labels)
            orders.append(order)
    return orders


def _first_present(row: dict, candidates) -> str:
    """First non-empty value among ``candidates``, matched case-insensitively
    and ignoring spaces/underscores, so "Ship To Name" and "ship_to_name" both
    hit. Returns "" when the export has no such column."""
    lookup = {(k or "").strip().lower().replace(" ", "").replace("_", ""): v
              for k, v in row.items()}
    for name in candidates:
        v = lookup.get(name.replace("_", ""))
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _to_int(value, default: int = 1) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _extract_fields(order: Order, labels: dict) -> None:
    lines = [ln.strip() for ln in order.raw_note.splitlines() if ln.strip()]
    if not lines:
        order.log("empty note")
        return

    # Two different facts live on the language line (see _detect_languages):
    # which form the order came from, and which sign the customer picked.
    form_lang, sign_lang, raw_value = _detect_languages(lines, labels)
    order.form_language = form_lang
    order.language = sign_lang or form_lang
    if sign_lang is None:
        if form_lang is None:
            order.log("could not detect language")
        elif raw_value:
            # An unrecognised selection must be visible, not quietly treated as
            # the form language: that is exactly how English orders on a French
            # form ended up printed in French. Add the missing name to
            # labels.LANGUAGE_NAMES.
            order.log(f"unrecognised sign language {raw_value!r} - fell back to "
                      f"the form language {form_lang}")
        else:
            order.log(f"no sign language selected - using the form language {form_lang}")

    # Extract fields by matching labels from ALL languages: the note's label
    # language can differ from the selected sign language (e.g. an "Englisch"
    # order whose note still uses German labels). Longer labels first so a more
    # specific label wins over a shorter prefix.
    label_to_field: list[tuple[str, str]] = []
    for langset in labels.values():
        for field, variants in langset.items():
            for lab in variants:
                label_to_field.append((_normalize(lab).lower(), field))
    label_to_field.sort(key=lambda lf: -len(lf[0]))

    values: dict[str, list[str]] = {}
    current_field: Optional[str] = None
    for line in lines:
        matched_field, remainder = _match_label(line, label_to_field)
        if matched_field:
            current_field = matched_field
            values.setdefault(current_field, [])
            if remainder:
                values[current_field].append(remainder)
        elif current_field:
            # continuation line (e.g. postcode/city under address)
            values[current_field].append(line)

    order.company = " ".join(values.get("company", [])).strip()
    order.address = ", ".join(values.get("address", [])).strip()
    order.material_text = " ".join(values.get("material", [])).strip()
    order.provided_link = " ".join(values.get("link", [])).strip()


def _detect_languages(lines: Iterable[str], labels: dict):
    """Return ``(form_language, sign_language, raw_value)`` from the note.

    ``form_language`` is whose labels matched -- the marketplace/country the
    order came from. ``sign_language`` is the value the customer selected on
    that form, which is what the TEMPLATE must follow.

    The two are reported separately and the sign language is never inferred
    from the form. Previously a value the lookup did not know fell back to the
    form's language, so a French form + "Anglais" silently printed a French
    sign; the caller now decides what to do about an unknown value and says so.
    """
    for line in lines:
        norm = _normalize(line)
        low = norm.lower()
        for lang, fields in labels.items():
            for lab in fields.get("language", []):
                lab_norm = _normalize(lab).lower()
                if low.startswith(lab_norm):
                    raw = norm[len(lab_norm):].strip()
                    return lang, language_code_for(raw), raw
    return None, None, ""


def _match_label(line: str, label_to_field: list[tuple[str, str]]):
    low = _normalize(line).lower()
    for lab, field in label_to_field:
        if low.startswith(lab):
            return field, line[len(lab):].strip()
    return None, None
