"""
Florida WebExport format (tab-delimited, headerless WebExport_*.TXT files).

Used by Brevard and Indian River County assessor downloads. The export is a set
of related tables (PROPERTY, LAND, OWNER, VALUES, SALES) that are joined on the
Property ID. Column positions follow the standard Florida DOR WebExport layout.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..utils import (
    clean, read_headerless_tsv, combine_name_parts, is_vacant_by_text,
)

NAME = "Florida WebExport (Brevard / Indian River)"


def detect(folder: Path, files: list[Path]) -> bool:
    return any(p.name.upper().startswith("WEBEXPORT_PROPERTY_") for p in files)


def _find(files: list[Path], token: str) -> Path | None:
    token = token.upper()
    matches = [p for p in files if p.name.upper().startswith(f"WEBEXPORT_{token}_")]
    return matches[0] if matches else None


def _split_location(series: pd.Series) -> pd.DataFrame:
    """Split 'STREET  CITY, FL 32958' into address / city / zip parts."""
    pattern = r"^(.*?)\s+([A-Z][A-Z .'-]+),\s*FL\s+(\d{5})\s*$"
    extracted = series.fillna("").str.strip().str.extract(pattern)
    out = pd.DataFrame(index=series.index)
    out["Property Address"] = extracted[0].fillna(series.fillna("").str.strip())
    out["Property City"] = extracted[1].fillna("").str.strip()
    out["Property ZIP"] = extracted[2].fillna("")
    return out


def parse(folder: Path, files: list[Path]) -> pd.DataFrame:
    property_file = _find(files, "PROPERTY")
    land_file = _find(files, "LAND")
    owner_file = _find(files, "OWNER")
    values_file = _find(files, "VALUES")
    sales_file = _find(files, "SALES")
    improvement_file = _find(files, "IMPROVEMENT")

    missing = [name for name, path in
               {"PROPERTY": property_file, "LAND": land_file, "OWNER": owner_file}.items()
               if path is None]
    if missing:
        raise RuntimeError(
            "WebExport county is missing required file(s): " + ", ".join(missing))

    # --- PROPERTY: id, parcel, location, acreage ---
    prop = read_headerless_tsv(property_file, usecols=[0, 1, 2, 3, 19])
    prop.columns = ["Property ID", "Tax Year", "Parcel ID", "Property Location", "Property Acres"]
    prop["Property ID"] = prop["Property ID"].map(clean)
    prop["Parcel ID"] = prop["Parcel ID"].map(clean).str.replace(r"\.0$", "", regex=True)
    prop = pd.concat([prop.drop(columns=["Property Location"]),
                      _split_location(prop["Property Location"])], axis=1)

    # --- LAND: use code / description / acreage / land value ---
    land = read_headerless_tsv(land_file, usecols=[0, 2, 3, 14, 18, 22])
    land.columns = ["Property ID", "Land Use Code", "Land Use Subcode",
                    "Land Use", "Land Market Value", "Acreage"]
    land["Property ID"] = land["Property ID"].map(clean)
    land["Land Use"] = land["Land Use"].fillna("").astype(str).str.strip()
    land["Acreage"] = pd.to_numeric(land["Acreage"], errors="coerce")

    # Keep only vacant residential land rows; keep the largest qualifying lot per parcel.
    land = land[is_vacant_by_text(land["Land Use"])].copy()

    # Exclude parcels that have improvements (a building) if that table exists.
    if improvement_file is not None:
        imp = read_headerless_tsv(improvement_file, usecols=[0])
        improved_ids = set(imp[0].dropna().astype(str).str.strip())
        if improved_ids:
            land = land[~land["Property ID"].isin(improved_ids)].copy()

    land = (land.sort_values(["Property ID", "Acreage"], ascending=[True, False])
                .drop_duplicates("Property ID"))

    # --- OWNER: primary owner + mailing address ---
    owners = read_headerless_tsv(owner_file, usecols=[0, 2, 3, 4, 5, 6, 7, 8, 9])
    owners.columns = ["Property ID", "Primary", "Owner Name", "Owner Name 2",
                      "Mailing Address", "Mailing Address 2", "Mailing City",
                      "Mailing State", "Mailing ZIP"]
    owners["Property ID"] = owners["Property ID"].map(clean)
    owners["Primary"] = owners["Primary"].fillna("").astype(str).str.upper().str.strip()
    owners = (owners.sort_values(["Property ID", "Primary"], ascending=[True, False])
                    .drop_duplicates("Property ID"))
    owners["Owner Name"] = combine_name_parts(owners["Owner Name"], owners["Owner Name 2"])
    owners["Mailing Address"] = combine_name_parts(
        owners["Mailing Address"], owners["Mailing Address 2"])
    owners = owners.drop(columns=["Primary", "Owner Name 2", "Mailing Address 2"])

    result = land.merge(prop, on="Property ID", how="left").merge(owners, on="Property ID", how="left")

    # --- VALUES ---
    if values_file is not None:
        values = read_headerless_tsv(values_file, usecols=[0, 2, 5])
        values.columns = ["Property ID", "Market Value", "Land Value"]
        values["Property ID"] = values["Property ID"].map(clean)
        values = values.drop_duplicates("Property ID")
        result = result.merge(values, on="Property ID", how="left")
    else:
        result["Market Value"] = ""
        result["Land Value"] = result["Land Market Value"]

    # --- SALES (most recent) ---
    if sales_file is not None:
        sales = read_headerless_tsv(sales_file, usecols=[0, 4, 11])
        sales.columns = ["Property ID", "Last Sale Date", "Last Sale Price"]
        sales["Property ID"] = sales["Property ID"].map(clean)
        sales["_d"] = pd.to_datetime(sales["Last Sale Date"], errors="coerce")
        sales = sales.sort_values(["Property ID", "_d"]).drop_duplicates("Property ID", keep="last")
        result = result.merge(sales.drop(columns=["_d"]), on="Property ID", how="left")
    else:
        result["Last Sale Date"] = ""
        result["Last Sale Price"] = ""

    result["Private Owner"] = "Y"
    result["Vacant"] = "Y"
    return result
