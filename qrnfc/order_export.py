"""Write the per-order export file (``output/export.csv``).

One row per ORDER, to the client's data contract:

    Order number | Recipient | Business name | Link | Tracking number | Filename

This sits alongside ``links.csv`` rather than replacing it, because the two
answer different questions:

  * ``links.csv``  — one row per PRINT FILE, with the number of tags to write.
    The NFC-writing worklist: the operator works down it chip by chip.
  * ``export.csv`` — one row per ORDER, keyed on the order number. The matching
    document: which parcel is this, who is it going to, which sign is in it.

Two names on one row are deliberately different things:

  * **Recipient** — the Amazon orderer, matching the DHL shipping label.
  * **Business name** — the company the review link points at, printed on the
    sign. "Andreas Fercher" can order a sign for "Lastenrad Manufaktur", so
    these must never be collapsed into one field.

An order that needs several different signs (different address or variant, the
``A1``/``A2`` case) still gets ONE row: the multi-valued cells list their values
in sign order separated by ``" | "``, so Business name, Link and Filename line
up positionally. Values that are identical across the signs collapse to a
single value instead of being repeated.

Semicolon-separated, UTF-8 **with BOM** — same convention as ``links.csv``,
because a German Excel splits on ``;`` and without the BOM decodes the file as
cp1252 ("Pfotenglück" -> "PfotenglÃ¼ck").
"""
from __future__ import annotations

import csv
import os
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime

FILENAME = "export.csv"
DELIMITER = ";"
MULTI_SEP = " | "

COLUMNS = ["Order number", "Recipient", "Business name", "Link",
           "Tracking number", "Filename"]


@dataclass
class OrderRow:
    order_number: str
    recipient: str
    business_name: str
    link: str
    tracking: str
    filename: str

    def as_record(self) -> list:
        return [self.order_number, self.recipient, self.business_name,
                self.link, self.tracking, self.filename]


def _join(values) -> str:
    """Join one cell's values, dropping blanks and collapsing duplicates.

    A two-sign order at the same business shows that business once, not twice,
    while two genuinely different businesses are both listed.
    """
    seen = OrderedDict()
    for v in values:
        v = (v or "").strip()
        if v:
            seen[v] = None
    return MULTI_SEP.join(seen)


def _business_name(order) -> str:
    """The company the review link actually points at.

    Prefer the name Places resolved, since that IS the listing behind the Place
    ID; fall back to what the customer typed in the note.
    """
    return (getattr(order, "resolved_business_name", "") or "").strip() \
        or (order.company or "").strip()


def rows_from_orders(orders) -> list[OrderRow]:
    """One row per order number, in first-seen order.

    Rows merged into another print file (identical duplicate signs) are skipped
    so a quantity-2 order does not list its business and link twice -- the
    quantity lives in the filename prefix ("2x") and in links.csv.
    """
    groups: "OrderedDict[str, list]" = OrderedDict()
    for o in orders:
        if not getattr(o, "emits_file", True):
            continue
        groups.setdefault(o.order_number, []).append(o)

    rows: list[OrderRow] = []
    for order_number, items in groups.items():
        items = sorted(items, key=lambda r: getattr(r, "sign_index", 0))
        rows.append(OrderRow(
            order_number=order_number,
            recipient=_join(getattr(i, "recipient", "") for i in items),
            business_name=_join(_business_name(i) for i in items),
            # Unresolved orders keep their row with an empty link: a blank cell
            # is far easier to spot than a missing row.
            link=_join(i.final_link for i in items),
            tracking=_join(i.tracking for i in items),
            filename=_join(os.path.basename(i.output_path) if i.output_path
                           else "" for i in items),
        ))
    return rows


def write_csv(out_path: str, rows: list[OrderRow]) -> str:
    """Write the export. Returns the path actually written.

    Falls back to a timestamped copy when the file is open in Excel (Windows
    locks it), rather than failing a finished print run over the export.
    """
    try:
        return _write(out_path, rows)
    except PermissionError:
        stem, ext = os.path.splitext(out_path)
        return _write(f"{stem}_{datetime.now():%Y%m%d-%H%M%S}{ext}", rows)


def _write(path: str, rows: list[OrderRow]) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=DELIMITER, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow(r.as_record())
    return path


def append_rows(path: str, rows: list[OrderRow]) -> str:
    """Append to an existing export (used by manually-created print files),
    writing the header first if the file isn't there yet."""
    if not os.path.isfile(path):
        return write_csv(path, rows)
    try:
        with open(path, "a", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=DELIMITER, quoting=csv.QUOTE_MINIMAL)
            for r in rows:
                w.writerow(r.as_record())
        return path
    except PermissionError:
        stem, ext = os.path.splitext(path)
        return _write(f"{stem}_{datetime.now():%Y%m%d-%H%M%S}{ext}", rows)
