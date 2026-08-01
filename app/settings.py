"""
Persistent settings — remembers the working folder the user chose.

Stored in ~/.florida_land_machine/config.json, a fixed, always-writable location
in the user's home (never affected by macOS App Translocation). This lets the
user point the app at whatever folder holds their Input/Output/Builder Buy Boxes
and have that choice stick across launches.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".florida_land_machine"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_working_dir() -> Path | None:
    """Return the saved working folder if it exists on disk, else None."""
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        raw = str(data.get("working_dir", "")).strip()
        if raw:
            p = Path(raw).expanduser()
            if p.is_dir():
                return p
    except Exception:  # noqa: BLE001 - a missing/broken config is not an error
        pass
    return None


def save_working_dir(path: Path) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps({"working_dir": str(path)}, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def clear_working_dir() -> None:
    try:
        CONFIG_FILE.unlink()
    except Exception:  # noqa: BLE001
        pass
