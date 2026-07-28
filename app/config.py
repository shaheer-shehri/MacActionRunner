"""
Central configuration for the Florida Land Machine.

Everything a non-programmer might reasonably want to adjust lives here in plain
language. You do NOT need to edit this file to add counties or builders — that is
done through the folders and the Buy Boxes spreadsheet. This file only holds the
filtering rules.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Vacant-land filtering rules
# ---------------------------------------------------------------------------

# Only keep parcels this many acres or smaller (infill residential lots).
MAX_ACRES = 5.0

# A parcel must be at least this many acres to count (filters out slivers/zero).
MIN_ACRES = 0.01

# Words that, when found in a land-use description, mark a parcel as vacant
# residential land. Matching is case-insensitive and partial.
VACANT_KEYWORDS = [
    "VACANT", "UNIMPROVED", "RESIDENTIAL LAND", "SINGLE FAMILY LOT",
    "SINGLE-FAMILY LOT", "V RES", "SF ZONED", "SF-AGRICULTURAL ZONED",
    "SF-MF ZONED", "ALLOCATED LAND-VACANT", "VAC RESIDENTIAL", "VAC RES",
    "VACANT RES", "RES VACANT",
]

# Land-use descriptions that look vacant but are NOT buildable single-family
# land (condominium units, mobile-home co-op lots, timeshares). These are
# dropped even if they match a vacant keyword, so builders only see real lots.
EXCLUDED_LANDUSE_KEYWORDS = [
    "COND",        # Vac Res-Cond (vacant residential condominium)
    "TIMESHARE", "TIME SHARE", "CO-OP", "COOP",
]

# Florida DOR land-use codes for vacant residential land (used by NAL-style
# feeds like Lake County that give a numeric code instead of a description).
# DOR code 00xx = Vacant Residential.
VACANT_DOR_CODES = {"0", "00", "000", "0000", "10", "0010"}

# Owners containing any of these phrases are dropped (government / institutional
# owners are not sellable leads).
EXCLUDED_OWNER_WORDS = [
    "COUNTY OF", "CITY OF", "STATE OF", "UNITED STATES", " USA", "U.S.",
    "SCHOOL BOARD", "WATER MANAGEMENT", "DEPARTMENT OF", "HOUSING AUTHORITY",
    "PORT AUTHORITY", "TIITF", "MUNICIPAL", "DISTRICT ", "BOARD OF",
    "TRUSTEES OF THE INTERNAL", "FLORIDA DEPT", "REDEVELOPMENT AGENCY",
]

# Square feet per acre (used to convert lot area to acreage).
SQFT_PER_ACRE = 43560.0

# ---------------------------------------------------------------------------
# The standard output schema. Every parser normalizes to exactly these columns,
# in this order, so all counties look identical downstream.
# ---------------------------------------------------------------------------
STANDARD_COLUMNS = [
    "County", "Property ID", "Parcel ID", "Owner Name", "Mailing Address",
    "Mailing City", "Mailing State", "Mailing ZIP", "Property Address",
    "Property City", "Property ZIP", "Acreage", "Land Use", "Land Use Code",
    "Land Use Subcode", "Market Value", "Land Value", "Last Sale Date",
    "Last Sale Price", "Tax Year", "Private Owner", "Vacant",
]

# The columns used to uniquely identify a parcel (for de-duplication).
KEY_COLUMN = "Property ID"
