"""Multilingual label dictionary for extracting fields from the note text.

Data-driven and extendable: adding a language = adding an entry (ideally via the
shared ``config.xlsx`` ``labels`` tab, which overrides these built-in defaults).

DE, FR and IT are verified against real orders (IT confirmed 2026-08 from
processed-parcels-20260801-174518.csv — see the two ``per recensioni`` link
variants below, and note real IT notes use a curly apostrophe (’) in
"dell’azienda", not a straight one; matching is quote-insensitive, see
``csv_parser._normalize``, so future label additions don't need to special-case
this by hand). ES / EN strings are still placeholders and MUST be confirmed
with the client (open question #5) — do not assume they're right just because
the IT ones turned out to need fixing.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

# field -> list of accepted label prefixes (case-insensitive, matched at line start)
DEFAULT_LABELS: dict[str, dict[str, list[str]]] = {
    "DE": {
        "language": ["Bitte wählen Sie eine Sprache:"],
        "company": ["Name des Unternehmens:"],
        "address": ["Anschrift des Unternehmens:"],
        "link": ["Direkter Google Bewertungslink (optional):"],
        "material": ["Material:"],
    },
    "FR": {
        "language": ["Langue du support:"],
        "company": ["Nom de l'entreprise (identique à Google Business):",
                    "Nom de l’entreprise (identique à Google Business):"],
        "address": ["Adresse complète de l'entreprise (identique à Google Business):",
                    "Adresse complète de l’entreprise (identique à Google Business):"],
        "link": ["Lien vers vos avis Google (optionnel):"],
        "material": ["Matériau:"],
    },
    # Confirmed 2026-08 against real orders (processed-parcels-20260801-174518.csv).
    # Company/address apostrophe form doesn't matter (see module docstring); the
    # original "alla recensione" link guess was simply wrong wording and is kept
    # only as a fallback in case an older/different order used it.
    "IT": {
        "language": ["Seleziona una lingua:"],
        "company": ["Nome dell'azienda:"],
        "address": ["Indirizzo dell'azienda:"],
        "link": ["Link diretto per recensioni Google (opzionale):",
                 "Link diretto alla recensione Google (opzionale):"],
        "material": ["Materiale:"],
    },
    "ES": {
        "language": ["Seleccione un idioma:"],
        "company": ["Nombre de la empresa:"],
        "address": ["Dirección de la empresa:"],
        "link": ["Enlace directo de reseña de Google (opcional):"],
        "material": ["Material:"],
    },
    "EN": {
        "language": ["Please select a language:"],
        "company": ["Company name:"],
        "address": ["Company address:"],
        "link": ["Direct Google review link (optional):"],
        "material": ["Material:"],
    },
}

# Sign-language options AS WRITTEN IN EACH FORM LANGUAGE (the 5x5 matrix).
#
# A checkout form in language F lists the sign options in F's own words, so a
# French customer who picks an English sign sends "Anglais" -- not "English".
# Detecting the ORDERED sign language therefore needs every language's name in
# every language, not just each language's name in its own tongue.
#
# The old map held only 12 names (each language in itself, plus the English
# names). Every cross-language combination it was missing fell through to the
# FORM's language, which printed the wrong template: a French form + English
# sign came out French. Keep all five columns filled when adding a language.
#
#                   as written in:  DE            EN          ES          FR           IT
LANGUAGE_NAMES: dict[str, list[str]] = {
    "DE": ["Deutsch",      "German",   "Alemán",   "Allemand",  "Tedesco"],
    "EN": ["Englisch",     "English",  "Inglés",   "Anglais",   "Inglese"],
    "ES": ["Spanisch",     "Spanish",  "Español",  "Espagnol",  "Spagnolo"],
    "FR": ["Französisch", "French", "Francés", "Français", "Francese"],
    "IT": ["Italienisch",  "Italian",  "Italiano",  "Italien",   "Italiano"],
}


def fold(value: str) -> str:
    """Accent- and punctuation-insensitive key for a language value.

    "Inglés", "INGLES" and "ingles " all fold to "ingles", so the matrix above
    can be written with its natural spelling while still matching whatever the
    form actually sent.
    """
    s = (value or "").lower().replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# Folded language name -> canonical code, derived from the matrix above.
LANGUAGE_NAME_TO_CODE: dict[str, str] = {
    fold(name): code for code, names in LANGUAGE_NAMES.items() for name in names
}


def language_code_for(value: str) -> Optional[str]:
    """Map a selected sign-language value to its code, or None if unknown.

    Exact match first, then the longest matching prefix so a decorated value
    ("Deutsch / German", "Italiano (IT)") still resolves. The prefix step is
    safe because no two names in the matrix share a prefix while pointing at
    different codes ("italien"/"italienisch"/"italiano" are all IT).

    Returning None rather than guessing is deliberate: the caller must be able
    to tell "the customer picked Spanish" from "we could not tell", because
    falling back silently is what printed wrong-language signs.
    """
    v = fold(value)
    if not v:
        return None
    code = LANGUAGE_NAME_TO_CODE.get(v)
    if code:
        return code
    for name in sorted(LANGUAGE_NAME_TO_CODE, key=len, reverse=True):
        if v.startswith(name):
            return LANGUAGE_NAME_TO_CODE[name]
    return None
