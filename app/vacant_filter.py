"""
Central vacant-land filtering, applied uniformly to every county after parsing.

Parsers may pre-filter for efficiency, but this is the single authoritative gate
so the rules are consistent everywhere:
  * must be vacant residential (by land-use text, unless the parser already
    guaranteed it by flagging Vacant = 'Y'),
  * acreage within the configured range,
  * owner is not a government / institutional entity.
"""
from __future__ import annotations

import re

import pandas as pd

from . import config
from .utils import is_vacant_by_text, is_government_owner


def apply(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    stats = {"input": len(df)}
    if df.empty:
        stats.update(after_vacant=0, after_acreage=0, after_owner=0)
        return df, stats

    work = df.copy()

    # 1) Vacant residential. Trust an explicit Vacant='Y' flag from the parser,
    #    otherwise judge from the land-use description.
    land_use = work.get("Land Use", pd.Series("", index=work.index))
    flagged = work.get("Vacant", pd.Series("", index=work.index)).fillna("").astype(str).str.upper().eq("Y")
    vacant = flagged | is_vacant_by_text(land_use)

    # Remove non-buildable "vacant" uses (condos, co-ops, timeshares) even when
    # they are flagged vacant, so only real single-family lots remain.
    lu_upper = land_use.fillna("").astype(str).str.upper()
    excluded = pd.Series(False, index=work.index)
    for word in config.EXCLUDED_LANDUSE_KEYWORDS:
        excluded |= lu_upper.str.contains(re.escape(word.upper()), regex=True, na=False)

    work = work[vacant & ~excluded].copy()
    stats["after_vacant"] = len(work)

    # 2) Acreage window.
    acres = pd.to_numeric(work["Acreage"], errors="coerce")
    work = work[(acres >= config.MIN_ACRES) & (acres <= config.MAX_ACRES)].copy()
    stats["after_acreage"] = len(work)

    # 3) Drop government / institutional owners.
    gov = is_government_owner(work.get("Owner Name", pd.Series("", index=work.index)))
    work = work[~gov].copy()
    work["Vacant"] = "Y"
    stats["after_owner"] = len(work)

    return work.reset_index(drop=True), stats
