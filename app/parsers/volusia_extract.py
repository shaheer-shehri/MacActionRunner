"""
Volusia County vacant-land extract (a single headered CSV, already filtered to
vacant residential parcels by the county). Columns are lower-case and stable.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..utils import clean, read_delimited, combine_name_parts

NAME = "Volusia vacant extract (CSV)"

_FINGERPRINT = {"altkey", "parcelid", "pc_descr", "situs", "owner1", "acres"}


def detect(folder: Path, files: list[Path]) -> bool:
    csvs = [p for p in files if p.suffix.lower() == ".csv"]
    if any("VOLUSIA" in p.name.upper() and "EXTRACT" in p.name.upper() for p in csvs):
        return True
    for p in csvs:
        try:
            cols = {c.strip().lower() for c in read_delimited(p, nrows=3).columns}
            if _FINGERPRINT.issubset(cols):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _pick_source(files: list[Path]) -> Path:
    csvs = [p for p in files if p.suffix.lower() == ".csv"]
    combined = [p for p in csvs if "COMBINED" in p.name.upper()]
    return combined[0] if combined else csvs[0]


def parse(folder: Path, files: list[Path]) -> pd.DataFrame:
    df = read_delimited(_pick_source(files))
    df.columns = [c.strip().lower() for c in df.columns]

    out = pd.DataFrame(index=df.index)
    out["Property ID"] = df.get("altkey", "").map(clean)
    out["Parcel ID"] = df.get("parcelid", "").map(clean)
    out["Owner Name"] = combine_name_parts(
        df.get("owner1", pd.Series("", index=df.index)),
        df.get("owner2", pd.Series("", index=df.index)))
    out["Mailing Address"] = combine_name_parts(
        df.get("mailaddr1", pd.Series("", index=df.index)),
        df.get("mailaddr2", pd.Series("", index=df.index)),
        df.get("mailaddr3", pd.Series("", index=df.index)))
    out["Mailing City"] = df.get("mailcity", "").map(clean)
    out["Mailing State"] = df.get("mailstate", "").map(clean)
    out["Mailing ZIP"] = df.get("mailzip", "").map(clean).str[:5]
    out["Property Address"] = df.get("situs", "").map(clean)
    out["Property City"] = df.get("situs_city", "").map(clean)
    out["Property ZIP"] = df.get("situs_zip", "").map(clean).str[:5]
    out["Acreage"] = pd.to_numeric(df.get("acres", pd.Series(index=df.index, dtype=str)), errors="coerce")
    out["Land Use"] = df.get("pc_descr", "").map(clean)
    out["Land Use Code"] = df.get("pc_code", "").map(clean)
    out["Market Value"] = df.get("just_val", "").map(clean)
    out["Land Value"] = df.get("land_val", "").map(clean)
    out["Last Sale Date"] = df.get("last_saledt", "").map(clean)
    out["Last Sale Price"] = df.get("last_sale_price", "").map(clean)
    out["Private Owner"] = "Y"
    out["Vacant"] = "Y"
    return out
