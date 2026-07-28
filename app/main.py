"""
Florida Land Machine — main pipeline.

For every county folder in Input/:
  1. detect its format (or stop-and-report if unrecognized),
  2. parse -> normalized schema,
  3. filter to vacant residential land,
  4. write the seller list + skip-trace CSV,
  5. match every property with every qualifying builder (scored, 5-star),
  6. write builder matches + final buyer list.
Then rebuild the growing master datasets and save a run report.

Run from the project root:  python -m app.main
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from . import detect, vacant_filter, buyers, outputs
from .report import RunReport
from .utils import finalize_standard, blank_standard_frame


def find_root() -> Path:
    """
    The working folder that holds Input/, Output/ and Builder Buy Boxes/.

    * Running from source: the parent of the app/ package.
    * Running as a compiled macOS .app: the folder that CONTAINS the .app bundle,
      so the user's Input/Output sit right next to the double-clickable app.
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent.parent
        return exe.parent
    return Path(__file__).resolve().parent.parent


def bundled_resource(name: str) -> Path:
    """Locate a file shipped inside the app (e.g. the template workbook)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / name
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent.parent / name


def process_county(det: detect.Detection, report: RunReport):
    """Return (vacant_df, matrix, final) or None if skipped."""
    report.header(f"COUNTY: {det.county}")

    if det.parser is None:
        report.log(det.reason)
        report.county_skipped(det.county, det.reason)
        return None

    report.log(f"Format detected : {det.format_name}")
    report.log(f"Input files     : {len(det.files)}")

    try:
        parsed = det.parser.parse(det.folder, det.files)
    except Exception as exc:  # noqa: BLE001
        reason = f"Parser error: {exc}"
        report.log("  ! " + reason)
        report.county_skipped(det.county, reason)
        return None

    normalized = finalize_standard(parsed, det.county)
    report.log(f"Parcels parsed  : {len(normalized):,}")

    vacant, stats = vacant_filter.apply(normalized)
    report.log(f"Vacant filter   : {stats['input']:,} -> vacant {stats.get('after_vacant', 0):,} "
               f"-> acreage {stats.get('after_acreage', 0):,} -> non-gov {stats.get('after_owner', 0):,}")

    if vacant.empty:
        reason = "No vacant residential parcels qualified after filtering."
        report.log("  ! " + reason)
        report.county_skipped(det.county, reason)
        return None

    report.county_ok(det.county)
    return vacant


def run(sink=None) -> int:
    root = find_root()
    input_root = root / "Input"
    output_root = root / "Output"
    workbook = root / "Builder Buy Boxes" / "Master_Buyer_Buy_Boxes.xlsx"

    report = RunReport(sink=sink)
    report.header("FLORIDA LAND MACHINE")
    report.log(f"Input folder  : {input_root}")
    report.log(f"Output folder : {output_root}")
    report.log(f"Buy boxes     : {workbook}  ({'found' if workbook.exists() else 'MISSING'})")

    if not input_root.exists():
        report.log("\nERROR: Input folder is missing. Create it and drop county folders inside.")
        return 1

    county_dirs = sorted(d for d in input_root.iterdir()
                         if d.is_dir() and not d.name.startswith((".", "_")))
    if not county_dirs:
        report.log("\nNothing to do: no county folders found in Input/.")
        report.log("Drop one folder per county (e.g. Input/Brevard/...) and run again.")
        return 0

    paths = outputs.OutputPaths(output_root)
    buy_boxes = buyers.load_buy_boxes(workbook)
    contacts = buyers.load_contacts(workbook)
    report.log(f"Active buy boxes loaded: {len(buy_boxes)}")

    any_ok = False
    for folder in county_dirs:
        det = detect.detect(folder.name, folder)
        vacant = process_county(det, report)
        if vacant is None:
            continue
        any_ok = True

        matrix, final = buyers.match(vacant, buy_boxes, contacts)
        written = outputs.write_county(paths, det.county, vacant, matrix, final)

        report.log(f"Vacant list     : {written['vacant'].name}  ({len(vacant):,} rows)")
        report.log(f"Skip-trace CSV  : {written['skip'].name}")
        if not matrix.empty:
            builders_hit = matrix['Matched_Builder'].nunique()
            report.log(f"Builder matches : {len(matrix):,} pairs across {builders_hit} builders")
            report.log(f"Final buyer list: {len(final):,} properties (best builder each)")
        else:
            report.log("Builder matches : 0 (no buy box qualified for this county)")

    if any_ok:
        counts = outputs.rebuild_master(paths)
        report.header("MASTER DATASETS")
        report.log(f"Master vacant land : {counts['vacant']:,} rows")
        report.log(f"Master buyer list  : {counts['final']:,} rows")

    report.summary()
    saved = report.save(paths.reports)
    report.log(f"\nRun report saved: {saved}")
    return 0


def main(sink=None) -> int:
    try:
        return run(sink=sink)
    except Exception:  # noqa: BLE001
        msg = traceback.format_exc()
        if sink is not None:
            sink("\nUNEXPECTED ERROR — please send this to your developer:\n")
            sink(msg)
        else:
            print("\nUNEXPECTED ERROR — please send this to your developer:\n")
            print(msg)
        return 1


if __name__ == "__main__":
    sys.exit(main())
