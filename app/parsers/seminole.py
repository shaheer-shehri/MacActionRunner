"""
Seminole County export (Parcels.csv, largely self-contained).

Parcels.csv carries owner, addresses, DOR code, a Vacant/Improved flag, acreage
and values in one table. MailingLabels.csv adds a cleaner city/state/zip for the
owner mailing address, joined on MasterId.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..utils import clean, read_delimited

NAME = "Seminole (Parcels.csv)"

_FINGERPRINT = {"masterid", "ownername", "vacantimproved", "dorcode"}


def _find(files: list[Path], name: str) -> Path | None:
    for p in files:
        if p.name.lower() == name.lower():
            return p
    return None


def detect(folder: Path, files: list[Path]) -> bool:
    parcels = _find(files, "Parcels.csv")
    if parcels is None:
        return False
    try:
        cols = {c.strip().lower() for c in read_delimited(parcels, nrows=3).columns}
        return _FINGERPRINT.issubset(cols)
    except Exception:  # noqa: BLE001
        return False


def _split_city_state_zip(series: pd.Series) -> pd.DataFrame:
    """Parse 'SANFORD FL 32771' / 'SANFORD, FL 32771-1234'."""
    pattern = r"^(.*?)[,\s]+([A-Z]{2})\s+(\d{5})"
    extracted = series.fillna("").str.upper().str.strip().str.extract(pattern)
    out = pd.DataFrame(index=series.index)
    out["Mailing City"] = extracted[0].fillna("").str.strip()
    out["Mailing State"] = extracted[1].fillna("")
    out["Mailing ZIP"] = extracted[2].fillna("")
    return out


def parse(folder: Path, files: list[Path]) -> pd.DataFrame:
    parcels_file = _find(files, "Parcels.csv")
    if parcels_file is None:
        raise RuntimeError("Seminole: Parcels.csv not found")
    df = read_delimited(parcels_file)
    df.columns = [c.strip().strip('"').lstrip("﻿") for c in df.columns]

    out = pd.DataFrame(index=df.index)
    out["Property ID"] = df.get("MasterId", "").map(clean)
    out["Parcel ID"] = df.get("Parcel", "").map(clean)
    out["Owner Name"] = df.get("OwnerName", "").map(clean)
    out["Property Address"] = df.get("PrimaryAddress", "").map(clean)
    out["Mailing Address"] = df.get("MailingAddress", "").map(clean)
    out["Land Use Code"] = df.get("DORCode", "").map(clean)

    acres = pd.to_numeric(df.get("SUM_LegalAcres", pd.Series(index=df.index, dtype=str)), errors="coerce")
    gis = pd.to_numeric(df.get("SUM_GISAcres", pd.Series(index=df.index, dtype=str)), errors="coerce")
    out["Acreage"] = acres.where(acres.notna() & (acres > 0), gis)

    out["Market Value"] = df.get("TotalJustValue", "").map(clean)
    out["Land Value"] = df.get("AppraisedLandValue", "").map(clean)
    out["Last Sale Date"] = df.get("LastSaleDate", "").map(clean)

    # Vacant residential: the Vacant/Improved flag says Vacant AND the DOR code
    # is in the residential-vacant band (00xx).
    vac_flag = df.get("VacantImproved", pd.Series("", index=df.index)).fillna("").astype(str).str.upper()
    dor = out["Land Use Code"].fillna("").astype(str).str.strip().str.lstrip("0")
    dor_vacant_res = (dor == "") | out["Land Use Code"].astype(str).str.strip().str.zfill(4).str.startswith("00")
    is_vacant = vac_flag.str.contains("VAC") & dor_vacant_res
    out["Vacant"] = is_vacant.map(lambda x: "Y" if x else "")
    out["Land Use"] = out["Vacant"].map(lambda v: "Vacant Residential" if v == "Y" else "")
    out["Private Owner"] = "Y"

    # Better mailing city/state/zip from MailingLabels.csv (CityStateZip).
    labels_file = _find(files, "MailingLabels.csv")
    if labels_file is not None:
        try:
            lab = read_delimited(labels_file)
            lab.columns = [c.strip().strip('"').lstrip("﻿") for c in lab.columns]
            lab["Property ID"] = lab.get("MasterId", "").map(clean)
            csz = _split_city_state_zip(lab.get("CityStateZip", pd.Series("", index=lab.index)))
            lab = pd.concat([lab[["Property ID"]], csz], axis=1).drop_duplicates("Property ID")
            out = out.merge(lab, on="Property ID", how="left")
        except Exception:  # noqa: BLE001
            pass

    return out[out["Vacant"] == "Y"].copy()
