# Book Listing Formatter

Turns scraped book spreadsheets into product-listing content using the OpenAI API,
following the three prompt briefs in this folder and the layout in `image (1).png`.

Two front ends, one engine:

| | |
|---|---|
| `app.py` | desktop window — the thing that becomes the .exe / .app |
| `book_formatter.py` | command line, and the engine behind the GUI |

## Setup

```powershell
pip install -r requirements.txt
copy .env.example .env      # then paste your key into .env
```

## Run

```powershell
python app.py                             # desktop window
python book_formatter.py                  # every .xlsx in this folder
python book_formatter.py --limit 3        # smoke test on 3 rows per file
python book_formatter.py --dry-run        # show mapping + payloads, no API calls
python book_formatter.py --workers 8      # faster on large files
```

Each `X.xlsx` produces `X_formatted.xlsx`. The GUI stores your API key and last-used
folder in `~/.book_formatter.json` (chmod 600 on macOS), so the packaged app needs
no `.env` file.

## Output columns

The new file contains **only these eight** — no scraped source columns beyond the
lookup key:

| Col | Column | Content |
|---|---|---|
| A | **Name** | product name copied **verbatim** from the input — the VLOOKUP key |
| B | **Revised Name** | title in English |
| C | **Revised Author** | author in English |
| D | **Book Details** | HTML `<ul>` with bold labels |
| E | **Book Description** | one 90–150 word SEO paragraph |
| F | **Meta Description** | ≤160 chars, starts with "Buy Online" |
| G | **Listing HTML** | Book Details + Book Description, ready to paste as page body |
| H | **Tags** | 5–12 comma-separated Shopify collection tags |

The listing HTML never contains the meta description — that text is taken from
column F and belongs in the page `<head>`, not in the product body.

Section headings render 3px above the body copy (19px vs 16px), set inline so the
sizes survive being pasted into a store template. Change `BODY_FONT_PX` in
`book_formatter.py` to rescale both together.

### Tags

Generated from *Prompt for Tag Decision.docx* — browsing categories for Shopify
collections, not SEO keywords. Beyond the prompt, the code enforces what it can:
duplicates are removed case-insensitively, ISBN-like and publisher-name tags are
dropped, the list is capped at 12, and acronyms (UPSC, NEET, UGC NET) keep their
capitals instead of being title-cased into "Upsc". The language collection tag
(e.g. `Bengali Books`) is added if the model omits it, since the language comes from
the source data. Rows that end up under 5 tags are counted in the run summary rather
than padded — inventing a category is worse than a short list.

## Joining the two files with VLOOKUP

Column A is the shared key. From a row in the **input** file:

```excel
=VLOOKUP($A2, [_Neo0x07_BaatigharBooksScraper_T396_formatted.xlsx]Books!$A:$H, 7, FALSE)
```

| Want | Column index |
|---|---|
| Revised Name | 2 |
| Revised Author | 3 |
| Book Details | 4 |
| Book Description | 5 |
| Meta Description | 6 |
| Listing HTML | 7 |
| Tags | 8 |

Two things make this reliable, and both are deliberate:

* **The key is an untouched copy of the source cell** — trailing spaces included.
  Every one of the 72 ExoticIndia titles ends in a space; writing the cleaned name
  instead would have broken every lookup on that sheet. Point the lookup at the
  input's own `Name` cell (`$A2`) rather than a typed or `TRIM`-ed value.
* **The key is the leftmost column**, because VLOOKUP only ever searches the first
  column of its range.

The run warns if two rows share a name, since VLOOKUP would silently return only the
first of them. Both current files are duplicate-free.

Apart from the key, no scraped column is copied: price, discount, barcode, image and
fees are dropped — the prompts forbid that information from appearing in a listing
anyway. If you need one back for cross-checking, add it per run: `--carry link`.

## How the two different file layouts are handled

Nothing is positional. Headers are matched against alias sets in `COLUMN_ALIASES`,
so `Format` (Baatighar) and `Cover` (ExoticIndia) both resolve to *Binding*, and
`Author`/`Writer` fall back to each other. Values then pass through normalisers:

* `Bengali / বাংলা` → `Bengali`, `English Text` → `English`, `KANNADA` → `Kannada`
* `Weight 410 gm` → `410 gm`
* `1186000000000` (an internal id in the ISBN column) → dropped
* `Description` = `"Baatighar"` (shop name, not a blurb) → dropped
* missing `Country` (ExoticIndia has no such column) → simply omitted

Unrecognised but potentially useful columns are still handed to the model as extra
context, so a third scraper usually works without any code change.

## Building the apps

```powershell
pip install -r requirements-build.txt
python build_app.py
```

| Built on | Produces |
|---|---|
| Windows | `dist/BookListingFormatter/BookListingFormatter.exe` |
| macOS | `dist/Book Listing Formatter.app` |

Both come from `BookListingFormatter.spec`, which is also what CI runs, so local
and CI builds cannot drift apart.

The app is a **folder**, not a single file, deliberately. A `--onefile` build
unpacks itself on every launch: measured here, the window took ~60 seconds to
appear. The folder build starts immediately. Distribute the whole folder.

### Getting the .app without using the Mac

**PyInstaller cannot cross-compile**, so Windows cannot produce a `.app`. Rather
than building on the MacBook Air, push to
[MacActionRunner](https://github.com/shaheer-shehri/MacActionRunner) and let
`.github/workflows/build-bookformatter.yml` do it — download the finished
`BookListingFormatter-macos-x86_64.zip` from the run's Artifacts, or trigger it
manually from the Actions tab (*Run workflow*).

The workflow copies the runner strategy that already works in that repo:

* `runs-on: macos-14` — the fast, always-available Apple Silicon runner. The
  Intel `macos-13` runners are being retired and queue for a long time.
* An **Intel x86_64** Python is installed via Miniforge and run under Rosetta 2,
  so PyInstaller emits an Intel app that runs natively on Intel Macs *and* on
  Apple Silicon through Rosetta — one bundle, every Mac.
* The Miniforge env is cached, `concurrency` cancels superseded runs, and the
  job is `paths`-filtered to `bookformatter/**` so unrelated pushes don't build.

A Windows job runs alongside it, so a clean-environment `.exe` comes out of the
same push.

### macOS notes (target: macOS 14.4.1)

The bundle is unsigned, so Gatekeeper blocks the first launch **and** macOS may
apply App Translocation, silently running the app from a random read-only folder.
Ship `Run Book Listing Formatter.command` next to the `.app` — the CI zip already
does — and double-click that instead; it clears the quarantine flag and launches
the binary directly. Manually:

```bash
xattr -dr com.apple.quarantine "Book Listing Formatter.app"
```

### Windows notes

SmartScreen warns on first run because the `.exe` is unsigned — *More info → Run
anyway*. Signing either binary requires a paid certificate; nothing in the code
depends on it.

### If Tk fails to start

Some Windows Python installs put Tcl in `<prefix>/tcl/tcl8.6` while Tk only searches
`<prefix>/lib/tcl8.6`, giving `TclError: Can't find a usable init.tcl`. `app.py`
detects this and sets `TCL_LIBRARY`/`TK_LIBRARY` itself, so running from source
works either way. For a clean packaging run it is still worth repairing the install:
Python installer → **Modify** → tick *tcl/tk and IDLE*.

## Per-sheet rules

Sheet-specific behaviour lives in `SHEET_PROFILES`, matched on the filename (falling
back to the product URL), so a rule only ever touches the sheet it was written for.

| Sheet | `bilingual_title` | Result |
|---|---|---|
| Baatighar | on | `Swapna-Bishleshon (স্বপ্ন-বিশ্লেষণ)` |
| ExoticIndia | off | `Srividyamanyatirtha` |

The bracket is added only to titles that were actually transliterated — an
already-English title on the Baatighar sheet stays plain. The meta description is
always written from the plain English title, never the bracketed one.

Override per run with `--bilingual-title` / `--no-bilingual-title`, or add a new
sheet by appending one line to `SHEET_PROFILES`.

## Meta description guards

The prompt asks for ≤160 characters and an ISBN only when one exists, but the model
does not always comply, so both rules are also enforced in code:

* `strip_wrong_isbn()` deletes any ISBN that is not this book's own — the model was
  observed copying the example ISBN onto books that have none.
* `trim_meta()` drops whole trailing sentences until the text fits 160 characters.

The run summary reports how many descriptions needed repair.

## Token saving: English is never re-translated

`is_english()` checks the script locally. If a title or author is already Latin
script, it is copied straight through and the corresponding key is removed from the
model's return schema, so the model is never asked to rewrite English into English.
On the ExoticIndia file most rows skip both keys.

Results are also cached in `.cache/book_formatter_cache.json`, keyed by the exact
payload, so re-running after a crash or adding rows only pays for what is new.

## Options

| Flag | Default | Purpose |
|---|---|---|
| `--files` | all `.xlsx` | process specific files |
| `--model` | `gpt-4o-mini` | any chat model |
| `--workers` | `4` | parallel API calls |
| `--limit` | `0` (all) | max rows per file |
| `--carry` | none | source fields added back into the output |
| `--suffix` | `_formatted` | output filename suffix |
| `--infer-country` | off | fill a missing Country from the source domain |
| `--bilingual-title` / `--no-bilingual-title` | per sheet | force the title style on every sheet |
| `--dry-run` | off | preview mapping and payloads, no API calls |

`--infer-country` is off by default because the brief says never to invent missing
information; turn it on only if you accept "baatighar.com ⇒ Bangladesh" as a fact.
