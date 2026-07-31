#!/bin/bash
# ============================================================================
#  Florida Land Machine — launcher (macOS)
#
#  Double-click this file to start the app.
#  The FIRST time, macOS may say it is from an unidentified developer:
#  right-click this file -> Open -> Open. After that a normal double-click works.
#
#  Why a launcher? The app is not code-signed (no Apple Developer account).
#  If macOS opens it the normal way it (a) blocks it as "unidentified" and
#  (b) uses "App Translocation" — it silently runs the app from a random,
#  READ-ONLY system folder, so the app can't see the Input/Output folders next
#  to it. This launcher removes the quarantine flag and starts the app's program
#  DIRECTLY from its real folder, which avoids translocation entirely.
# ============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

APP="$DIR/Florida Land Machine.app"
BIN="$APP/Contents/MacOS/FloridaLandMachine"

if [ ! -x "$BIN" ]; then
    echo "Could not find the app next to this launcher."
    echo "Keep 'Run Florida Land Machine.command' in the SAME folder as"
    echo "'Florida Land Machine.app' (expected: $BIN)."
    read -r -p "Press Return to close." _
    exit 1
fi

# Allow the unsigned app to run (and prevent translocation) by clearing the
# 'downloaded from the internet' quarantine flag.
xattr -dr com.apple.quarantine "$APP" 2>/dev/null
xattr -d  com.apple.quarantine "$0"   2>/dev/null

# Tell the app where its real folder is, then launch its program directly
# (NOT via 'open') so macOS runs it in place instead of a read-only copy.
export FLM_HOME="$DIR"
"$BIN"
