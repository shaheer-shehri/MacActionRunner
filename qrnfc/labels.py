"""Multilingual label dictionary for extracting fields from the note text.

Data-driven and extendable: adding a language = adding an entry (ideally via the
shared ``config.xlsx`` ``labels`` tab, which overrides these built-in defaults).

Only DE and FR are verified against the sample CSV. IT / ES / EN strings are
placeholders and MUST be confirmed with the client (open question #5).
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
    # --- PLACEHOLDERS — confirm with client ---
    "IT": {
        "language": ["Seleziona una lingua:"],
        "company": ["Nome dell'azienda:"],
        "address": ["Indirizzo dell'azienda:"],
        "link": ["Link diretto alla recensione Google (opzionale):"],
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
