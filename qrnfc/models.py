"""Domain models shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LinkSource(str, Enum):
    PROVIDED = "provided"        # canonicalized from customer-supplied link
    PLACES = "places"            # built from Google Places API lookup
    MANUAL = "manual"            # operator typed it in
    UNRESOLVED = "unresolved"    # no link could be produced


@dataclass
class Variant:
    """Decoded product variant → identifies the template."""
    language: str    # DE, EN, ES, FR, IT
    shape: str       # D01, D02
    colour: str      # BLK, TRP, WHT
    size: str        # A5, A6
    material_code: str = ""   # e.g. OAK (does not affect template)

    @property
    def template_key(self) -> str:
        return f"{self.language}_{self.shape}_{self.colour}_{self.size}"

    @property
    def layout_key(self) -> str:
        """QR placement is keyed by shape+size only."""
        return f"{self.shape}_{self.size}"


@dataclass
class Order:
    """One parsed CSV row, enriched as it flows through the pipeline."""
    row_index: int
    order_number: str
    sku: str
    raw_note: str
    quantity: int = 1
    tracking: str = ""

    # extracted from the note
    language: Optional[str] = None
    company: str = ""
    address: str = ""
    material_text: str = ""
    provided_link: str = ""

    # resolved
    variant: Optional[Variant] = None
    final_link: str = ""
    link_source: LinkSource = LinkSource.UNRESOLVED
    place_id: str = ""
    resolved_business_name: str = ""     # from Places, used in output filename
    needs_confirmation: bool = False
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    output_path: str = ""

    @property
    def is_resolved(self) -> bool:
        return bool(self.final_link) and self.link_source != LinkSource.UNRESOLVED

    def log(self, msg: str) -> None:
        self.notes.append(msg)
