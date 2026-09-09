# NFC / QR Review Print Tool

Batch-generates print-ready PDFs (with a `Spot_Weiss` UV channel) from a shipping
CSV. See [REQUIREMENTS.md](REQUIREMENTS.md) for the full spec and open questions.

## Structure

```
app/
  qrnfc/                 # core library (UI-independent, testable)
    models.py            # Order / Variant / LinkSource
    labels.py            # multilingual label dictionary (DE/FR verified)
    csv_parser.py        # CSV -> Order, extract labelled note fields
    variants.py          # SKU + note -> Variant; resolve template PNG
    review_link.py       # validate / canonicalize Google review links
    places.py            # Google Places lookup (needs API key)
    qr.py                # QR generation + composite onto template
    pdf_export.py        # assemble Spot_Weiss overprint PDF (pikepdf)
    config.py            # load shared config from app-data folder
    settings_store.py    # per-machine local settings (folder + API key)
    template_registry.py # editable variant table (config/templates.csv)
    manual_entry.py      # build one print file without a CSV
    link_export.py       # NFC-writing worklist (output/links.csv)
    pipeline.py          # orchestration (headless; UI plugs in via callbacks)
  ui/
    app.py               # Tkinter front-end skeleton
  config_sample/         # example config.json files -> app-data/config/
  requirements.txt
```

## App-data folder (shared / cloud-synced)

```
<app-data>/
  config/{labels.json, variants.json, settings.json, templates.csv}
  templates/<LANG>/<LANG>_<SHAPE>_<COLOUR>_<SIZE>_*.png
  output/
```
Copy `config_sample/*` into `<app-data>/config/` and the `Print Templates PNG`
language folders into `<app-data>/templates/` to run.

## Run

```
pip install -r requirements.txt
python -m ui.app          # from the app/ directory
```

## Adding a template variant (no code change)

`config/templates.csv` is the variant registry — open it in Excel:

| Code | QR colour | Description |
|------|-----------|-------------|
| BLK  | white     | Black acrylic — white text/QR |
| WHT  | black     | White acrylic — black text/QR |
| TRP  | black     | Transparent acrylic — black text/QR |
| HDF  | white     | Wood / HDF — white text/QR |

To add a variant: **add one row**, then drop its PNGs into
`templates/<LANG>/` named `<LANG>_<SHAPE>_<CODE>_<SIZE>.png`. The code becomes
valid in SKUs immediately (`NFC_D02_<CODE>-A5`).

`QR colour` is the only visual variation across the range — `white` for dark
stock (black acrylic, wood), `black` for light stock. Language, shape and size
are not rows here: they already come from the SKU and the folder layout, so
listing all 80 combinations would be busywork. The table is semicolon-separated
UTF-8-with-BOM so it opens cleanly in a German Excel. Reachable from the UI via
**Edit templates**.

## Creating a print file by hand (no CSV)

For orders that arrive by email, eBay or phone: **New print file…** in the UI.
Pick language / shape / variant / size (the variant list comes from the registry
above), type the company and address, optionally paste a Place ID or review
link, and give it a **reference** — a name or order ID, which becomes the
filename: `<reference>_<lang>_<SKU>[_<material>].pdf`.

With no link supplied it runs the same Places lookup as a batch. The file is
rendered through the identical render path as CSV orders (same spot channel,
overprint and QR ink) and is appended to `output/links.csv`.

## Output

- `output/*.pdf` — the print files
- `output/links.csv` — NFC worklist: order, company, address, link to encode
- `output/labels/*.pdf` — 10x15 cm packing labels for multi-location orders

## Status (validated so far)

- ✅ CSV parsing, label extraction, language detection, variant decode, template
  resolution and link canonicalization — **verified against the sample CSV**
  (all 4 orders, incl. the `share.google` short-link flagged for resolution).
- ✅ `qr.py` + `pdf_export.py` — **executed end-to-end for all 4 layouts.** Output
  has a `/Separation /Spot_Weiss` channel + overprint ExtGState, correct MediaBox,
  and the QR sits in the measured window. RIP proof still pending (client side).
- ✅ QR box coordinates in `config_sample/variants.json` are **measured** from the
  templates (fractional, cross-checked against finished samples).
- ✅ `places.py` + auto address-matching — **live-tested** with a real key: 4-order
  batch resolved fully automatically (3 provided links, 1 Places lookup, 0 manual).
- ✅ Full **UI worker path** — scaffold a folder, load config + 60 templates, run
  the batch, write correctly-named PDFs (BLK/TRP/WHT), all with `Spot_Weiss` +
  overprint and 100% white behind the QR. BLK + TRP RIP proofs in `_rip_proofs/`.
- ⏳ Tkinter window not launchable in CI, but imports/parses clean and its exact
  worker path is validated end-to-end above.
```
