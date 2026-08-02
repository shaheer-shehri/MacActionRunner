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

import os
import sys
import traceback
from pathlib import Path

from . import detect, vacant_filter, buyers, outputs, extract
from .report import RunReport
from .diagnostics import Diagnostics, emit_workbook
from .utils import finalize_standard, blank_standard_frame


DATA_FOLDER_NAME = "Florida Land Machine"


def find_root() -> Path:
    """
    The working folder that holds Input/, Output/ and Builder Buy Boxes/.

    Resolution order:
      1. FLM_HOME environment variable (testing / portable override).
      2. The folder the user picked with "Change Working Folder…", remembered in
         ~/.florida_land_machine/config.json. This is the reliable way to point
         the app at exactly where your files live.
      3. Compiled app default: ~/Florida Land Machine (fixed, writable, immune to
         macOS App Translocation).
      4. Running from source: the parent of the app/ package.
    """
    env = os.environ.get("FLM_HOME")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p

    from . import settings
    saved = settings.load_working_dir()
    if saved is not None:
        return saved

    if getattr(sys, "frozen", False):
        home = Path.home() / DATA_FOLDER_NAME
        home.mkdir(parents=True, exist_ok=True)
        return home

    return Path(__file__).resolve().parent.parent


def bundled_resource(name: str) -> Path:
    """Locate a file shipped inside the app (e.g. the template workbook)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / name
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent.parent / name


def process_county(folder, report: RunReport, diag: Diagnostics):
    """Extract archives, detect, parse and vacant-filter one county folder.
    Returns (county_name, vacant_df) or (county_name, None) if skipped."""
    county = folder.name
    report.header(f"COUNTY: {county}")

    # 1) Auto-unzip any archives so the operator never has to.
    arch = extract.extract_all(folder, log=report.log)
    for name in arch["unzipped"]:
        report.log(f"Unzipped        : {name}")
    for name, err in arch["failed"]:
        report.log(f"  ! could not unzip {name}: {err}")
    if arch["access_db"]:
        msg = (f"{county}: Microsoft Access file(s) {arch['access_db']} cannot be read on "
               f"Mac. Export to CSV/TXT first.")
        report.log("  ! " + msg)
        diag.fail(msg)

    # 2) Detect format.
    det = detect.detect(county, folder)
    if det.parser is None:
        report.log(det.reason)
        report.county_skipped(county, det.reason)
        if det.format_name == "EMPTY":
            if not arch["access_db"]:
                diag.fail(f"{county}: no readable data files found (missing input files).")
        else:
            diag.fail(f"{county}: unsupported county format — needs a mapping.")
        return county, None

    report.log(f"Format detected : {det.format_name}")
    report.log(f"Input files     : {len(det.files)}")

    # 3) Parse.
    try:
        parsed = det.parser.parse(det.folder, det.files)
    except Exception as exc:  # noqa: BLE001
        reason = f"Parser error: {exc}"
        report.log("  ! " + reason)
        report.county_skipped(county, reason)
        diag.fail(f"{county}: processing stopped by an unexpected error while reading files: {exc}")
        return county, None

    raw_rows = len(parsed)
    normalized = finalize_standard(parsed, county)
    duplicates = raw_rows - len(normalized)
    report.log(f"Parcels parsed  : {len(normalized):,}"
               + (f"  ({duplicates:,} duplicate parcel IDs collapsed)" if duplicates > 0 else ""))
    if duplicates > 0:
        diag.warn(f"{county}: {duplicates:,} duplicate parcel ID(s) found and collapsed to one row each.")

    # 4) Vacant filter.
    vacant, stats = vacant_filter.apply(normalized)
    report.log(f"Vacant filter   : {stats['input']:,} -> vacant {stats.get('after_vacant', 0):,} "
               f"-> acreage {stats.get('after_acreage', 0):,} -> non-gov {stats.get('after_owner', 0):,}")

    if vacant.empty:
        reason = "No vacant residential parcels qualified after filtering."
        report.log("  ! " + reason)
        report.county_skipped(county, reason)
        diag.fail(f"{county}: no vacant parcels matched after filtering.")
        return county, None

    report.county_ok(county)
    diag.ok(f"{county}: {len(vacant):,} vacant residential parcel(s) ({det.format_name}).")
    return county, vacant


def run(sink=None) -> int:
    root = find_root()
    input_root = root / "Input"
    output_root = root / "Output"
    bb_dir = root / "Builder Buy Boxes"
    workbook, wb_candidates = buyers.resolve_workbook(bb_dir)

    report = RunReport(sink=sink)
    diag = Diagnostics("RUN DIAGNOSTICS")
    diag.info(f"Working folder: {root}")
    report.header("FLORIDA LAND MACHINE")
    report.log(f"Working folder: {root}")
    report.log(f"Input folder  : {input_root}")
    report.log(f"Output folder : {output_root}")
    report.log(f"Buy boxes     : {workbook}  ({'found' if workbook.exists() else 'MISSING'})")

    paths = outputs.OutputPaths(output_root)

    if not input_root.exists():
        report.log("\nERROR: Input folder is missing. Create it and drop county folders inside.")
        diag.fail("Input folder is missing. Create an 'Input' folder next to the app.")
        report.log(f"\nDiagnostics saved: {diag.save(paths.reports)}")
        return 1

    # --- Buy Box workbook diagnostics ---
    if len(wb_candidates) > 1:
        diag.info(f"{len(wb_candidates)} workbook(s) in Builder Buy Boxes: "
                  + ", ".join(p.name for p in wb_candidates))
    if not workbook.exists():
        diag.fail("Builder Buy Box workbook not found. Put 'Master_Buyer_Buy_Boxes.xlsx' "
                  f"in this folder: {bb_dir}")
    else:
        emit_workbook(diag, buyers.inspect_workbook(workbook))

    buy_boxes = buyers.load_buy_boxes(workbook)
    contacts = buyers.load_contacts(workbook)
    report.log(f"Active buy boxes loaded: {len(buy_boxes)}")

    county_dirs = sorted(d for d in input_root.iterdir()
                         if d.is_dir() and not d.name.startswith((".", "_")))
    if not county_dirs:
        report.log("\nNothing to do: no county folders found in Input/.")
        report.log("Drop one folder per county (e.g. Input/Brevard/...) and run again.")
        diag.fail("No county folders found in Input. Drop one folder per county.")
        report.summary()
        report.log(f"\nRun report saved: {report.save(paths.reports)}")
        report.log(f"Diagnostics saved: {diag.save(paths.reports)}")
        return 0

    diag.ok(f"{len(county_dirs)} county folder(s) detected.")

    any_ok = False
    for folder in county_dirs:
        county, vacant = process_county(folder, report, diag)
        if vacant is None:
            continue
        any_ok = True

        matrix, final = buyers.match(vacant, buy_boxes, contacts)
        written = outputs.write_county(paths, county, vacant, matrix, final)

        report.log(f"Vacant list     : {written['vacant'].name}  ({len(vacant):,} rows)")
        report.log(f"Skip-trace CSV  : {written['skip'].name}")
        if not matrix.empty:
            builders_hit = matrix['Matched_Builder'].nunique()
            report.log(f"Builder matches : {len(matrix):,} pairs across {builders_hit} builders")
            report.log(f"Final buyer list: {len(final):,} properties (best builder each)")
        elif buy_boxes.empty:
            # No active builders loaded at all — the real reason for zero matches.
            report.log("Builder matches : 0 (no ACTIVE builders are loaded — "
                       "use 'Import Buy Boxes…' to load your workbook)")
            diag.info(f"{county}: 0 builder matches because no active builders are loaded.")
        else:
            report.log("Builder matches : 0 (builders are loaded, but none target this county)")
            diag.info(f"{county}: 0 builder matches — buy boxes are loaded, but none target "
                      f"this county (check the County/City/ZIP/acreage criteria).")

    if any_ok:
        counts = outputs.rebuild_master(paths)
        report.header("MASTER DATASETS")
        report.log(f"Master vacant land : {counts['vacant']:,} rows")
        report.log(f"Master buyer list  : {counts['final']:,} rows")

    report.summary()
    saved = report.save(paths.reports)
    diag_path = diag.save(paths.reports)
    report.log(f"\nRun report saved: {saved}")
    report.log(f"Diagnostics saved: {diag_path}")
    report.log("")
    report.log(diag.render())
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
