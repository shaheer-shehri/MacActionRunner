"""Automatic address matching for disambiguating Places candidates.

Mirrors the manual process: a business name alone returns several candidates, but
the Place ID becomes unique once you also match street + city (and house number).
Only when NO candidate matches does the order fall back to manual review — which
in practice means no Place ID exists yet (new/unprocessed Google listing).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def normalize(s: str) -> str:
    """Lowercase, strip accents, ß->ss, punctuation -> spaces, collapse."""
    if not s:
        return ""
    s = s.replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class ParsedAddress:
    postcode: str = ""
    house_numbers: set[str] = field(default_factory=set)
    street_words: set[str] = field(default_factory=set)
    city_words: set[str] = field(default_factory=set)


def parse_address(addr: str) -> ParsedAddress:
    norm = normalize(addr)
    if not norm:
        return ParsedAddress()
    pm = re.search(r"\b(\d{4,5})\b", norm)      # postal code = pivot
    postcode = pm.group(1) if pm else ""
    if postcode:
        street_seg = norm[:pm.start()]
        city_seg = norm[pm.end():]
    elif "," in addr:
        street_seg, _, city_seg = normalize(addr.split(",", 1)[0]), None, \
            normalize(addr.split(",", 1)[1])
    else:
        street_seg, city_seg = norm, ""
    house = {t for t in re.findall(r"\b\d{1,3}[a-z]?\b", street_seg)}
    street_words = {t for t in street_seg.split() if len(t) >= 3 and not t.isdigit()}
    city_words = {t for t in city_seg.split() if len(t) >= 3 and not t.isdigit()}
    return ParsedAddress(postcode, house, street_words, city_words)


def address_matches(csv_addr: str, candidate_addr: str) -> bool:
    """True if the candidate address is the same place as the CSV address.

    Requires a distinctive street word AND the house number AND a geo anchor
    (postcode or city). The house number is what separates near-identical
    candidates on the same street (e.g. "Oberhofer Weg 21" vs "…Weg 9").
    """
    csv = parse_address(csv_addr)
    cand = normalize(candidate_addr)
    cand_tokens = set(cand.split())

    street_hit = bool(csv.street_words & cand_tokens)
    house_hit = bool(csv.house_numbers & cand_tokens)
    geo_available = bool(csv.postcode or csv.city_words)
    geo_hit = (csv.postcode and csv.postcode in cand_tokens) or \
              bool(csv.city_words & cand_tokens)

    if not csv.house_numbers:
        # No house number: only trust a street + geo match (too weak otherwise).
        return street_hit and geo_available and bool(geo_hit)
    if geo_available:
        return street_hit and house_hit and bool(geo_hit)
    # CSV gave only street + house (no postcode/city): match on that alone.
    return street_hit and house_hit
