# NFC / QR Review Print Tool

Batch-generates print-ready PDFs (with a `Spot_Weiss` UV channel) from a shipping
CSV. See [REQUIREMENTS.md](REQUIREMENTS.md) for the full spec and open questions.

## Structure

```
app/
  qrnfc/                 # core library (UI-independent, testable)
    models.py            # Order / Variant / LinkSource
    labels.py            # label dictionary + 5x5 language-name matrix
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
    order_export.py      # per-order export file (output/export.csv)
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

The link box accepts **either a bare Place ID or a full review link** — an ID
is turned into its `writereview` link automatically, which is the fallback for
when the Places lookup cannot resolve the business from company + address.

With no link supplied it runs the same Places lookup as a batch. The file is
rendered through the identical render path as CSV orders (same spot channel,
overprint and QR ink) and is appended to `output/links.csv`.

## Language vs. country

Two separate facts come off the note's language line and they are **not** the
same thing:

| | from | drives |
|---|---|---|
| **sign language** (`order.language`) | the value the customer *selected* | which template is used |
| **country** (`order.form_language`) | the language of the note's own *labels* | the last part of the filename |

A French customer can order an English sign. The form is French, so its labels
and its dropdown values are French — the selected value arrives as `Anglais`,
not `English`. `labels.LANGUAGE_NAMES` therefore holds every language's name in
every language (the 5×5 matrix); without a name the lookup used to fall back to
the form's language and print the wrong template. **When adding a language, fill
in all five columns.** `tests/` covers all 25 combinations.

## Output filename

```
<prefix>_<lang>_<SKU>_<tracking>_<material>-<country>.pdf
1x_EN_NFC_D02_BLK-A5_00340434888052019115_OAK-FR.pdf
   ^^                                     ^^^ ^^
   sign language ordered                  |   marketplace it was bought on
                                          material (OAK/WNT, omitted for plain MDF)
```
`<prefix>` is `1x`/`2x`/`3x` for an order needing one print file, or `A1`/`A2`…
when it needs several different ones (see `pipeline._assign_sign_groups`). With
no material code the trailing field is just the country.

## Output

- `output/*.pdf` — the print files
- `output/links.csv` — NFC worklist: **one row per print file**, with the number
  of tags to write. The operator works down it chip by chip.
- `output/export.csv` — **one row per order**, keyed on the order number. The
  matching document: which parcel is this, who is it for, which sign is in it.
- `output/labels/*.pdf` — 10x15 cm packing labels for multi-location orders

### export.csv — the per-order data contract

| Field | Source | Note |
|---|---|---|
| Order number | `order_number` | the match key |
| Recipient | a ship-to column, if the export has one | the Amazon orderer / DHL label — **see below** |
| Business name | Places-resolved name, else the note's company | the listing the review link points at |
| Link | the final review link | identical to what the QR encodes |
| Tracking number | `tracking_numbers` | matches the DHL label |
| Filename | the generated print file | shows which sign this is |

**Recipient and Business name are different things on purpose**: "Andreas
Fercher" can order a sign for "Lastenrad Manufaktur", so they are never merged.

**The recipient is not in the shipping export yet.** No column in it holds a
person: `integration_account_name` and `carrier_account_name` are constants and
the rest is item data. `csv_parser.RECIPIENT_COLUMNS` therefore accepts any of
the usual spellings (`recipient`, `ship_to_name`, `buyer_name`, `empfaenger`,
…, matched ignoring case/spaces/underscores) — the day that column is added to
the export it is picked up with **no code change**. Until then the cell is
empty, and each run logs how many rows lack one.

An order needing several different signs still gets **one row**: the
multi-valued cells list their values in sign order separated by `" | "`, so
Business name, Link and Filename line up positionally. Values identical across
the signs collapse to one.

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
