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

    # Filename prefix decision (see pipeline._assign_sign_groups):
    #   Case 1 – every sign in the order is identical (same address AND variant):
    #            one print file, quantity prefix -> "1x" / "2x" / "3x".
    #   Case 2 – the order needs several DIFFERENT print files (different address
    #            or variant): one letter per order + number per distinct file ->
    #            "A1", "A2"… (plus its quantity if a file is needed more than once).
    group_prefix: Optional[str] = None      # letter for Case 2; None for Case 1
    sign_index: int = 0                     # 1..N within a Case-2 order
    copies: int = 1                         # identical copies this file covers
    file_prefix: str = ""                   # "1x" / "2x" / "A1" / "A2_2x"
    emits_file: bool = True                 # False = duplicate row merged elsewhere
    output_path: str = ""
    output_paths: list[str] = field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        return bool(self.final_link) and self.link_source != LinkSource.UNRESOLVED

    def log(self, msg: str) -> None:
        self.notes.append(msg)
