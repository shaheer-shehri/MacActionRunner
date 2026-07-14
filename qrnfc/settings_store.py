"""Per-machine local settings: the chosen app-data folder + the Places API key.

Stored OUTSIDE the shared/synced folder (in the OS user config dir) so secrets
never sync and each machine can point at its own mount path.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Optional

APP_NAME = "NFCReviewPrintTool"


def _local_config_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys_is_mac():
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def sys_is_mac() -> bool:
    import sys
    return sys.platform == "darwin"


@dataclass
class LocalSettings:
    app_data_folder: str = ""
    places_api_key: str = ""
    output_folder: str = ""      # optional override; default = <app_data>/output

    @classmethod
    def path(cls) -> str:
        return os.path.join(_local_config_dir(), "settings.json")

    @classmethod
    def load(cls) -> "LocalSettings":
        try:
            with open(cls.path(), encoding="utf-8") as fh:
                return cls(**json.load(fh))
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return cls()

    def save(self) -> None:
        with open(self.path(), "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)

    def folder_ok(self) -> bool:
        """The app-data folder must exist and look like ours (has templates/)."""
        return bool(self.app_data_folder) and os.path.isdir(
            os.path.join(self.app_data_folder, "templates"))
