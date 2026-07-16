"""Parse the shipping CSV and extract labelled fields from the free-text note.

The note is multi-line. Strategy:
  1. Detect the language first (scan every language's "language" label).
  2. Use that language's label set to slice out company / address / link / material.
  3. Address may span multiple lines until the next known label.
"""
from __future__ import annotations

import csv
from typing import Iterable, Optional

from .labels import DEFAULT_LABELS, LANGUAGE_NAME_TO_CODE
from .models import Order

NOTE_COLUMN = "item_note"
SKU_COLUMN = "item_sku"
ORDER_COLUMN = "order_number"
QTY_COLUMN = "item_quantity"
TRACKING_COLUMN = "tracking_numbers"


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
            )
            _extract_fields(order, labels)
            orders.append(order)
    return orders


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

    # Sign language (for the template) comes from the language line's value.
    lang = _detect_language(lines, labels)
    order.language = lang
    if lang is None:
        order.log("could not detect language")

    # Extract fields by matching labels from ALL languages: the note's label
    # language can differ from the selected sign language (e.g. an "Englisch"
    # order whose note still uses German labels). Longer labels first so a more
    # specific label wins over a shorter prefix.
    label_to_field: list[tuple[str, str]] = []
    for langset in labels.values():
        for field, variants in langset.items():
            for lab in variants:
                label_to_field.append((lab.lower(), field))
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


def _detect_language(lines: Iterable[str], labels: dict) -> Optional[str]:
    for line in lines:
        low = line.lower()
        for lang, fields in labels.items():
            for lab in fields.get("language", []):
                if low.startswith(lab.lower()):
                    value = line[len(lab):].strip().lower()
                    # value like "Deutsch" -> DE; fall back to label's own language
                    return LANGUAGE_NAME_TO_CODE.get(value, lang)
    return None


def _match_label(line: str, label_to_field: list[tuple[str, str]]):
    low = line.lower()
    for lab, field in label_to_field:
        if low.startswith(lab):
            return field, line[len(lab):].strip()
    return None, None
