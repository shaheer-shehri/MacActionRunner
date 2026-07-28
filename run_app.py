"""
Entry point for the double-clickable macOS app.

PyInstaller builds this into 'Florida Land Machine.app'. It simply launches the
desktop window; all logic lives in the app/ package.
"""
import sys

from app.gui import launch

if __name__ == "__main__":
    sys.exit(launch())
