# Build the Windows executable. Run from the app/ folder:
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean NFCPrintTool.spec
Write-Host "Built dist/NFCPrintTool.exe"
