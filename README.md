# Florida Land Machine — macOS build

This repository builds **Florida Land Machine**, a double-click macOS app that turns
Florida county assessor downloads into vacant-land seller lists, skip-trace upload
files, and builder-matched buyer lists with a 1–5 star rating.

GitHub's macOS runner compiles a **self-contained `.app`** (Python, pandas and
openpyxl embedded), so the end user needs nothing installed.

---

## Download the built app

1. Open the **[Actions](../../actions)** tab.
2. Click the most recent **"Build macOS app (Apple Silicon)"** run.
3. Download the **`FloridaLandMachine-macos-arm64`** artifact and unzip it.

You get a folder **`Florida Land Machine`** containing:

```
Florida Land Machine/
  Florida Land Machine.app     <- double-click this
  Input/                       <- put county folders here
  QUICK START.txt
```

### First launch (Gatekeeper)
Because the app is not code-signed, the first time you open it macOS will warn you.
**Right-click the app → Open → Open.** After that, a normal double-click works.

The app builds for **Apple Silicon (arm64)**. On Intel Macs it runs under Rosetta 2.

---

## How to use it

1. Put each county's downloaded files in a folder inside **`Input/`**
   (e.g. `Input/St Lucie/`, `Input/Indian River/`). Unzip any `.zip` downloads first.
2. Double-click **Florida Land Machine.app** and click **Run**. A live log shows
   progress; large counties take a few minutes.
3. When it finishes it opens the **`Output/`** folder next to the app:
   `Vacant Land`, `Skip Trace Uploads`, `Builder Matches`, `Final Buyers Lists`,
   `Master`, and `_Run Reports`.

### Builders / buy boxes
On first launch the app drops a **`Builder Buy Boxes/Master_Buyer_Buy_Boxes.xlsx`**
starter next to itself (from a sanitized template). Replace the example rows with
your real builders — no code changes needed. **Keep your real workbook local; it is
not stored in this public repo.**

Unrecognized county formats are skipped with a clear note in the run report saying
what to map — the app never guesses.

---

## How the build works

| File | Purpose |
|------|---------|
| `run_app.py` | App entry point (launches the desktop window) |
| `app/` | All logic: format detection, county parsers, vacant filter, buyer matching/scoring, outputs |
| `app/gui.py` | The Tkinter window (Run button + live log) |
| `FloridaLandMachine.spec` | PyInstaller recipe (arm64, windowed, bundles pandas/openpyxl + template) |
| `tools/make_template_workbook.py` | Regenerates the sanitized (no-PII) Buy Boxes template |
| `template/Master_Buyer_Buy_Boxes.xlsx` | Sanitized starter workbook bundled into the app |
| `.github/workflows/build-macos.yml` | Builds, zips, and uploads the app on every push to `main` |

To cut a downloadable **Release**, create a GitHub Release — the workflow attaches
the zip automatically.

Adding a new county format: see `app/parsers/HOW_TO_ADD_A_COUNTY.md`.
