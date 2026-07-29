#!/bin/bash
# ============================================================================
#  Florida Land Machine — launcher (macOS)
#
#  Double-click this file to start the app.
#  The FIRST time, macOS may say it is from an unidentified developer:
#  right-click this file -> Open -> Open. After that a normal double-click works.
#
#  What it does: the app is not code-signed (no Apple Developer account), so
#  macOS "quarantines" it after download and blocks it. This launcher removes
#  that quarantine flag from the app and then opens it — no Terminal knowledge
#  needed.
# ============================================================================

cd "$(dirname "$0")" || exit 1
APP="Florida Land Machine.app"

if [ ! -d "$APP" ]; then
    echo "Could not find \"$APP\" next to this launcher."
    echo "Keep 'Run Florida Land Machine.command' in the SAME folder as the app."
    read -r -p "Press Return to close." _
    exit 1
fi

# Allow the unsigned app to run: strip the 'downloaded from the internet' flag.
xattr -dr com.apple.quarantine "$APP" 2>/dev/null
xattr -d  com.apple.quarantine "$0"   2>/dev/null

# Launch the app (its own window shows the progress and results).
open "$APP"
