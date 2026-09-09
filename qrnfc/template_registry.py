"""Editable template/variant registry — ``config/templates.csv``.

This is the "external table as a database" option: the client adds a new stand
variant (a new colour code, a new material) by adding ONE row here and dropping
the PNGs into ``templates/<LANG>/``. No code change, no rebuild.

    Code;QR colour;Description
    BLK;white;Black acrylic - white text/QR
    HDF;white;Wood / HDF - white text/QR

``Code`` is the token that appears in the SKU between shape and size
(``NFC_D02_<CODE>-A5``) and in the template filename
(``<LANG>_<SHAPE>_<CODE>_<SIZE>.png``). ``QR colour`` is the only visual
variation across the range: ``white`` for dark stock (black acrylic, wood),
``black`` for light stock (white/transparent acrylic).

Language, shape and size are NOT rows here - they are already derived from the
SKU and the folder layout, so listing all 80 combinations would be busywork.

Semicolon-separated + UTF-8 BOM so it opens correctly in a German Excel, same
convention as the generated links.csv.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass

FILENAME = "templates.csv"
DELIMITER = ";"
COLUMNS = ["Code", "QR colour", "Description"]

WHITE = "white"
BLACK = "black"

# Shipped defaults - what the range was before the registry existed.
DEFAULT_ROWS = [
    ("BLK", WHITE, "Black acrylic - white text/QR"),
    ("WHT", BLACK, "White acrylic - black text/QR"),
    ("TRP", BLACK, "Transparent acrylic - black text/QR"),
    ("HDF", WHITE, "Wood / HDF - white text/QR"),
]


@dataclass(frozen=True)
class TemplateVariant:
    code: str
    qr_colour: str          # "white" | "black"
    description: str = ""

    @property
    def qr_white(self) -> bool:
        return self.qr_colour.strip().lower() == WHITE


def default_variants() -> list[TemplateVariant]:
    return [TemplateVariant(c, q, d) for c, q, d in DEFAULT_ROWS]


def path_in(root: str) -> str:
    return os.path.join(root, "config", FILENAME)


def write_default(path: str) -> bool:
    """Create the table if absent. Never overwrites - the client's edits win."""
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=DELIMITER)
        w.writerow(COLUMNS)
        w.writerows(DEFAULT_ROWS)
    return True


def load(root: str) -> list[TemplateVariant]:
    """Read the registry, falling back to the built-in defaults.

    A malformed or empty table falls back rather than raising: a typo in a
    spreadsheet must not stop a print run.
    """
    path = path_in(root)
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh, delimiter=DELIMITER))
    except (FileNotFoundError, OSError):
        return default_variants()

    out: list[TemplateVariant] = []
    for r in rows:
        code = (r.get("Code") or "").strip().upper()
        if not code or not code.isalnum():
            continue
        colour = (r.get("QR colour") or "").strip().lower()
        if colour not in (WHITE, BLACK):
            colour = WHITE if code in ("BLK", "HDF") else BLACK
        out.append(TemplateVariant(code, colour, (r.get("Description") or "").strip()))
    return out or default_variants()


def codes(variants: list[TemplateVariant]) -> tuple[str, ...]:
    return tuple(v.code for v in variants)


def white_qr_codes(variants: list[TemplateVariant]) -> tuple[str, ...]:
    return tuple(v.code for v in variants if v.qr_white)
