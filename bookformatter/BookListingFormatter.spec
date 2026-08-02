# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Book Listing Formatter desktop app.
#
# One spec for both platforms:
#   Windows -> dist/BookListingFormatter/BookListingFormatter.exe
#   macOS   -> dist/Book Listing Formatter.app   (BUNDLE is ignored off macOS)
#
# Built as a FOLDER (COLLECT) rather than one file on purpose. A --onefile build
# unpacks itself into a temp folder on every launch; measured on Windows that was
# a ~60 second wait before the window appeared. The folder build starts instantly.
#
# On macOS this is built as Intel x86_64 (see target_arch) so the same .app runs
# natively on Intel Macs and on Apple Silicon through Rosetta 2.

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['openpyxl.cell._writer']

for package in ('openai', 'openpyxl', 'dotenv'):
    pkg_datas, pkg_bins, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_bins
    hiddenimports += pkg_hidden

# The openai package declares optional numpy/pandas integrations that this app
# never touches. Without these excludes PyInstaller follows them and, on a
# machine that happens to have the scientific stack installed, drags in torch,
# scipy and matplotlib - a 225 MB bundle instead of roughly 40 MB. Excluding
# them also keeps the build honest across different developer machines.
excludes = [
    'torch', 'torchvision', 'torchaudio', 'torchgen',
    'scipy', 'sympy', 'mpmath', 'networkx',
    'pandas', 'numpy', 'matplotlib', 'PIL',
    'sqlalchemy', 'fsspec', 'transformers',
    'IPython', 'notebook', 'jupyter', 'pytest', 'setuptools',
    'flask', 'werkzeug', 'django',
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BookListingFormatter',
    debug=False,
    strip=False,
    upx=False,
    console=False,            # windowed GUI app (no terminal)
    disable_windowed_traceback=False,
    target_arch='x86_64',     # macOS only; ignored on Windows
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='BookListingFormatter',
)

app = BUNDLE(
    coll,
    name='Book Listing Formatter.app',
    icon=None,
    bundle_identifier='com.shaheer.booklistingformatter',
    info_plist={
        'LSMinimumSystemVersion': '11.0',
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
    },
)
