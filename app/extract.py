"""
Automatic archive extraction.

County downloads often arrive as .zip files (sometimes zips inside zips) or with
odd nested folders. Before detection runs, this module unzips every archive it
finds inside a county folder so the operator never has to unzip or reorganize
anything. Extraction is cached: an archive is only re-extracted if it changed.

Microsoft Access (.accdb/.mdb) files cannot be read on macOS and are reported,
not silently ignored.
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

EXTRACT_SUFFIX = "_unzipped"
MAX_NESTED_PASSES = 4


def _signature(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}-{int(st.st_mtime)}"


def _is_junk(member: str) -> bool:
    return "__MACOSX" in member or member.rsplit("/", 1)[-1] in {".DS_Store", ""}


def extract_all(folder: Path, log=None) -> dict:
    """
    Recursively unzip every .zip under `folder`. Returns a dict with:
      unzipped:  list of archive names successfully extracted (this run)
      failed:    list of (name, error)
      access_db: list of .accdb/.mdb files found (cannot be read on Mac)
    """
    result = {"unzipped": [], "failed": [], "access_db": []}

    def note(msg: str) -> None:
        if log is not None:
            try:
                log(msg)
            except Exception:  # noqa: BLE001
                pass

    for _ in range(MAX_NESTED_PASSES):
        zips = [
            p for p in folder.rglob("*.zip")
            if "__MACOSX" not in p.parts and not p.name.startswith(".")
        ]
        did_work = False
        for zip_path in zips:
            target = zip_path.parent / (zip_path.stem + EXTRACT_SUFFIX)
            marker = target / ".extracted"
            try:
                sig = _signature(zip_path)
            except OSError:
                continue
            if marker.exists() and marker.read_text(encoding="utf-8").strip() == sig:
                continue  # already extracted from this exact archive

            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    for member in zf.namelist():
                        if _is_junk(member):
                            continue
                        zf.extract(member, target)
                marker.write_text(sig, encoding="utf-8")
                result["unzipped"].append(zip_path.name)
                note(f"Unzipped: {zip_path.name}")
                did_work = True
            except Exception as exc:  # noqa: BLE001
                result["failed"].append((zip_path.name, str(exc)))
                note(f"Could not unzip {zip_path.name}: {exc}")
        if not did_work:
            break

    # Report Access databases (not readable on macOS).
    for db in folder.rglob("*"):
        if db.is_file() and db.suffix.lower() in {".accdb", ".mdb"} and "__MACOSX" not in db.parts:
            result["access_db"].append(db.name)

    return result
