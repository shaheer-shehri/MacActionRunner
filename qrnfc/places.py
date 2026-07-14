"""Google Places lookup: company + address -> candidate Place IDs.

Wrapped behind a small interface so the pipeline can auto-disambiguate multiple
candidates by address (see qrnfc.matching) instead of prompting a human. Requires
a Places API key restricted to the Places API + a billing budget cap.

Volume is tiny (only orders lacking a valid direct link hit the API), so this
stays well inside the free monthly tier. Results are cached per (company,address)
so a repeated business is never looked up twice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .review_link import link_from_place_id


@dataclass
class PlaceCandidate:
    place_id: str
    name: str = ""
    formatted_address: str = ""
    review_link: str = ""

    def __post_init__(self):
        if not self.review_link:
            self.review_link = link_from_place_id(self.place_id)


class PlacesClient:
    """Thin wrapper over googlemaps.Client. Import is lazy so the app runs
    (parsing, template resolution) even when the SDK/key are absent."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Places API key required")
        import googlemaps  # lazy
        self._gm = googlemaps.Client(key=api_key)
        self._cache: dict[tuple[str, str], list[PlaceCandidate]] = {}

    def find_candidates(self, company: str, address: str) -> list[PlaceCandidate]:
        key = (company.strip().lower(), address.strip().lower())
        if key in self._cache:
            return self._cache[key]
        cands = self._find_place(company, address)
        if not cands:                       # broaden via text search
            cands = self._text_search(f"{company} {address}".strip())
        if not cands and company:
            cands = self._text_search(company)
        self._cache[key] = cands
        return cands

    def _find_place(self, company: str, address: str) -> list[PlaceCandidate]:
        query = ", ".join(p for p in (company, address) if p)
        res = self._gm.find_place(
            input=query, input_type="textquery",
            fields=["place_id", "name", "formatted_address"],
        )
        return [self._to_cand(c) for c in res.get("candidates", [])]

    def _text_search(self, query: str) -> list[PlaceCandidate]:
        if not query:
            return []
        res = self._gm.places(query=query)
        return [self._to_cand(c) for c in res.get("results", [])]

    @staticmethod
    def _to_cand(c: dict) -> PlaceCandidate:
        return PlaceCandidate(
            place_id=c.get("place_id", ""),
            name=c.get("name", ""),
            formatted_address=c.get("formatted_address", c.get("vicinity", "")),
        )
