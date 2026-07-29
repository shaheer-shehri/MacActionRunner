"""
Orange County certified roll — the standard DOR NAL file (vw_nalf*.csv),
pipe-delimited and self-contained (owner, mailing, situs, land size, DOR code,
values). Parsing this one file avoids joining the 20+ relational tables.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import config
from ..utils import clean, read_delimited, combine_name_parts

NAME = "Orange NAL (vw_nalf)"

_FINGERPRINT = {"strap", "dorcode", "name", "situscity", "landsqft"}


def _nal_file(files: list[Path]) -> Path | None:
    candidates = [p for p in files if p.suffix.lower() == ".csv"]
    # Prefer an obvious NAL filename, else sniff headers.
    named = [p for p in candidates if "nalf" in p.name.lower() or "nal" == p.stem.lower()]
    for p in (named or candidates):
        try:
            cols = {c.strip().lower() for c in read_delimited(p, nrows=3).columns}
            if _FINGERPRINT.issubset(cols):
                return p
        except Exception:  # noqa: BLE001
            continue
    return None


def detect(folder: Path, files: list[Path]) -> bool:
    return _nal_file(files) is not None


def _is_vacant_res(code: pd.Series) -> pd.Series:
    """
    Vacant residential = DOR use code 00 (here written '000'/'0000').
    Only an all-zero code qualifies; '001' is single-family, '004' condo, etc.
    """
    digits = code.fillna("").astype(str).str.replace(r"\D", "", regex=True)
    return (digits != "") & (digits.str.lstrip("0") == "")


def parse(folder: Path, files: list[Path]) -> pd.DataFrame:
    src = _nal_file(files)
    if src is None:
        raise RuntimeError("Orange: NAL file (vw_nalf*.csv) not found")
    df = read_delimited(src)
    df.columns = [c.strip() for c in df.columns]

    out = pd.DataFrame(index=df.index)
    out["Property ID"] = df.get("Strap", df.get("AltKey", "")).map(clean)
    out["Parcel ID"] = df.get("Strap", "").map(clean)
    out["Owner Name"] = df.get("Name", "").map(clean)
    out["Mailing Address"] = combine_name_parts(
        df.get("MailAddr1", pd.Series("", index=df.index)),
        df.get("MailAddr2", pd.Series("", index=df.index)))
    out["Mailing City"] = df.get("MailCity", "").map(clean)
    out["Mailing State"] = df.get("MailState", "").map(clean)
    out["Mailing ZIP"] = df.get("MailZip", "").map(clean).str[:5]
    out["Property Address"] = combine_name_parts(
        df.get("SitusAddr1", pd.Series("", index=df.index)),
        df.get("SitusAddr2", pd.Series("", index=df.index)))
    out["Property City"] = df.get("SitusCity", "").map(clean)
    out["Property ZIP"] = df.get("SitusZip", "").map(clean).str[:5]
    out["Acreage"] = pd.to_numeric(df.get("LandSqFt", pd.Series(index=df.index, dtype=str)),
                                   errors="coerce") / config.SQFT_PER_ACRE
    out["Land Use Code"] = df.get("DORCode", "").map(clean)
    out["Market Value"] = df.get("TotalJust", "").map(clean)
    out["Land Value"] = df.get("LandValue", "").map(clean)
    out["Private Owner"] = "Y"

    vacant = _is_vacant_res(df.get("DORCode", pd.Series("", index=df.index)))
    out = out[vacant].copy()
    out["Vacant"] = "Y"
    out["Land Use"] = "Vacant Residential"
    return out
