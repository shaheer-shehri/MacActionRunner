"""
St Lucie County CAMA export (a folder of related CSV tables that must be joined).

The download splits data across PropertyIdentification.csv (parcel + land use +
lot area), PropertyOwnership.csv (owner + mailing address) and Assessment.csv
(values). The old generic importer read only ONE table, so its output had no
owner, no mailing address and lot area in square feet — unusable for skip trace.
This parser joins the tables on PropertyID and converts area to acres.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..utils import clean, read_delimited, combine_name_parts, acres_from_sqft, is_vacant_by_text

NAME = "St Lucie CAMA (multi-CSV)"

_REQUIRED = {"propertyidentification.csv", "propertyownership.csv"}


def detect(folder: Path, files: list[Path]) -> bool:
    names = {p.name.lower() for p in files}
    return _REQUIRED.issubset(names)


def _by_name(files: list[Path], name: str) -> Path | None:
    for p in files:
        if p.name.lower() == name.lower():
            return p
    return None


def parse(folder: Path, files: list[Path]) -> pd.DataFrame:
    ident_file = _by_name(files, "PropertyIdentification.csv")
    owner_file = _by_name(files, "PropertyOwnership.csv")
    assess_file = _by_name(files, "Assessment.csv")
    trans_file = _by_name(files, "Transactions.csv")
    site_file = _by_name(files, "SiteLocation.csv")

    if ident_file is None or owner_file is None:
        raise RuntimeError("St Lucie CAMA is missing PropertyIdentification.csv or PropertyOwnership.csv")

    # --- Identification: parcel, address, land use, lot area ---
    ident = read_delimited(ident_file)
    ident.columns = [c.strip() for c in ident.columns]
    ident["Property ID"] = ident["PropertyID"].map(clean)
    ident["Parcel ID"] = ident.get("ParcelID", "").map(clean)
    ident["Property Address"] = ident.get("SiteAddress", "").map(clean)
    ident["Land Use Code"] = ident.get("LandUse", "").map(clean)
    ident["Land Use"] = ident.get("LandUseDescription", "").map(clean)
    ident["Property City"] = ident.get("DistrictGroupDescription", "").map(clean)
    ident["Property ZIP"] = ""

    # Lot area -> acres. The unit-of-measure column matters: most lots are SqFt,
    # but some rows are 'FrFt' (front feet, a LINEAR measure) or blank. Only SqFt
    # and explicit acres can be converted; anything else is left unknown (NaN) so
    # the acreage filter drops it rather than inventing a bogus lot size.
    area = pd.to_numeric(ident.get("TotalArea", pd.Series(index=ident.index, dtype=str)), errors="coerce")
    uom = ident.get("TotalAreaUOM", pd.Series("", index=ident.index)).astype(str).str.upper().str.strip()
    acres = np.where(uom.str.contains("AC"), area,
                     np.where(uom.str.startswith("SQ"), area / 43560.0, np.nan))
    ident["Acreage"] = acres

    ident = ident[is_vacant_by_text(ident["Land Use"])].copy()
    ident = ident.drop_duplicates("Property ID")

    # --- Ownership: primary owner + mailing address ---
    own = read_delimited(owner_file)
    own.columns = [c.strip() for c in own.columns]
    own["Property ID"] = own["PropertyID"].map(clean)
    if "IsPrimaryFlag" in own.columns:
        own["_pri"] = own["IsPrimaryFlag"].fillna("").astype(str).str.upper().str.strip()
        own = own.sort_values(["Property ID", "_pri"], ascending=[True, False])
    own = own.drop_duplicates("Property ID")
    own["Owner Name"] = combine_name_parts(
        own.get("OwnerFirstName", pd.Series("", index=own.index)),
        own.get("OwnerLastName", pd.Series("", index=own.index)))
    own["Mailing Address"] = combine_name_parts(
        own.get("Street1", pd.Series("", index=own.index)),
        own.get("Street2", pd.Series("", index=own.index)))
    own["Mailing City"] = own.get("City", "").map(clean)
    own["Mailing State"] = own.get("StateProvince", "").map(clean)
    own["Mailing ZIP"] = own.get("PostalCodeFull", "").map(clean).str[:5]
    own = own[["Property ID", "Owner Name", "Mailing Address",
               "Mailing City", "Mailing State", "Mailing ZIP"]]

    result = ident.merge(own, on="Property ID", how="left")

    # --- Site location: real city (Jurisdiction) + property ZIP (LocationPostal) ---
    if site_file is not None:
        site = read_delimited(site_file)
        site.columns = [c.strip() for c in site.columns]
        site["Property ID"] = site["PropertyID"].map(clean)
        site["Site City"] = site.get("Jurisdiction", "").map(clean)
        site["Site ZIP"] = site.get("LocationPostal", "").map(clean).str[:5]
        site = site[["Property ID", "Site City", "Site ZIP"]].drop_duplicates("Property ID")
        result = result.merge(site, on="Property ID", how="left")
        result["Property City"] = result["Site City"].where(
            result["Site City"].fillna("") != "", result["Property City"])
        result["Property ZIP"] = result["Site ZIP"].fillna("")
        result = result.drop(columns=["Site City", "Site ZIP"])

    # --- Assessment: values ---
    if assess_file is not None:
        av = read_delimited(assess_file)
        av.columns = [c.strip() for c in av.columns]
        av["Property ID"] = av["PropertyID"].map(clean)
        av["Market Value"] = av.get("TotalAppraisedValue", "").map(clean)
        av["Land Value"] = av.get("TotalAppraisedLandValue", "").map(clean)
        av = av[["Property ID", "Market Value", "Land Value"]].drop_duplicates("Property ID")
        result = result.merge(av, on="Property ID", how="left")

    # --- Transactions: most recent sale ---
    if trans_file is not None:
        try:
            tx = read_delimited(trans_file)
            tx.columns = [c.strip() for c in tx.columns]
            tx["Property ID"] = tx["PropertyID"].map(clean)
            date_col = next((c for c in tx.columns if "date" in c.lower()), None)
            price_col = next((c for c in tx.columns if "price" in c.lower() or "amount" in c.lower()), None)
            if date_col:
                tx["Last Sale Date"] = tx[date_col].map(clean)
                tx["Last Sale Price"] = tx[price_col].map(clean) if price_col else ""
                tx["_d"] = pd.to_datetime(tx["Last Sale Date"], errors="coerce")
                tx = tx.sort_values(["Property ID", "_d"]).drop_duplicates("Property ID", keep="last")
                result = result.merge(
                    tx[["Property ID", "Last Sale Date", "Last Sale Price"]],
                    on="Property ID", how="left")
        except Exception:  # noqa: BLE001 - sales are optional enrichment
            pass

    result["Land Use Subcode"] = ""
    result["Tax Year"] = ""
    result["Private Owner"] = "Y"
    result["Vacant"] = "Y"
    return result
