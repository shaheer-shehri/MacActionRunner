"""
Lake County NAL extract (Florida DOR "Name-Address-Legal" roll, as XLSX).

The main file NALExtractPublic_*.xlsx already contains owner, mailing address,
physical address, land value, lot square footage and the DOR land-use code — so
it can be read on its own. Land use is a numeric DOR code (0000 = vacant
residential) rather than a text description.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import config
from ..utils import clean, combine_name_parts

NAME = "Lake NAL (XLSX)"

# Columns that fingerprint an NAL public extract.
_FINGERPRINT = {"PIN", "DOR_LUC", "Owners_Name", "Land_Square_Feet"}


def _nal_file(files: list[Path]) -> Path | None:
    xlsx = [p for p in files if p.suffix.lower() in {".xlsx", ".xls"}]
    named = [p for p in xlsx if "NAL" in p.name.upper()]
    for candidate in (named or xlsx):
        try:
            cols = set(pd.read_excel(candidate, nrows=1, dtype=str).columns)
            if _FINGERPRINT.issubset(cols):
                return candidate
        except Exception:  # noqa: BLE001
            continue
    return None


def detect(folder: Path, files: list[Path]) -> bool:
    return _nal_file(files) is not None


def _dor_is_vacant_res(codes: pd.Series) -> pd.Series:
    stripped = codes.fillna("").astype(str).str.strip()
    normalized = stripped.str.lstrip("0")
    # DOR 0000 -> "" after stripping zeros; 0010 -> "10".
    is_zero = normalized == ""
    return is_zero | stripped.isin(config.VACANT_DOR_CODES) | normalized.isin({"10"})


def parse(folder: Path, files: list[Path]) -> pd.DataFrame:
    src = _nal_file(files)
    if src is None:
        raise RuntimeError("Lake NAL: could not locate NALExtractPublic_*.xlsx")
    df = pd.read_excel(src, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    out = pd.DataFrame(index=df.index)
    out["Property ID"] = df.get("Alternate_Key", df.get("PIN", "")).map(clean)
    out["Parcel ID"] = df.get("PIN", "").map(clean)
    out["Owner Name"] = df.get("Owners_Name", "").map(clean)
    out["Mailing Address"] = combine_name_parts(
        df.get("Mailing_Address_1", pd.Series("", index=df.index)),
        df.get("Mailing_Address_2", pd.Series("", index=df.index)))
    out["Mailing City"] = df.get("City", "").map(clean)
    out["Mailing State"] = df.get("State", "").map(clean)
    out["Mailing ZIP"] = df.get("Zip_4", "").map(clean).str[:5]
    out["Property Address"] = combine_name_parts(
        df.get("Physical_Address_1", pd.Series("", index=df.index)),
        df.get("Physical_Address_2", pd.Series("", index=df.index)))
    out["Property City"] = df.get("Physical_City", "").map(clean)
    out["Property ZIP"] = df.get("Physical_Zip", "").map(clean).str[:5]
    out["Acreage"] = pd.to_numeric(df.get("Land_Square_Feet", pd.Series(index=df.index, dtype=str)),
                                   errors="coerce") / config.SQFT_PER_ACRE
    out["Land Use Code"] = df.get("DOR_LUC", "").map(clean)
    out["Land Use"] = out["Land Use Code"].map(lambda c: "Vacant Residential" if c else "")
    out["Market Value"] = df.get("Total_JV", "").map(clean)
    out["Land Value"] = df.get("Land_Val", "").map(clean)
    out["Private Owner"] = "Y"

    vacant = _dor_is_vacant_res(df.get("DOR_LUC", pd.Series("", index=df.index)))
    out = out[vacant].copy()
    out["Vacant"] = "Y"
    out["Land Use"] = "Vacant Residential"
    return out
