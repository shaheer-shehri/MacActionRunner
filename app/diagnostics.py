"""
Plain-English diagnostics.

Collects the result of each check performed during a run (or a quick pre-flight
from the Diagnostics button) and writes a report a non-technical operator can
read and forward. This is a deterministic rules engine — no AI, no internet.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

OK = "✅"
BAD = "❌"
WARN = "⚠️"
INFO = "•"


class Diagnostics:
    def __init__(self, title: str = "DIAGNOSTICS"):
        self.title = title
        self.started = datetime.now()
        self.items: list[tuple[str, str]] = []

    def ok(self, msg: str) -> None:
        self.items.append((OK, msg))

    def fail(self, msg: str) -> None:
        self.items.append((BAD, msg))

    def warn(self, msg: str) -> None:
        self.items.append((WARN, msg))

    def info(self, msg: str) -> None:
        self.items.append((INFO, msg))

    @property
    def failures(self) -> int:
        return sum(1 for icon, _ in self.items if icon == BAD)

    @property
    def warnings(self) -> int:
        return sum(1 for icon, _ in self.items if icon == WARN)

    def render(self) -> str:
        lines = [
            "=" * 64,
            f"  {self.title}",
            f"  {self.started.strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 64,
            "",
        ]
        if self.failures == 0:
            lines.append(f"{OK} Everything looks good — no problems detected.")
        else:
            lines.append(f"{BAD} {self.failures} problem(s) found"
                         + (f", {self.warnings} warning(s)." if self.warnings else "."))
        lines.append("")
        for icon, msg in self.items:
            lines.append(f"{icon} {msg}")
        lines += ["", "-" * 64,
                  "Send this file to your developer if anything shows " + BAD + "."]
        return "\n".join(lines)

    def save(self, reports_dir: Path) -> Path:
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"Diagnostics_{self.started.strftime('%Y%m%d_%H%M%S')}.txt"
        path.write_text(self.render(), encoding="utf-8")
        return path


def emit_workbook(diag: "Diagnostics", info: dict) -> None:
    """Write the detailed Buy Box findings (columns, sample rows, before/after
    counts, and the exact reason each row was rejected)."""
    if info.get("path"):
        diag.info(f"Reading Buy Boxes from: {info['path']}")
    if info.get("error"):
        diag.fail(f"Builder Buy Box workbook could not be read: {info['error']}")
        return

    if info.get("is_template"):
        diag.fail("This is the built-in EXAMPLE template, NOT your real workbook. "
                  "Replace the file shown above with your own Master_Buyer_Buy_Boxes.xlsx "
                  "(put it in this exact folder), then run again.")

    diag.ok(f"Buy Box file loaded successfully (sheet '{info['sheet']}').")
    diag.info("Detected columns: " + (", ".join(info["columns"]) or "(none)"))
    for n, row in enumerate(info.get("sample_rows", []), start=1):
        diag.info(f"Row {n}: {row}")
    diag.info(f"Builder rows before Active filter: {info['rows_with_data']}")
    diag.info(f"Builder rows remaining after Active filter: {info['active']}")

    if not info.get("has_active_column"):
        diag.info("No 'Active' column present — every builder row is treated as active.")

    if info["active"] == 0:
        diag.fail("No active builders found. Every row was rejected (see reasons below), "
                  "or the workbook is still the template. Set 'Active' to Yes on your rows, "
                  "or replace the template with your real workbook.")
    else:
        diag.ok(f"{info['active']} active builder buy box(es) loaded.")

    for name, reason in info.get("rejected", []):
        diag.warn(f"Rejected {name}: {reason}")

    if info["missing_columns"]:
        diag.warn("Buy Box missing recommended column(s): " + ", ".join(info["missing_columns"]))


def preflight(root: Path) -> Diagnostics:
    """
    A quick check WITHOUT full processing, for the Diagnostics button: is the
    workbook OK, are there active builders, are county folders present and
    recognized? Imports are local to keep this module light.
    """
    from . import detect, extract, buyers

    diag = Diagnostics("PRE-FLIGHT DIAGNOSTICS")
    diag.info(f"Working folder: {root}")
    bb_dir = root / "Builder Buy Boxes"
    workbook, wb_candidates = buyers.resolve_workbook(bb_dir)

    # --- Buy Box workbook ---
    if len(wb_candidates) > 1:
        diag.info(f"{len(wb_candidates)} workbook(s) in Builder Buy Boxes: "
                  + ", ".join(p.name for p in wb_candidates))
    if not workbook.exists():
        diag.fail(f"Builder Buy Box workbook not found. Put your "
                  f"Master_Buyer_Buy_Boxes.xlsx in this folder: {bb_dir}")
    else:
        emit_workbook(diag, buyers.inspect_workbook(workbook))

    # --- Input folders ---
    input_root = root / "Input"
    if not input_root.exists():
        diag.fail("Input folder is missing. Create an 'Input' folder next to the app.")
        return diag
    counties = sorted(d for d in input_root.iterdir()
                      if d.is_dir() and not d.name.startswith((".", "_")))
    if not counties:
        diag.fail("No county folders found in Input. Drop one folder per county "
                  "(e.g. Input/St Lucie/).")
        return diag

    diag.ok(f"{len(counties)} county folder(s) detected: "
            + ", ".join(c.name for c in counties))

    for folder in counties:
        arch = extract.extract_all(folder)
        if arch["access_db"]:
            diag.fail(f"{folder.name}: Microsoft Access file(s) {arch['access_db']} cannot be "
                      f"read on Mac. Export them to CSV/TXT first.")
        det = detect.detect(folder.name, folder)
        if det.parser is None and det.format_name == "EMPTY":
            diag.fail(f"{folder.name}: no readable data files found (missing input files).")
        elif det.parser is None:
            diag.fail(f"{folder.name}: unsupported county format — needs a mapping. {det.reason.splitlines()[0]}")
        else:
            diag.ok(f"{folder.name}: recognized as {det.format_name}.")

    return diag
