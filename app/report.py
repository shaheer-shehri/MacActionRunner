"""Human-readable run reporting: console output + a saved run report file."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


class RunReport:
    def __init__(self, sink=None):
        # sink: optional callable(str) used by the GUI to show live progress.
        self.lines: list[str] = []
        self.started = datetime.now()
        self.counties_ok: list[str] = []
        self.counties_skipped: list[tuple[str, str]] = []
        self.sink = sink

    def log(self, text: str = "") -> None:
        self.lines.append(text)
        if self.sink is not None:
            try:
                self.sink(text)
            except Exception:  # noqa: BLE001 - never let display break the run
                pass
        else:
            print(text)

    def county_ok(self, county: str) -> None:
        self.counties_ok.append(county)

    def county_skipped(self, county: str, reason: str) -> None:
        self.counties_skipped.append((county, reason))

    def header(self, title: str) -> None:
        self.log("")
        self.log("=" * 68)
        self.log(f"  {title}")
        self.log("=" * 68)

    def summary(self) -> None:
        self.header("RUN SUMMARY")
        self.log(f"Processed OK : {len(self.counties_ok)}  -> {', '.join(self.counties_ok) or '(none)'}")
        if self.counties_skipped:
            self.log(f"Skipped      : {len(self.counties_skipped)}")
            for county, reason in self.counties_skipped:
                self.log(f"   - {county}: {reason.splitlines()[0]}")
        else:
            self.log("Skipped      : 0")
        elapsed = (datetime.now() - self.started).total_seconds()
        self.log(f"Elapsed      : {elapsed:.1f}s")

    def save(self, reports_dir: Path) -> Path:
        stamp = self.started.strftime("%Y%m%d_%H%M%S")
        path = reports_dir / f"Run_Report_{stamp}.txt"
        path.write_text("\n".join(self.lines), encoding="utf-8")
        return path
