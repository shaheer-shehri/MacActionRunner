# NFC/QR Review Print Tool — Requirements & Structure

_Understanding captured from the client brief, the sample CSV, the template sets
(PNG + PDF), and the finished sample print files._

## 1. Purpose

Batch-generate **print-ready PDFs** (with a UV "Spot White" channel) for NFC/QR
Google-review plaques. Input is a shipping CSV; output is one print file per order
placed onto the correct localized template, with a QR code pointing at the
customer's Google review link.

A **second tool** (not built here) shares the same configuration + template store.

## 2. Data source (CSV)

- Structured columns: `order_number`, `item_sku`, `tracking_numbers`, etc.
- Customer data lives inside the free-text `item_note` field as **labelled lines**.
- Labels are **language-specific**. Confirmed from samples:

| Field    | DE                                            | FR                                                      |
|----------|-----------------------------------------------|---------------------------------------------------------|
| language | `Bitte wählen Sie eine Sprache:`              | `Langue du support:`                                    |
| company  | `Name des Unternehmens:`                      | `Nom de l'entreprise (identique à Google Business):`    |
| address  | `Anschrift des Unternehmens:`                 | `Adresse complète de l'entreprise (...):`               |
| link     | `Direkter Google Bewertungslink (optional):`  | `Lien vers vos avis Google (optionnel):`                |
| material | `Material:`                                   | `Matériau:`                                             |

- Address may span **multiple lines** (postcode/city on the next line).
- Label dictionary must be **data-driven / extendable** (DE, FR, IT, ES today; EN
  templates also exist).

## 3. Product variants → template

- `item_sku` example: `NFC_D02_WHT-A5` → shape `D02`, colour `WHT`, size `A5`.
- Language comes from the parsed note (not the SKU).
- **Template matrix (60):** language {DE,EN,ES,FR,IT} × shape {D01,D02} ×
  colour {BLK,TRP,WHT} × size {A5,A6}.
- Template file path pattern:
  `Print Templates PNG/<LANG>/<LANG>_<SHAPE>_<COLOUR>_<SIZE>_ copy.png`
- **Material** (`MDF Sockel Eiche Dekor` → `OAK`) does **not** change the template;
  it is product metadata used only in the output filename. _(Open Q: are other
  materials coming that DO change artwork?)_

## 4. Review-link logic

1. **Supplied direct review link** — recognized by pattern and used as-is:
   - `https://g.page/r/<id>/review`
   - `https://search.google.com/local/writereview?placeid=<PLACE_ID>`
   `share.google/<id>` links are NOT review links (they expand to a Knowledge-
   Graph search URL with no place_id) → treated as missing.
2. **Otherwise: Places lookup** (IDs-Only) from company + address, then build
   `writereview?placeid=<PLACE_ID>`. Disambiguation is **automatic, no human step**:
   - one candidate → accept;
   - many candidates → pick the one whose **street + house number + city** matches
     the CSV address (`qrnfc.matching`);
   - no address match → step 3.
3. **Manual fallback (the exception only)** — when automatic matching cannot
   resolve a unique Place ID. Usually means no Place ID exists yet (new/unprocessed
   Google listing, or reviews not enabled).
4. **Unresolved-orders list** at the end.

Lookups are cached per (company, address); volume stays inside the free tier.

## 5. QR code

Generated from the final link, placed at a **fixed position/size per layout**
(shape+size). QR is baked into the RGB raster; on TRP/BLK it also needs white ink
behind it (i.e. painted into the Spot White mask). _(Open Q: confirm white-behind-QR.)_

## 6. Print output

- Full-page raster PDF at the template's native resolution.
- Layers: **RGB artwork** (template RGB + QR) + **`Spot_Weiss` separation**
  (from the template alpha), spot set to **overprint**. ✅ Confirmed working in the
  client's RIP (separation view shows spot white + colours correct).
- White fill behind the QR is spread ~5 px (choke/trap) so there is **no hairline
  un-inked ring** at the anti-aliased window edge.
- MediaBox matches the template (D02_A5 = 522.904 × 595.274 pt ≈ 184.4 × 210 mm).
- Built with **pikepdf**, mirroring the structure of the supplied finished PDFs.
- **Output filename** = `<qty>x_<SKU>_<tracking>_<material>.pdf`
  (material = OAK / WNT, omitted for plain MDF). Fields: `item_quantity`,
  `item_sku`, `tracking_numbers`, and the `Material:` note line.
  Example: `1x_NFC_D02_WHT-A5_00340434888052019115_OAK.pdf`.
- **On-screen preview note:** normal PDF viewers show a solid white page because
  the Spot_Weiss separation renders as opaque paper-white on top; this is expected
  and does not affect print (verify via the RIP separation view or Acrobat
  "Overprint Preview"). An optional soft-mask preview mode can be added if desired.

## 7. Configuration & template store (no API keys)

- The app points at a **user-selected folder** (a cloud-synced folder — Google
  Drive/Dropbox/OneDrive desktop — treated as a plain local folder).
- That folder holds `config.xlsx` (labels, variants, settings) + `templates/`.
- The chosen path + the Google API key are stored **locally** (not in the shared
  folder). Re-prompt only if the folder goes missing.
- Cache + validate on load; fall back to last cache if the folder is unreachable.
- The **second tool** reads the same folder → edits propagate everywhere.

## 8. UI

Tkinter desktop app (packaged with PyInstaller). Screens: Settings/folder → Load CSV
→ Process (progress) → Manual-entry dialog (fallback only, rare) → Summary +
unresolved list → PDFs written to output folder. No per-candidate confirmation step
— disambiguation is automatic (§4).

## 9. Resolved by analysis (no client input needed)

- **QR box coordinates + DPI** — MEASURED from the empty QR window in the blank
  templates and cross-checked against the finished sample PDFs (D02 window centre
  = printed QR centre, exact). Stored as fractions in `config/variants.json`:
  D02 `(0.5738, 0.4235, 0.3281)`, D01 `(0.2945, 0.2855, 0.4116)`. D01 = true
  A5/A6 @ 300 dpi; D02 = wider custom format @ ~212 dpi. A5/A6 share a shape's box.
- **Material never changes artwork** — the template set has no material axis
  (60 files = lang×shape×colour×size). Material is filename metadata only; a
  5-language wood vocabulary + slug fallback handles it (`variants.MATERIAL_CODES`).
- **Spot White PDF** — `pdf_export.py` produces a `/Separation /Spot_Weiss`
  channel with overprint (verified in generated output). Preview alternate only;
  RIP keys off the name (still to be proofed in the client's RIP).

## 10. Resolved since first draft

- ✅ **RIP proof** — client confirmed spot white + colour separations correct.
- ✅ **QR coordinates** — measured (section 9).
- ✅ **Filename structure** — corrected to `<qty>x_<SKU>_<tracking>_<material>`
  (matches client's examples exactly).
- ✅ **Places API key** — provided and live-tested (accurate matches; ambiguous
  generic names correctly trigger the confirmation flow). Key must be restricted
  to Places API + budget-capped; stored only in local settings, never in repo.
- ✅ **Hairline gap** at QR window — fixed via white-fill trap.

## 11. Open questions (blockers marked ★)

1. ✅ RESOLVED — **Link handling confirmed.** Two usable types: (a) standard
   review link, recognized by pattern, used as-is; (b) place-id link, built by
   Places lookup (name+address) → `writereview?placeid=<id>`. `share.google`
   (kgmid) links are not usable directly and route through (b) / manual.
2. **White backing layer** — the finished samples had a 2nd near-white RGB layer
   (`Im1`); RIP works without reproducing it, but confirm it isn't required.
3. Full **label strings for IT, ES, EN** (DE/FR verified); confirm note is always
   labelled.
4. **Confirmation threshold** tuning (currently auto-accept ≥0.85 & single hit).
