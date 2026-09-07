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

# Value written on the language line -> canonical language code.
LANGUAGE_NAME_TO_CODE: dict[str, str] = {
    "deutsch": "DE", "german": "DE",
    "français": "FR", "francais": "FR", "french": "FR",
    "italiano": "IT", "italian": "IT",
    "español": "ES", "espanol": "ES", "spanish": "ES",
    "english": "EN", "englisch": "EN",
}
