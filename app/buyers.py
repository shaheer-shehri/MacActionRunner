"""
Builder / buyer matching with a 0-100 score and a 1-5 star rating.

Business rules
--------------
* Every qualifying property is matched with EVERY qualifying builder (the full
  matrix), not just the first match.
* A property qualifies for a builder only on the fields county assessor data
  reliably contains: County, City/Area or ZIP, and Acreage. These are HARD
  filters.
* Among qualifying matches, the STAR RATING reflects how well the property fits
  the middle of the buy box (acreage position, location precision, price fit).
* Criteria the assessor data cannot verify (utilities, lot width/depth, road
  exclusions, off-market status) are never used to drop a property; they are
  listed in a "Needs_Verification" column so the operator can check top matches
  by hand.

Two outputs are produced from the matrix:
  * Builder Matches  -> every qualifying (property, builder) pair.
  * Final Buyer List -> the single best-rated builder for each property.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .utils import clean, to_number


# ---------------------------------------------------------------------------
# Loading the workbook
# ---------------------------------------------------------------------------
_ACTIVE_TRUE = {"", "YES", "Y", "TRUE", "1", "ACTIVE"}
_RECOMMENDED_COLUMNS = ["Builder", "County", "City/Area", "ZIP Codes", "Min Acres", "Max Acres"]


def _read_buy_box_sheet(workbook: Path) -> tuple[pd.DataFrame, str]:
    """
    Read the buy-box sheet as strings. Tries the 'Buy Boxes' sheet first, then
    the sheet whose header most looks like buy boxes, then the first sheet.
    Explicitly uses the openpyxl engine (required inside the packaged app).
    Raises on genuine read failure.
    """
    xls = pd.ExcelFile(workbook, engine="openpyxl")
    names = xls.sheet_names
    preferred = next((s for s in names if s.strip().lower() in {"buy boxes", "buyboxes", "buy box"}), None)
    order = ([preferred] if preferred else []) + [s for s in names if s != preferred]
    best: tuple[pd.DataFrame, str] | None = None
    for sheet in order:
        df = pd.read_excel(xls, sheet_name=sheet, dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
        if "Builder" in df.columns or "Buyer" in df.columns:
            return df, sheet
        if best is None:
            best = (df, sheet)
    if best is None:
        raise RuntimeError("workbook has no readable sheets")
    return best


def inspect_workbook(workbook: Path) -> dict:
    """Return facts about the workbook for diagnostics (never raises)."""
    info = {"error": None, "sheet": None, "rows": 0, "active": 0, "missing_columns": []}
    try:
        df, sheet = _read_buy_box_sheet(workbook)
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
        return info
    info["sheet"] = sheet
    info["rows"] = len(df)
    if "Active" in df.columns:
        active = df["Active"].fillna("").astype(str).str.strip().str.upper()
        info["active"] = int(active.isin(_ACTIVE_TRUE).sum())
    else:
        info["active"] = len(df)  # no Active column -> treat all as active
    info["missing_columns"] = [c for c in _RECOMMENDED_COLUMNS if c not in df.columns]
    return info


def load_buy_boxes(workbook: Path) -> pd.DataFrame:
    if not workbook.exists():
        return pd.DataFrame()
    try:
        df, _ = _read_buy_box_sheet(workbook)
    except Exception:
        return pd.DataFrame()
    if "Active" in df.columns:
        active = df["Active"].fillna("").astype(str).str.strip().str.upper()
        df = df[active.isin(_ACTIVE_TRUE)]
    return df.reset_index(drop=True)


def load_contacts(workbook: Path) -> dict[str, dict]:
    try:
        df = pd.read_excel(workbook, sheet_name="Contacts", dtype=str)
    except Exception:
        return {}
    df.columns = [str(c).strip() for c in df.columns]
    contacts: dict[str, dict] = {}
    for _, row in df.iterrows():
        builder = clean(row.get("Builder", "")).upper()
        if builder and builder not in contacts:
            contacts[builder] = {
                "Buyer_Contact": clean(row.get("Contact", "")),
                "Buyer_Email": clean(row.get("Email", "")),
                "Buyer_Phone": clean(row.get("Phone", "")),
            }
    return contacts


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------
def _canon(value: str) -> str:
    """Uppercase, drop periods, and treat 'Saint'/'St' as the same token."""
    v = clean(value).upper().replace(".", "")
    v = re.sub(r"\bSAINT\b", "ST", v)
    return re.sub(r"\s+", " ", v).strip()


def _norm_county(value: str) -> str:
    v = _canon(value)
    v = re.sub(r"\bCOUNTY\b", "", v)
    return re.sub(r"\s+", " ", v).strip()


def _norm_city(value: str) -> str:
    return _canon(value)


def _num(value) -> float | None:
    n = to_number(pd.Series([value])).iloc[0]
    return None if pd.isna(n) else float(n)


def _col(columns, *names):
    lower = {str(c).strip().lower(): c for c in columns}
    return next((lower[n.lower()] for n in names if n.lower() in lower), None)


# Buy-box fields that assessor data cannot verify automatically.
_ENRICH_FIELDS = [
    ("Water Requirement", "water"),
    ("Sewer/Septic Requirement", "sewer/septic"),
    ("Min Width Ft", "lot width"),
    ("Min Depth Ft", "lot depth"),
    ("Excluded Roads/Areas", "road exclusions"),
    ("Off Market Only", "off-market status"),
]


def _needs_verification(buyer: pd.Series) -> str:
    notes = []
    for field, label in _ENRICH_FIELDS:
        val = clean(buyer.get(field, "")).upper()
        if val and val not in {"NO", "UNKNOWN", "N/A", "0"}:
            notes.append(label)
    return "; ".join(notes)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _acreage_score(acres: pd.Series, lo: float | None, hi: float | None) -> pd.Series:
    """0-25: highest at the centre of the buy box range, lower toward the edges."""
    if lo is None and hi is None:
        return pd.Series(15.0, index=acres.index)  # neutral, no preference stated
    lo_v = lo if lo is not None else (hi * 0.5 if hi else 0.0)
    hi_v = hi if hi is not None else (lo * 2.0 if lo else lo_v + 1.0)
    if hi_v <= lo_v:
        hi_v = lo_v + max(lo_v * 0.5, 0.05)
    center = (lo_v + hi_v) / 2.0
    half = (hi_v - lo_v) / 2.0 or 1.0
    dist = (acres - center).abs() / half           # 0 at center, 1 at edge
    return (25.0 * (1.0 - dist.clip(0, 1))).clip(0, 25)


def _price_score(value: pd.Series, pmin: float | None, pmax: float | None) -> pd.Series:
    """0-20: how the property's just value sits against the builder's price band."""
    if pmin is None and pmax is None:
        return pd.Series(12.0, index=value.index)   # neutral
    v = value
    hi = pmax if pmax is not None else (pmin if pmin is not None else None)
    lo = pmin if pmin is not None else 0.0
    out = pd.Series(12.0, index=v.index)
    known = v.notna() & (v > 0)
    if hi is not None:
        within = known & (v >= lo) & (v <= hi)
        below = known & (v < lo)
        near = known & (v > hi) & (v <= hi * 1.25)
        far = known & (v > hi * 1.25)
        out = out.mask(within, 20.0).mask(below, 16.0).mask(near, 9.0).mask(far, 4.0)
    return out.clip(0, 20)


def _stars_from_score(score: pd.Series) -> pd.Series:
    return score.div(20).round().clip(1, 5).astype(int)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def match(vacant: pd.DataFrame, buy_boxes: pd.DataFrame, contacts: dict[str, dict]
          ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (builder_matches_matrix, final_best_per_property)."""
    empty = pd.DataFrame()
    if vacant.empty or buy_boxes.empty:
        return empty, empty

    cols = buy_boxes.columns
    f_builder = _col(cols, "Builder", "Buyer", "Company")
    f_bbid = _col(cols, "BuyBoxID", "BuyBox ID")
    f_market = _col(cols, "Market", "Target Market")
    f_county = _col(cols, "County")
    f_city = _col(cols, "City/Area", "City", "Area")
    f_zips = _col(cols, "ZIP Codes", "Zip Codes", "ZIP", "Target ZIPs")
    f_min = _col(cols, "Min Acres", "Minimum Acres")
    f_max = _col(cols, "Max Acres", "Maximum Acres")
    f_pmin = _col(cols, "Price Min", "Min Price")
    f_pmax = _col(cols, "Price Max", "Max Price", "Price")
    f_notes = _col(cols, "Special Criteria", "Notes", "Automation Notes")
    if not f_builder:
        return empty, empty

    prop_county = vacant["County"].map(_norm_county)
    prop_city = vacant["Property City"].map(_norm_city)
    prop_zip = vacant["Property ZIP"].fillna("").astype(str).str[:5]
    prop_acres = pd.to_numeric(vacant["Acreage"], errors="coerce")
    prop_value = to_number(vacant["Market Value"])

    frames = []
    for _, buyer in buy_boxes.iterrows():
        mask = pd.Series(True, index=vacant.index)
        reasons_parts = []

        # County (hard filter when specified)
        bc = _norm_county(buyer.get(f_county, "")) if f_county else ""
        if bc:
            mask &= prop_county.eq(bc)
            reasons_parts.append(("county", f"County {bc.title()}"))

        # Location precision: ZIP first, else City/Area
        zips = re.findall(r"\b\d{5}\b", clean(buyer.get(f_zips, ""))) if f_zips else []
        loc_kind = "county"
        if zips:
            mask &= prop_zip.isin(zips)
            loc_kind = "zip"
        elif f_city and clean(buyer.get(f_city, "")):
            terms = [_norm_city(t) for t in re.split(r"[,;/|]", clean(buyer.get(f_city, ""))) if t.strip()]
            if terms:
                city_mask = pd.Series(False, index=vacant.index)
                for t in terms:
                    # match when either name contains the other (handles
                    # "Port St Lucie" vs "PORT SAINT LUCIE" style variants)
                    city_mask |= prop_city.apply(lambda c, t=t: bool(c) and (t in c or c in t))
                mask &= city_mask
                loc_kind = "city"

        # Acreage (hard filter when bounds given)
        lo = _num(buyer.get(f_min, "")) if f_min else None
        hi = _num(buyer.get(f_max, "")) if f_max else None
        if lo is not None:
            mask &= prop_acres >= lo
        if hi is not None:
            mask &= prop_acres <= hi

        matched = vacant[mask].copy()
        if matched.empty:
            continue

        idx = matched.index
        pmin = _num(buyer.get(f_pmin, "")) if f_pmin else None
        pmax = _num(buyer.get(f_pmax, "")) if f_pmax else None

        loc_score = {"zip": 25.0, "city": 18.0, "county": 10.0}[loc_kind]
        acre_s = _acreage_score(prop_acres.loc[idx], lo, hi)
        price_s = _price_score(prop_value.loc[idx], pmin, pmax)
        score = (30.0 + loc_score + acre_s + price_s).clip(0, 100).round(1)
        stars = _stars_from_score(score)

        builder = clean(buyer.get(f_builder, ""))
        contact = contacts.get(builder.upper(), {})

        matched.insert(0, "Star_Rating", stars.values)
        matched.insert(1, "Stars", stars.map(lambda s: "★" * s + "☆" * (5 - s)).values)
        matched.insert(2, "Match_Score", score.values)
        matched.insert(3, "Matched_Builder", builder)
        matched.insert(4, "BuyBoxID", clean(buyer.get(f_bbid, "")) if f_bbid else "")
        matched.insert(5, "Builder_Market", clean(buyer.get(f_market, "")) if f_market else "")
        matched["Buyer_Price_Min"] = "" if pmin is None else int(pmin)
        matched["Buyer_Price_Max"] = "" if pmax is None else int(pmax)
        matched["Match_On"] = {"zip": "County+ZIP+Acreage", "city": "County+City+Acreage",
                               "county": "County+Acreage"}[loc_kind]
        matched["Needs_Verification"] = _needs_verification(buyer)
        matched["Buyer_Notes"] = clean(buyer.get(f_notes, "")) if f_notes else ""
        matched["Buyer_Contact"] = contact.get("Buyer_Contact", "")
        matched["Buyer_Email"] = contact.get("Buyer_Email", "")
        matched["Buyer_Phone"] = contact.get("Buyer_Phone", "")
        frames.append(matched)

    if not frames:
        return empty, empty

    matrix = pd.concat(frames, ignore_index=True)
    matrix = matrix.sort_values(
        ["Matched_Builder", "Star_Rating", "Match_Score"],
        ascending=[True, False, False]).reset_index(drop=True)

    # Final list: best-rated builder per property.
    final = (matrix.sort_values(["Match_Score", "Star_Rating"], ascending=False)
                   .drop_duplicates(subset="Property ID", keep="first")
                   .sort_values(["Star_Rating", "Match_Score"], ascending=False)
                   .reset_index(drop=True))
    return matrix, final
