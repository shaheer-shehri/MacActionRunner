"""
Writes all output files and maintains the growing master datasets.

Every run fully rebuilds each county's outputs from the newest input, so parcels
that no longer qualify disappear and newly qualifying parcels appear automatically.
The master files are rebuilt from the per-county vacant lists each run and a
timestamped snapshot is archived so history is never lost.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from .utils import safe_name

# Columns for the skip-trace / XLeads upload (owner + mailing + property basics).
XLEADS_COLUMNS = [
    "Property ID", "Parcel ID", "Owner Name", "Mailing Address", "Mailing City",
    "Mailing State", "Mailing ZIP", "Property Address", "Property City",
    "Property ZIP", "Acreage", "Land Use", "Market Value", "Land Value",
    "Last Sale Date", "Last Sale Price",
]


class OutputPaths:
    def __init__(self, output_root: Path):
        self.root = output_root
        self.vacant = output_root / "Vacant Land"
        self.skip = output_root / "Skip Trace Uploads"
        self.matches = output_root / "Builder Matches"
        self.final = output_root / "Final Buyers Lists"
        self.master = output_root / "Master"
        self.reports = output_root / "_Run Reports"
        for folder in (self.vacant, self.skip, self.matches, self.final,
                       self.master, self.reports):
            folder.mkdir(parents=True, exist_ok=True)


def write_county(paths: OutputPaths, county: str, vacant: pd.DataFrame,
                 matrix: pd.DataFrame, final: pd.DataFrame) -> dict[str, Path]:
    tag = safe_name(county)
    written: dict[str, Path] = {}

    vacant_file = paths.vacant / f"{tag}_Vacant_Land.csv"
    vacant.to_csv(vacant_file, index=False, encoding="utf-8-sig")
    written["vacant"] = vacant_file

    skip_file = paths.skip / f"{tag}_XLeads_Upload.csv"
    xleads = pd.DataFrame({c: vacant[c] if c in vacant.columns else "" for c in XLEADS_COLUMNS})
    xleads.to_csv(skip_file, index=False, encoding="utf-8-sig")
    written["skip"] = skip_file

    if matrix is not None and not matrix.empty:
        m_file = paths.matches / f"{tag}_Builder_Matches.csv"
        matrix.to_csv(m_file, index=False, encoding="utf-8-sig")
        written["matches"] = m_file
    if final is not None and not final.empty:
        f_file = paths.final / f"{tag}_Final_Buyer_List.csv"
        final.to_csv(f_file, index=False, encoding="utf-8-sig")
        written["final"] = f_file

    return written


def rebuild_master(paths: OutputPaths) -> dict[str, int]:
    """Combine all per-county vacant lists and final buyer lists into masters,
    and archive a timestamped snapshot."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    counts = {"vacant": 0, "final": 0}

    def _combine(folder: Path, suffix: str) -> pd.DataFrame:
        parts = []
        for csv in sorted(folder.glob(f"*{suffix}")):
            try:
                parts.append(pd.read_csv(csv, dtype=str))
            except Exception:  # noqa: BLE001
                continue
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    all_vacant = _combine(paths.vacant, "_Vacant_Land.csv")
    if not all_vacant.empty:
        all_vacant.to_csv(paths.master / "Master_Vacant_Land.csv", index=False, encoding="utf-8-sig")
        archive = paths.master / "Archive"
        archive.mkdir(exist_ok=True)
        all_vacant.to_csv(archive / f"Master_Vacant_Land_{stamp}.csv", index=False, encoding="utf-8-sig")
        counts["vacant"] = len(all_vacant)

    all_final = _combine(paths.final, "_Final_Buyer_List.csv")
    if not all_final.empty:
        all_final.to_csv(paths.master / "Master_Final_Buyer_List.csv", index=False, encoding="utf-8-sig")
        counts["final"] = len(all_final)

    return counts
