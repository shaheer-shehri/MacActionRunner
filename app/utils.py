"""Small shared helpers used across parsers and the pipeline."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from . import config


def clean(value: object) -> str:
    """Return a trimmed string, treating NaN/None as empty."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def safe_name(value: str) -> str:
    """Turn a county name into a filesystem-safe token: 'St Lucie' -> 'St_Lucie'."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value).strip()).strip("_") or "County"


def to_number(series: pd.Series) -> pd.Series:
    """Coerce a string column that may contain $ and commas into numbers."""
    cleaned = (
        series.astype(str)
        .str.replace(r"[,$]", "", regex=True)
        .str.replace(r"^\s*$", "", regex=True)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def acres_from_sqft(series: pd.Series) -> pd.Series:
    return to_number(series) / config.SQFT_PER_ACRE


def is_vacant_by_text(series: pd.Series) -> pd.Series:
    """True where a land-use description matches any vacant keyword."""
    text = series.fillna("").astype(str).str.upper()
    mask = pd.Series(False, index=series.index)
    for word in config.VACANT_KEYWORDS:
        mask |= text.str.contains(re.escape(word.upper()), regex=True, na=False)
    return mask


def is_government_owner(series: pd.Series) -> pd.Series:
    """True where an owner name looks like a government/institutional entity."""
    text = series.fillna("").astype(str).str.upper()
    mask = pd.Series(False, index=series.index)
    for phrase in config.EXCLUDED_OWNER_WORDS:
        mask |= text.str.contains(re.escape(phrase.upper()), regex=True, na=False)
    return mask


def read_delimited(path: Path, nrows: int | None = None) -> pd.DataFrame:
    """Read a CSV/TSV trying several delimiters and encodings."""
    last_err: Exception | None = None
    for sep in [",", "\t", "|", ";"]:
        for enc in ["utf-8-sig", "latin-1"]:
            try:
                df = pd.read_csv(
                    path, sep=sep, dtype=str, nrows=nrows, encoding=enc,
                    on_bad_lines="skip", low_memory=False,
                )
                if len(df.columns) > 1:
                    return df
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
    raise RuntimeError(f"Could not read {path.name}: {last_err}")


def read_headerless_tsv(path: Path, usecols=None) -> pd.DataFrame:
    """Read a tab-delimited file that has no header row (Florida WebExport)."""
    return pd.read_csv(
        path, sep="\t", header=None, dtype=str, encoding="latin-1",
        on_bad_lines="skip", usecols=usecols, low_memory=False,
    )


def blank_standard_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=config.STANDARD_COLUMNS)


def finalize_standard(df: pd.DataFrame, county: str) -> pd.DataFrame:
    """
    Ensure a parser's output has exactly the standard columns, in order, with the
    county stamped, numeric acreage rounded, and one row per parcel.
    """
    out = df.copy()
    out["County"] = county
    for col in config.STANDARD_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    out = out[config.STANDARD_COLUMNS]

    out["Acreage"] = pd.to_numeric(out["Acreage"], errors="coerce").round(4)
    # Drop rows without an identifier, then de-duplicate on the parcel key.
    out = out[out[config.KEY_COLUMN].map(clean) != ""]
    out = out.drop_duplicates(subset=config.KEY_COLUMN, keep="first")
    return out.reset_index(drop=True)


def combine_name_parts(*parts: pd.Series) -> pd.Series:
    """Join owner name pieces with single spaces, dropping blanks."""
    frame = pd.concat([p.fillna("").astype(str).str.strip() for p in parts], axis=1)
    return frame.apply(lambda row: " ".join(x for x in row if x), axis=1).str.strip()
