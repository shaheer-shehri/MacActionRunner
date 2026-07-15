"""Decode the SKU + note into a Variant and resolve its template file.

SKU example: ``NFC_D02_WHT-A5`` -> shape D02, colour WHT, size A5.
Language comes from the parsed note (``order.language``).
Material comes from the note text, mapped to a short code (e.g. OAK) that is
only used in the output filename — it does NOT change the template.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from .models import Order, Variant

SHAPES = {"D01", "D02"}
COLOURS = {"BLK", "TRP", "WHT", "HDF"}
SIZES = {"A5", "A6"}

# Material only ever appears as text in the CSV "Material:" line; it never
# changes the template (proven: the template set has no material axis — 60 files
# = lang x shape x colour x size). It is used solely as the last filename part.
#
# Per client spec: only Oak -> OAK and Walnut -> WNT are coded; anything else
# (plain MDF etc.) leaves the material part EMPTY. Wood names may appear in any
# store language, so each code lists its DE/EN/FR/IT/ES translations.
MATERIAL_CODES = {
    "OAK": ["eiche", "oak", "chêne", "chene", "rovere", "quercia", "roble"],
    "WNT": ["walnuss", "nussbaum", "walnut", "noyer", "noce", "nogal", "noce nazionale"],
}

_SKU_RE = re.compile(r"(D0\d)[_-]?(BLK|TRP|WHT|HDF)[_-]?(A\d)", re.IGNORECASE)


def decode_variant(order: Order) -> Optional[Variant]:
    m = _SKU_RE.search(order.sku.upper())
    if not m or not order.language:
        order.log(f"cannot decode SKU '{order.sku}' (lang={order.language})")
        return None
    shape, colour, size = m.group(1).upper(), m.group(2).upper(), m.group(3).upper()
    material_code = _material_code(order.material_text, order)
    v = Variant(order.language, shape, colour, size, material_code)
    order.variant = v
    return v


def _material_code(material_text: str, order: Optional[Order] = None) -> str:
    low = material_text.lower()
    for code, keywords in MATERIAL_CODES.items():
        if any(k in low for k in keywords):
            return code
    # Not oak/walnut (e.g. plain MDF) -> no material part in the filename.
    return ""


def resolve_template_path(templates_root: str, variant: Variant) -> Optional[str]:
    """Find the PNG template. Filenames in the supplied set are messy
    (trailing spaces, ' copy', double spaces), so match tolerantly."""
    lang_dir = os.path.join(templates_root, variant.language)
    if not os.path.isdir(lang_dir):
        return None
    prefix = f"{variant.language}_{variant.shape}_{variant.colour}_{variant.size}"
    norm_prefix = prefix.lower().replace(" ", "")
    for name in os.listdir(lang_dir):
        if not name.lower().endswith(".png"):
            continue
        stem = os.path.splitext(name)[0].lower()
        stem = stem.replace("copy", "").replace(" ", "").rstrip("_")
        if stem == norm_prefix or stem.startswith(norm_prefix):
            return os.path.join(lang_dir, name)
    return None
