"""Write the NFC-writing worklist: one row per print file, with the link to encode.

Workflow this serves: after printing a sign, the operator finds its row here,
copies the review link and pastes it into the NFC writer software.

Format is semicolon-separated CSV written as UTF-8 **with BOM**. Both details
matter: Excel in a German locale splits on ``;`` (a comma-separated file lands in
one column) and without the BOM it decodes the file as cp1252, turning
"Pfotenglück" into "Pfotenglück". The file opens the same way in LibreOffice,
Numbers or any text editor, and needs no extra dependency.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime

FILENAME = "links.csv"
DELIMITER = ";"

COLUMNS = ["Order number", "Sign", "Company", "Address", "Tags to write",
           "Review link", "Place ID", "Source", "Print file"]


@dataclass
class LinkRow:
    order_number: str
    sign: str            # "A1"/"A2" for multi-sign orders, blank otherwise
    company: str
    address: str
    tags: int            # how many chips carry this link
    link: str
    place_id: str
    source: str          # provided / places / manual / unresolved
    print_file: str

    def as_record(self) -> list:
        return [self.order_number, self.sign, self.company, self.address,
                self.tags, self.link, self.place_id, self.source, self.print_file]


def rows_from_orders(orders) -> list[LinkRow]:
    """One row per print file. Rows merged into another file (identical signs)
    are skipped — their quantity is already counted in ``copies`` on the row that
    emits the file, so the operator writes N chips from a single row."""
    rows: list[LinkRow] = []
    for o in orders:
        if not o.emits_file:
            continue
        marker = f"{o.group_prefix}{o.sign_index}" if o.group_prefix else ""
        rows.append(LinkRow(
            order_number=o.order_number,
            sign=marker,
            company=o.company,
            address=" ".join((o.address or "").split()),
            tags=max(1, o.copies),
            link=o.final_link,
            place_id=o.place_id,
            # unresolved rows are kept, with an empty link: a missing row is
            # easier to overlook than a visible blank one
            source=o.link_source.value,
            print_file=os.path.basename(o.output_path) if o.output_path else "",
        ))
    return rows


def write_csv(out_path: str, rows: list[LinkRow]) -> str:
    """Write the worklist. Returns the path actually written.

    The operator keeps this file open in Excel while writing chips, which locks
    it on Windows; rather than failing the run, fall back to a timestamped copy.
    """
    try:
        return _write(out_path, rows)
    except PermissionError:
        stem, ext = os.path.splitext(out_path)
        alt = f"{stem}_{datetime.now():%Y%m%d-%H%M%S}{ext}"
        return _write(alt, rows)


def _write(path: str, rows: list[LinkRow]) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=DELIMITER, quoting=csv.QUOTE_MINIMAL)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow(r.as_record())
    return path
