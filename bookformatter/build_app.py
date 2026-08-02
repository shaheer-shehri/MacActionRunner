"""
build_app.py - package the formatter as a desktop app
=====================================================

    pip install -r requirements-build.txt
    python build_app.py

Produces, in dist/:
    Windows  ->  dist/BookListingFormatter/BookListingFormatter.exe
    macOS    ->  dist/Book Listing Formatter.app

Both come from BookListingFormatter.spec, which is also what the GitHub Actions
workflow runs - local and CI builds cannot drift apart.

IMPORTANT: PyInstaller does not cross-compile. A Windows machine can only build
the .exe and a Mac can only build the .app. To get the macOS bundle without a
Mac, push to GitHub and let .github/workflows/build-bookformatter.yml build it.

The app is a FOLDER, not a single file, on purpose: a one-file build unpacks
itself on every launch, which measured ~60 seconds here before the window
appeared. The folder build starts immediately.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
SPEC = HERE / "BookListingFormatter.spec"
DIST = HERE / "dist"


def check_prerequisites() -> None:
    if not SPEC.exists():
        sys.exit(f"Missing {SPEC.name} - run this script from the project folder.")
    if shutil.which("pyinstaller") is None:
        sys.exit("PyInstaller is not installed. Run:  pip install -r requirements-build.txt")


def build() -> None:
    command = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST),
        "--workpath", str(HERE / "build"),
        str(SPEC),
    ]
    print("Running:", " ".join(command), "\n")
    subprocess.run(command, check=True, cwd=HERE)


def packaged_binary() -> Path:
    if platform.system() == "Darwin":
        return DIST / "Book Listing Formatter.app" / "Contents" / "MacOS" / "BookListingFormatter"
    if platform.system() == "Windows":
        return DIST / "BookListingFormatter" / "BookListingFormatter.exe"
    return DIST / "BookListingFormatter" / "BookListingFormatter"


def verify() -> bool:
    """Launch the packaged app with --check so a broken bundle fails the build."""
    target = packaged_binary()
    if not target.exists():
        print(f"\nVERIFY FAILED: {target} was not produced.")
        return False

    print(f"\nVerifying {target.name} --check ...")
    try:
        result = subprocess.run([str(target), "--check"], timeout=300)
    except subprocess.TimeoutExpired:
        print("VERIFY FAILED: the app did not exit within 300s.")
        return False

    if result.returncode == 0:
        print("VERIFY OK: the packaged app starts and its window renders.")
        return True
    print(f"VERIFY FAILED: exit code {result.returncode}.")
    return False


def report() -> None:
    system = platform.system()
    print("\n" + "=" * 66)
    if system == "Darwin":
        bundle = DIST / "Book Listing Formatter.app"
        print(f"Built: {bundle}")
        print("\nThe bundle is unsigned, so Gatekeeper blocks the first launch.")
        print("Ship it next to launcher/Run Book Listing Formatter.command, which")
        print("clears the quarantine flag and avoids App Translocation. Manually:")
        print(f'    xattr -dr com.apple.quarantine "{bundle}"')
    elif system == "Windows":
        print(f"Built: {packaged_binary()}")
        print("\nDistribute the whole BookListingFormatter folder, not just the .exe.")
        print("SmartScreen warns on first run because it is unsigned:")
        print("    More info -> Run anyway")
    else:
        print(f"Built: {packaged_binary()}")
    print("\nThe API key is entered in the app and stored in ~/.book_formatter.json")
    print("=" * 66)


if __name__ == "__main__":
    check_prerequisites()
    build()
    ok = verify()
    report()
    sys.exit(0 if ok else 1)
