"""
Generic best-effort parser for a single headered CSV/XLSX whose columns can be
recognized by name. This is the LAST resort. It only claims a folder when it can
confidently map the essential fields (parcel/owner + acreage + land-use); a
weakly-recognized file is left UNRECOGNIZED so the operator maps it explicitly
rather than getting incorrect results.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..utils import clean, read_delimited

NAME = "Generic headered file"

COLUMN_ALIASES = {
    "property_id": ["PropertyID", "Account", "AccountNumber", "Folio", "FolioNumber",
                    "ParcelNumber", "ParcelNo", "ParcelID", "PIN", "AltKey", "Alternate_Key"],
    "parcel_id": ["ParcelIDFormatted", "ParcelID", "ParcelNumber", "ParcelNo", "APN",
                  "Account", "Folio", "PIN"],
    "owner_name": ["OwnerName", "PrimaryOwner", "Owner1", "Owner", "TaxpayerName",
                   "OwnerFullName", "Owners_Name"],
    "mail_address": ["MailFormatted1", "MailAddressLine1", "MailAddress", "OwnerAddress",
                     "MailingAddress", "Mailing_Address_1", "mailaddr1"],
    "mail_city": ["MailCity", "MailingCity", "OwnerCity", "mailcity"],
    "mail_state": ["MailState", "MailingState", "OwnerState", "mailstate"],
    "mail_zip": ["MailZip5", "MailZip", "MailingZip", "OwnerZip", "Zip_4", "mailzip"],
    "property_address": ["LocAddressFormatted", "PropertyAddress", "SiteAddress",
                         "SitusAddress", "Address", "situs"],
    "property_city": ["LocCity", "PropertyCity", "SiteCity", "SitusCity", "City", "situs_city"],
    "property_zip": ["LocZip", "PropertyZip", "SiteZip", "SitusZip", "Zip", "situs_zip"],
    "acreage": ["Acreage", "Acres", "LandAcres", "TotalAcres", "acres"],
    "land_use": ["LandUseCodeDescription", "LandUseDescription", "LandUseDesc",
                 "PropertyUseDescription", "UseDescription", "LandUse", "pc_descr"],
    "market_value": ["MarketValueCur", "MarketValue", "JustValue", "TotalValue",
                     "Total_JV", "just_val"],
    "land_value": ["LandValueAppraisedCur", "LandValue", "AssessedLandValue",
                   "LandMarketValue", "Land_Val", "land_val"],
    "last_sale_date": ["SaleDate", "LastSaleDate", "LastTransferDate", "last_saledt"],
    "last_sale_price": ["SalePrice", "LastSalePrice", "LastTransferPrice", "last_sale_price"],
    "sold_vacant": ["SoldAsVacantFlag", "VacantFlag", "IsVacant"],
}

# Minimum recognizable essential fields required before we trust this parser.
_ESSENTIAL = ["parcel_id", "owner_name", "acreage", "land_use"]
_MIN_SCORE = 3


def _map_columns(columns) -> dict[str, str | None]:
    lookup = {str(c).strip().lower(): c for c in columns}
    resolved: dict[str, str | None] = {}
    for field, aliases in COLUMN_ALIASES.items():
        resolved[field] = next((lookup[a.lower()] for a in aliases if a.lower() in lookup), None)
    return resolved


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
        score = sum(bool(cols.get(k)) for k in _ESSENTIAL)
        if best is None or score > best[1]:
            best = (path, score, cols)
    return best


def detect(folder: Path, files: list[Path]) -> bool:
    best = _best_file(files)
    return best is not None and best[1] >= _MIN_SCORE


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
    out["Acreage"] = pd.to_numeric(take("acreage"), errors="coerce")
    out["Land Use"] = take("land_use")
    out["Market Value"] = take("market_value")
    out["Land Value"] = take("land_value")
    out["Last Sale Date"] = take("last_sale_date")
    out["Last Sale Price"] = take("last_sale_price")
    out["Private Owner"] = "Y"
    out["Vacant"] = ""  # let the central vacant filter decide from land use
    return out
