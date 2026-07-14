# PyInstaller spec — cross-platform.
#   Windows -> a single NFCPrintTool.exe (windowed)
#   macOS   -> NFCPrintTool.app bundle (windowed)
# Build with:  pyinstaller NFCPrintTool.spec
import sys

HIDDEN = [
    "googlemaps", "qrcode", "qrcode.image.pil",
    "requests", "openpyxl", "PIL", "PIL._tkinter_finder", "numpy", "pikepdf",
]
# Keep the binary lean: these are present in dev but the app never uses them.
EXCLUDES = ["scipy", "matplotlib", "pandas", "pytest", "IPython", "notebook",
            "tkinter.test", "test"]

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # macOS: onedir + .app bundle
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
              name="NFCPrintTool", console=False, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="NFCPrintTool", upx=False)
    app = BUNDLE(
        coll,
        name="NFCPrintTool.app",
        icon=None,
        bundle_identifier="com.codiarts.nfcprinttool",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
else:
    # Windows / Linux: single-file executable
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              name="NFCPrintTool", console=False, upx=False,
              runtime_tmpdir=None, icon=None)
