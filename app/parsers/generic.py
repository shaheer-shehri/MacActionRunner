"""
Generic best-effort parser for a single headered CSV/XLSX whose columns can be
recognized by name. This is the LAST resort, tried only after the county-specific
parsers. It matches columns by a canonical key (case/space/underscore/punctuation
insensitive), so "Land Use", "Land_Use", "LANDUSE" and "landUse" all match. It
only claims a folder when it can confidently map the essential fields; anything
weaker is left UNRECOGNIZED so the operator maps it explicitly rather than
getting incorrect results.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .. import config
from ..utils import clean, read_delimited

NAME = "Generic headered file"

# Aliases are matched on a canonical key (letters+digits only, lowercased).
COLUMN_ALIASES = {
    "property_id": ["PropertyID", "Account", "AccountNumber", "Folio", "FolioNumber",
                    "ParcelNumber", "ParcelNo", "ParcelID", "PIN", "AltKey", "AlternateKey",
                    "Alternate_Key", "Strap", "MasterId", "PARCEL_ID"],
    "parcel_id": ["ParcelIDFormatted", "ParcelID", "ParcelNumber", "ParcelNo", "APN",
                  "Account", "Folio", "PIN", "Strap", "PARCEL_ID", "Parcel", "StrapNumber"],
    "owner_name": ["OwnerName", "PrimaryOwner", "Owner1", "Owner", "TaxpayerName",
                   "OwnerFullName", "Owners_Name", "Owner Name", "Name", "OwnerName1"],
    "mail_address": ["MailFormatted1", "MailAddressLine1", "MailAddress", "OwnerAddress",
                     "MailingAddress", "Mailing_Address_1", "mailaddr1", "MailAddr1",
                     "Mailing Address", "Street1", "ADDR_1"],
    "mail_city": ["MailCity", "MailingCity", "OwnerCity", "mailcity", "MailAddr City",
                  "Mailing City"],
    "mail_state": ["MailState", "MailingState", "OwnerState", "mailstate", "Mailing State"],
    "mail_zip": ["MailZip5", "MailZip", "MailingZip", "OwnerZip", "Zip_4", "mailzip",
                 "Mailing Zip", "MailPostal"],
    "property_address": ["LocAddressFormatted", "PropertyAddress", "SiteAddress",
                         "SitusAddress", "Address", "situs", "SitusAddr1", "PhysicalAddress",
                         "Physical_Address_1", "PrimaryAddress", "Location"],
    "property_city": ["LocCity", "PropertyCity", "SiteCity", "SitusCity", "City", "situs_city",
                      "PhysicalCity", "Physical_City", "Jurisdiction"],
    "property_zip": ["LocZip", "PropertyZip", "SiteZip", "SitusZip", "Zip", "situs_zip",
                     "PhysicalZip", "Physical_Zip", "LocationPostal", "PostalCode"],
    "acreage": ["Acreage", "Acres", "LandAcres", "TotalAcres", "acres", "GISAcres",
                "SUM_LegalAcres", "SUM_GISAcres", "LegalAcres", "TotalAcreage", "TOT_ACREAGE",
                "DeededAcres"],
    "land_sqft": ["LandSqFt", "Land_Square_Feet", "LandSquareFeet", "LandSF", "LotSqFt",
                  "SquareFeet", "LotSquareFeet"],
    "land_use": ["LandUseCodeDescription", "LandUseDescription", "LandUseDesc",
                 "PropertyUseDescription", "UseDescription", "LandUse", "pc_descr",
                 "DORDESC1", "DORDESC", "UseDesc", "PropertyType", "PrimaryPropertyType"],
    "dor_code": ["DORCode", "DOR_LUC", "DORUS_CODE", "DOR_UC", "UseCode", "LandUseCode",
                 "PropertyUseCode", "DOR"],
    "sold_vacant": ["SoldAsVacantFlag", "VacantFlag", "IsVacant", "VacantImproved",
                    "Vacant_Improved"],
    "market_value": ["MarketValueCur", "MarketValue", "JustValue", "TotalValue",
                     "Total_JV", "just_val", "TotalJust", "TotalJustValue",
                     "TotalAppraisedValue"],
    "land_value": ["LandValueAppraisedCur", "LandValue", "AssessedLandValue",
                   "LandMarketValue", "Land_Val", "land_val", "TotalAppraisedLandValue",
                   "tot_lnd_val", "TotalLandValue"],
    "last_sale_date": ["SaleDate", "LastSaleDate", "LastTransferDate", "last_saledt"],
    "last_sale_price": ["SalePrice", "LastSalePrice", "LastTransferPrice", "last_sale_price"],
}


def _canon(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


# Pre-compute canonical alias -> field lookups.
_ALIAS_CANON = {
    field: {_canon(a) for a in aliases} for field, aliases in COLUMN_ALIASES.items()
}


def _map_columns(columns) -> dict[str, str | None]:
    canon_to_col = {}
    for c in columns:
        canon_to_col.setdefault(_canon(c), c)
    resolved: dict[str, str | None] = {}
    for field, canon_aliases in _ALIAS_CANON.items():
        match = next((canon_to_col[a] for a in canon_aliases if a in canon_to_col), None)
        resolved[field] = match
    return resolved


def _score(cols: dict) -> int:
    """Essential coverage: an identifier, an owner, a size, and a use signal."""
    return (
        bool(cols.get("parcel_id") or cols.get("property_id"))
        + bool(cols.get("owner_name"))
        + bool(cols.get("acreage") or cols.get("land_sqft"))
        + bool(cols.get("land_use") or cols.get("dor_code") or cols.get("sold_vacant"))
    )


def _read_any(path: Path, nrows=None) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str, nrows=nrows)
    return read_delimited(path, nrows=nrows)


def _best_file(files: list[Path]):
    best = None
    for path in files:
        try:
            sample = _read_any(path, nrows=10)
        except Exception:  # noqa: BLE001
            continue
        cols = _map_columns(sample.columns)
        score = _score(cols)
        if best is None or score > best[1]:
            best = (path, score, cols)
    return best


_MIN_SCORE = 3


def detect(folder: Path, files: list[Path]) -> bool:
    best = _best_file(files)
    return best is not None and best[1] >= _MIN_SCORE


def _dor_all_zero(series: pd.Series) -> pd.Series:
    digits = series.fillna("").astype(str).str.replace(r"\D", "", regex=True)
    return (digits != "") & (digits.str.lstrip("0") == "")


def parse(folder: Path, files: list[Path]) -> pd.DataFrame:
    best = _best_file(files)
    if best is None or best[1] < _MIN_SCORE:
        raise RuntimeError("Generic parser could not recognize essential columns.")
    path, _, cols = best
    df = _read_any(path)

    def take(field):
        src = cols.get(field)
        return df[src].map(clean) if src else pd.Series("", index=df.index)

    out = pd.DataFrame(index=df.index)
    out["Property ID"] = take("property_id") if cols.get("property_id") else take("parcel_id")
    out["Parcel ID"] = take("parcel_id")
    out["Owner Name"] = take("owner_name")
    out["Mailing Address"] = take("mail_address")
    out["Mailing City"] = take("mail_city")
    out["Mailing State"] = take("mail_state")
    out["Mailing ZIP"] = take("mail_zip").str[:5]
    out["Property Address"] = take("property_address")
    out["Property City"] = take("property_city")
    out["Property ZIP"] = take("property_zip").str[:5]

    # Acreage: prefer an acres column; else convert square feet.
    if cols.get("acreage"):
        out["Acreage"] = pd.to_numeric(take("acreage"), errors="coerce")
    elif cols.get("land_sqft"):
        out["Acreage"] = pd.to_numeric(take("land_sqft"), errors="coerce") / config.SQFT_PER_ACRE
    else:
        out["Acreage"] = pd.NA

    out["Land Use"] = take("land_use")
    out["Land Use Code"] = take("dor_code")
    out["Market Value"] = take("market_value")
    out["Land Value"] = take("land_value")
    out["Last Sale Date"] = take("last_sale_date")
    out["Last Sale Price"] = take("last_sale_price")
    out["Private Owner"] = "Y"

    # Vacant signal: explicit flag, or a vacant land-use description, or an
    # all-zero DOR use code (00 = vacant residential). The central vacant filter
    # re-checks, but we set the flag here where the description is only a code.
    vacant = pd.Series(False, index=df.index)
    if cols.get("sold_vacant"):
        flag = take("sold_vacant").str.upper()
        vacant |= flag.isin({"Y", "YES", "TRUE", "1", "T", "VACANT"})
    if cols.get("dor_code"):
        vacant |= _dor_all_zero(df[cols["dor_code"]])
    out["Vacant"] = vacant.map(lambda v: "Y" if v else "")
    # Where we only had a DOR code (no text), label it so downstream is readable.
    out.loc[(out["Vacant"] == "Y") & (out["Land Use"].fillna("") == ""), "Land Use"] = "Vacant Residential"
    return out
