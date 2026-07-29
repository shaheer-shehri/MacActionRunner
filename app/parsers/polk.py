"""
Polk County FTP CAMA export (multiple tab/comma tables joined on PARCEL_ID).

  ftp_parcel.txt  -> DOR use code + description, acreage, values
  ftp_owner.txt   -> owner name + mailing address
  ftp_sales.txt   -> sale history (most recent kept)

Note: the Polk parcel table has no situs (property) city/ZIP, so city-based buy
boxes can only match Polk at the county level.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..utils import clean, read_delimited, combine_name_parts

NAME = "Polk FTP CAMA (multi-file)"


def _find(files: list[Path], stem: str) -> Path | None:
    for p in files:
        if p.name.lower() == stem.lower():
            return p
    return None


def detect(folder: Path, files: list[Path]) -> bool:
    if _find(files, "ftp_parcel.txt") is None:
        return False
    try:
        cols = {c.strip().lower() for c in read_delimited(_find(files, "ftp_parcel.txt"), nrows=3).columns}
        return {"parcel_id", "dorus_code", "tot_acreage"}.issubset(cols)
    except Exception:  # noqa: BLE001
        return False


def parse(folder: Path, files: list[Path]) -> pd.DataFrame:
    parcel_file = _find(files, "ftp_parcel.txt")
    owner_file = _find(files, "ftp_owner.txt")
    sales_file = _find(files, "ftp_sales.txt")
    if parcel_file is None:
        raise RuntimeError("Polk: ftp_parcel.txt not found")

    par = read_delimited(parcel_file)
    par.columns = [c.strip().strip('"') for c in par.columns]
    out = pd.DataFrame(index=par.index)
    out["Property ID"] = par.get("PARCEL_ID", "").map(clean)
    out["Parcel ID"] = par.get("PR_STRAP", par.get("PARCEL_ID", "")).map(clean)
    out["Land Use Code"] = par.get("DORUS_CODE", "").map(clean)
    # DORDESC is only a broad category (RES/COM/AG); DORDESC1 has the real
    # description (e.g. "Vac.Res"). Keep the detailed one as the land use.
    out["Land Use"] = par.get("DORDESC1", par.get("DORDESC", "")).map(clean)
    out["Acreage"] = pd.to_numeric(par.get("TOT_ACREAGE", pd.Series(index=par.index, dtype=str)), errors="coerce")
    out["Market Value"] = par.get("TOTALVAL", "").map(clean)
    out["Land Value"] = par.get("TOT_LND_VAL", "").map(clean)
    out["Private Owner"] = "Y"

    # Vacant residential land: DORDESC1 reads "Vac.Res" (punctuation varies, so
    # match on the letters only). Condos/MH/RV vacant lots are intentionally left
    # out (not buildable single-family land); the central filter also drops COND.
    desc = out["Land Use"].fillna("").astype(str).str.upper().str.replace(r"[^A-Z]", "", regex=True)
    out = out[desc.str.contains("VACRES")].copy()
    out["Vacant"] = "Y"

    # Owner + mailing.
    if owner_file is not None:
        own = read_delimited(owner_file)
        own.columns = [c.strip().strip('"') for c in own.columns]
        own["Property ID"] = own.get("PARCEL_ID", "").map(clean)
        if "LN_NUM" in own.columns:
            own["_ln"] = pd.to_numeric(own["LN_NUM"], errors="coerce").fillna(99)
            own = own.sort_values(["Property ID", "_ln"]).drop_duplicates("Property ID")
        else:
            own = own.drop_duplicates("Property ID")
        own["Owner Name"] = own.get("NAME", "").map(clean)
        own["Mailing Address"] = combine_name_parts(
            own.get("ADDR_1", pd.Series("", index=own.index)),
            own.get("ADDR_2", pd.Series("", index=own.index)),
            own.get("ADDR_3", pd.Series("", index=own.index)))
        own["Mailing City"] = own.get("CITY", "").map(clean)
        own["Mailing State"] = own.get("STATE", "").map(clean)
        own["Mailing ZIP"] = own.get("ZIP", "").map(clean).str[:5]
        own = own[["Property ID", "Owner Name", "Mailing Address",
                   "Mailing City", "Mailing State", "Mailing ZIP"]]
        out = out.merge(own, on="Property ID", how="left")

    # Most recent sale.
    if sales_file is not None:
        try:
            sal = read_delimited(sales_file)
            sal.columns = [c.strip().strip('"') for c in sal.columns]
            sal["Property ID"] = sal.get("PARCEL_ID", "").map(clean)
            sal["Last Sale Date"] = sal.get("SALEDT", "").map(clean)
            sal["Last Sale Price"] = sal.get("PRICE", "").map(clean)
            sal["_d"] = pd.to_datetime(sal["Last Sale Date"], errors="coerce")
            sal = sal.sort_values(["Property ID", "_d"]).drop_duplicates("Property ID", keep="last")
            out = out.merge(sal[["Property ID", "Last Sale Date", "Last Sale Price"]],
                            on="Property ID", how="left")
        except Exception:  # noqa: BLE001
            pass

    return out
