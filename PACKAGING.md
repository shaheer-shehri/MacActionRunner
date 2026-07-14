# Packaging — Windows .exe & macOS .app

Both are built with **PyInstaller** from the same spec (`NFCPrintTool.spec`).
PyInstaller **cannot cross-compile**: build the Windows binary on Windows and the
macOS binary on a Mac (or a macOS CI runner — see below).

The binaries are **standalone** — config and templates live in the user-selected
app-data (cloud-synced) folder, not inside the app. Nothing extra to bundle.

## Windows (.exe)

```powershell
cd app
powershell -ExecutionPolicy Bypass -File build_windows.ps1
# -> dist\NFCPrintTool.exe   (double-click to run; no Python needed)
```

## macOS (.app / .dmg) — on a Mac

```bash
cd app
chmod +x build_macos.sh && ./build_macos.sh
# -> dist/NFCPrintTool.app   (+ dist/NFCPrintTool.dmg if hdiutil is present)
```

Gatekeeper note: an unsigned app shows "unidentified developer". Either right-click
→ Open the first time, or sign/notarize with an Apple Developer ID:

```bash
codesign --deep --force --sign "Developer ID Application: <NAME> (<TEAMID>)" dist/NFCPrintTool.app
xcrun notarytool submit dist/NFCPrintTool.dmg --apple-id <id> --team-id <TEAMID> --wait
xcrun stapler staple dist/NFCPrintTool.app
```

## No Mac? Build both in CI (recommended)

`.github/workflows/build.yml` builds the Windows **and** macOS binaries on GitHub's
runners and uploads them as artifacts. Push the repo to GitHub and run the
workflow (Actions tab) — download `NFCPrintTool-windows` and `NFCPrintTool-macos`.
This gives you a real, notarizable `.app` without owning a Mac.

## Notes

- First launch of the onefile Windows exe unpacks to a temp dir (a few seconds).
- If a lazily-imported dependency is missing at runtime, add it to `HIDDEN` in
  `NFCPrintTool.spec` and rebuild.
- To add an app icon: put `icon.ico` (Windows) / `icon.icns` (macOS) beside the
  spec and set `icon=` in `NFCPrintTool.spec`.
