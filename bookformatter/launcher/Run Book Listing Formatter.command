#!/bin/bash
# ============================================================================
#  Book Listing Formatter - launcher (macOS)
#
#  Double-click this file to start the app.
#  The FIRST time, macOS may say it is from an unidentified developer:
#  right-click this file -> Open -> Open. After that a normal double-click works.
#
#  Why a launcher? The app is not code-signed (no Apple Developer account).
#  If macOS opens it the normal way it (a) blocks it as "unidentified" and
#  (b) uses "App Translocation" - it silently runs the app from a random,
#  READ-ONLY system folder. This launcher clears the quarantine flag and starts
#  the app's program directly from its real folder, avoiding translocation.
# ============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

APP="$DIR/Book Listing Formatter.app"
BIN="$APP/Contents/MacOS/BookListingFormatter"

if [ ! -x "$BIN" ]; then
    echo "Could not find the app next to this launcher."
    echo "Keep 'Run Book Listing Formatter.command' in the SAME folder as"
    echo "'Book Listing Formatter.app' (expected: $BIN)."
    read -r -p "Press Return to close." _
    exit 1
fi

# Allow the unsigned app to run by clearing the 'downloaded from the internet'
# quarantine flag (also avoids the Gatekeeper "unidentified developer" block).
xattr -dr com.apple.quarantine "$APP" 2>/dev/null
xattr -d  com.apple.quarantine "$0"   2>/dev/null

echo "Starting Book Listing Formatter..."
echo "Choose the folder holding your scraped .xlsx files, paste your OpenAI key,"
echo "then press Run. Each X.xlsx produces X_formatted.xlsx in the same folder."

# Launch the app's program directly (not via 'open').
"$BIN"
