"""Create / verify the shared app-data folder structure.

    <root>/config/{labels.json, variants.json, settings.json}
    <root>/templates/<LANG>/...png
    <root>/output/

Defaults are embedded here (not read from a sibling folder) so a PyInstaller
build can scaffold a folder with no external files. Existing files are never
overwritten — the client's edits win.
"""
from __future__ import annotations

import json
import os

from .labels import DEFAULT_LABELS

LANGS = ["DE", "EN", "ES", "FR", "IT"]

# Measured QR windows (fractional) + template MediaBox sizes. See REQUIREMENTS §9.
DEFAULT_VARIANTS = {
    "D02_A5": {"qr_box": {"fx": 0.57375, "fy": 0.42352, "fsize": 0.32814, "quiet_modules": 4},
               "page_w_pt": 522.904, "page_h_pt": 595.274},
    "D02_A6": {"qr_box": {"fx": 0.57375, "fy": 0.42352, "fsize": 0.32814, "quiet_modules": 4},
               "page_w_pt": 368.523, "page_h_pt": 419.528},
    "D01_A5": {"qr_box": {"fx": 0.29448, "fy": 0.28548, "fsize": 0.41160, "quiet_modules": 4},
               "page_w_pt": 422.160, "page_h_pt": 595.200},
    "D01_A6": {"qr_box": {"fx": 0.29448, "fy": 0.28548, "fsize": 0.41160, "quiet_modules": 4},
               "page_w_pt": 297.600, "page_h_pt": 419.520},
}

DEFAULT_SETTINGS = {
    "spot_name": "Spot_Weiss",
    "overprint": True,
    "white_behind_qr": True,
    "white_qr_colours": ["BLK", "HDF"],  # dark stock -> white QR (white ink)
}


def scaffold(root: str) -> list[str]:
    """Create the folder structure + default config files. Returns actions taken."""
    actions: list[str] = []
    cfg_dir = os.path.join(root, "config")
    for d in (cfg_dir, os.path.join(root, "templates"), os.path.join(root, "output")):
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            actions.append(f"created {os.path.relpath(d, root)}/")
    for lang in LANGS:
        d = os.path.join(root, "templates", lang)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
    _write_default(os.path.join(cfg_dir, "labels.json"), DEFAULT_LABELS, actions, root)
    _write_default(os.path.join(cfg_dir, "variants.json"), DEFAULT_VARIANTS, actions, root)
    _write_default(os.path.join(cfg_dir, "settings.json"), DEFAULT_SETTINGS, actions, root)
    return actions


def _write_default(path: str, data, actions: list[str], root: str) -> None:
    if os.path.exists(path):
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    actions.append(f"wrote {os.path.relpath(path, root)}")


def status(root: str) -> dict:
    """Report what's present, for the UI setup screen."""
    tpl_root = os.path.join(root, "templates")
    n_templates = 0
    if os.path.isdir(tpl_root):
        for _, _, files in os.walk(tpl_root):
            n_templates += sum(1 for f in files if f.lower().endswith(".png"))
    return {
        "config": os.path.isdir(os.path.join(root, "config")),
        "templates": os.path.isdir(tpl_root),
        "template_count": n_templates,
        "output": os.path.isdir(os.path.join(root, "output")),
    }
