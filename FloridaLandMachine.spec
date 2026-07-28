# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Florida Land Machine macOS app (Apple Silicon / arm64).
#
# Produces a self-contained "Florida Land Machine.app" with Python + pandas +
# openpyxl embedded, so the end user needs nothing installed. The Buy Boxes
# TEMPLATE and Quick Start guide are bundled and copied out next to the app on
# first launch (see app/gui.py).

from PyInstaller.utils.hooks import collect_all

# Files shipped inside the bundle, placed at the bundle root ('.').
datas = [
    ('template/Master_Buyer_Buy_Boxes.xlsx', '.'),
    ('QUICK START.txt', '.'),
]
binaries = []
hiddenimports = []

for package in ('pandas', 'numpy', 'openpyxl'):
    pkg_datas, pkg_bins, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_bins
    hiddenimports += pkg_hidden

a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['pytest'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FloridaLandMachine',
    debug=False,
    strip=False,
    upx=False,
    console=False,            # windowed GUI app (no terminal)
    disable_windowed_traceback=False,
    target_arch='arm64',      # Apple Silicon (M-series)
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='FloridaLandMachine',
)

app = BUNDLE(
    coll,
    name='Florida Land Machine.app',
    icon=None,
    bundle_identifier='com.shaheer.floridalandmachine',
    info_plist={
        'LSMinimumSystemVersion': '11.0',
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
    },
)
