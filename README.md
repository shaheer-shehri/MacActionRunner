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
    pipeline.py          # orchestration (headless; UI plugs in via callbacks)
  ui/
    app.py               # Tkinter front-end skeleton
  config_sample/         # example config.json files -> app-data/config/
  requirements.txt
```

## App-data folder (shared / cloud-synced)

```
<app-data>/
  config/{labels.json, variants.json, settings.json}
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
