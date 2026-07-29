"""
Format detection.

Each county folder dropped into Input/ is inspected and matched to a known
format parser. Parsers are tried in priority order (most specific first). If
nothing matches, the county is reported as UNRECOGNIZED with a clear message
about what columns were found, so the operator knows what needs mapping — the
system never guesses and never produces incorrect results silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .parsers import (
    webexport, stlucie_cama, volusia_extract, lake_nal,
    seminole, polk, orange_nal, generic,
)
from .utils import read_delimited

# Priority order: specific fingerprinted formats first, generic last.
PARSERS = [
    webexport,       # Brevard, Indian River (WebExport_*.TXT)
    stlucie_cama,    # St Lucie CAMA multi-CSV
    volusia_extract, # Volusia *_VACANT_*_EXTRACT.csv
    lake_nal,        # Lake NAL XLSX
    seminole,        # Seminole Parcels.csv
    polk,            # Polk FTP CAMA (ftp_parcel/owner/sales)
    orange_nal,      # Orange NAL (vw_nalf pipe-delimited)
    generic,         # best-effort single headered file (last resort)
]

DATA_SUFFIXES = {".txt", ".csv", ".xlsx", ".xls"}


@dataclass
class Detection:
    county: str
    folder: Path
    files: list[Path]
    parser: object | None          # parser module, or None if unrecognized
    format_name: str
    reason: str                    # human-readable explanation


def list_data_files(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.rglob("*")
        if p.is_file()
        and p.suffix.lower() in DATA_SUFFIXES
        and not p.name.startswith(".")
        and "__MACOSX" not in p.parts
    )


def _describe_columns(files: list[Path]) -> str:
    """Peek at the first readable file and list its columns for the report."""
    for path in files:
        if path.suffix.lower() in {".txt", ".csv"}:
            try:
                sample = read_delimited(path, nrows=5)
                cols = ", ".join(str(c) for c in sample.columns[:25])
                return f"'{path.name}' columns: {cols}"
            except Exception:  # noqa: BLE001
                continue
    names = ", ".join(p.name for p in files[:10])
    return f"files present: {names}"


def detect(county: str, folder: Path) -> Detection:
    files = list_data_files(folder)
    if not files:
        return Detection(county, folder, files, None, "EMPTY",
                         f"No .txt/.csv/.xlsx data files found in '{folder.name}'.")

    for parser in PARSERS:
        try:
            if parser.detect(folder, files):
                return Detection(county, folder, files, parser, parser.NAME,
                                 f"Detected format: {parser.NAME}")
        except Exception:  # noqa: BLE001
            continue

    hint = _describe_columns(files)
    reason = (
        f"UNRECOGNIZED format for county '{county}'. The app stopped this county "
        f"so it does not produce incorrect results.\n"
        f"    What was found -> {hint}\n"
        f"    To enable it, a parser mapping is needed for owner name, parcel ID, "
        f"acreage (or lot size), and land-use. Send these column names to your developer."
    )
    return Detection(county, folder, files, None, "UNRECOGNIZED", reason)
