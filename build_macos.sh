#!/usr/bin/env bash
# Build the macOS .app bundle. MUST run on a Mac (PyInstaller can't cross-compile).
#   chmod +x build_macos.sh && ./build_macos.sh
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean NFCPrintTool.spec

echo "Built dist/NFCPrintTool.app"
# Optional: make a distributable .dmg
if command -v hdiutil >/dev/null 2>&1; then
  hdiutil create -volname "NFC Print Tool" -srcfolder "dist/NFCPrintTool.app" \
    -ov -format UDZO "dist/NFCPrintTool.dmg"
  echo "Built dist/NFCPrintTool.dmg"
fi
