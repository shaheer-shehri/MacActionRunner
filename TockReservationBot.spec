# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the macOS (Apple Silicon) app.
# Chromium is NOT bundled - it downloads on first launch into the user's cache.
# The Playwright package (incl. its bundled node + cli.js) IS collected so the
# app can run that install itself.

from PyInstaller.utils.hooks import collect_all

datas = [('config.json', '.'), ('reservations.csv', '.')]
binaries = []
hiddenimports = []

pw_datas, pw_bins, pw_hidden = collect_all('playwright')
datas += pw_datas
binaries += pw_bins
hiddenimports += pw_hidden

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TockReservationBot',
    debug=False,
    strip=False,
    upx=False,
    console=False,            # windowed GUI app
    disable_windowed_traceback=False,
    target_arch='arm64',      # Apple Silicon (M1)
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='TockReservationBot',
)

app = BUNDLE(
    coll,
    name='TockReservationBot.app',
    icon=None,
    bundle_identifier='com.shaheer.tockreservationbot',
    info_plist={
        'LSMinimumSystemVersion': '11.0',
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
    },
)
