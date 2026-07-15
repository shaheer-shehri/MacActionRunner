"""Shared configuration loaded from the app-data folder.

Layout inside the app-data (cloud-synced) folder:
    config/labels.(xlsx|json)      -> overrides labels.DEFAULT_LABELS
    config/variants.(xlsx|json)    -> layout QR boxes + page sizes + material map
    config/settings.json           -> spot name, overprint, thresholds
    templates/<LANG>/...png
    output/

For now labels/variants can be JSON (see config_sample/). An xlsx loader can be
dropped in behind the same ``AppConfig`` interface once the client's sheet exists.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .labels import DEFAULT_LABELS
from .qr import QRBox


@dataclass
class LayoutConfig:
    qr_box: QRBox
    page_w_pt: float
    page_h_pt: float


@dataclass
class AppConfig:
    root: str
    labels: dict = field(default_factory=lambda: DEFAULT_LABELS)
    layouts: dict[str, LayoutConfig] = field(default_factory=dict)
    spot_name: str = "Spot_Weiss"
    overprint: bool = True
    white_behind_qr: bool = True
    # colour codes whose QR must be WHITE ink (dark materials): black acrylic, HDF
    white_qr_colours: tuple = ("BLK", "HDF")

    @property
    def templates_root(self) -> str:
        return os.path.join(self.root, "templates")

    @property
    def output_root(self) -> str:
        return os.path.join(self.root, "output")

    def layout_for(self, layout_key: str) -> LayoutConfig | None:
        return self.layouts.get(layout_key)


def load(root: str) -> AppConfig:
    cfg_dir = os.path.join(root, "config")
    labels = _load_json(os.path.join(cfg_dir, "labels.json")) or DEFAULT_LABELS
    settings = _load_json(os.path.join(cfg_dir, "settings.json")) or {}
    raw_layouts = _load_json(os.path.join(cfg_dir, "variants.json")) or {}

    layouts = {}
    for key, v in raw_layouts.items():
        b = v["qr_box"]
        layouts[key] = LayoutConfig(
            qr_box=QRBox(fx=b["fx"], fy=b["fy"], fsize=b["fsize"],
                         quiet_modules=b.get("quiet_modules", 4)),
            page_w_pt=v["page_w_pt"], page_h_pt=v["page_h_pt"],
        )

    return AppConfig(
        root=root, labels=labels, layouts=layouts,
        spot_name=settings.get("spot_name", "Spot_Weiss"),
        overprint=settings.get("overprint", True),
        white_behind_qr=settings.get("white_behind_qr", True),
        white_qr_colours=tuple(settings.get("white_qr_colours", ("BLK", "HDF"))),
    )


def _load_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
