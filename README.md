# Tock Reservation Bot — macOS app

A desktop app for **macOS (Apple Silicon / M1)** that monitors
[exploretock.com](https://www.exploretock.com) for open tables matching your
reservations and **books them automatically** using your own logged-in Tock session.
It drives a real Chromium browser (Playwright), so it survives Tock's JavaScript app
and anti-bot checks that block plain HTTP scrapers.

> **Security:** the app never stores your password or card. You log in once by hand
> into a saved browser profile, and Tock keeps your card on file. The bot uses the
> card on your account — it never types card numbers.

---

## Get the app

- **GitHub Actions build:** every push to `main` builds the `.app` on an Apple-Silicon
  runner. Download it from the run's **Artifacts** (`TockReservationBot-macos-arm64.zip`),
  or from a **Release** if one is published.
- Unzip → you get `TockReservationBot.app`.

### First launch (Gatekeeper)
The app is **unsigned** (no Apple Developer account), so macOS will warn on first open:
- Right-click the app → **Open** → **Open** again, **or**
- Run once in Terminal: `xattr -dr com.apple.quarantine /path/to/TockReservationBot.app`

On first run it downloads Chromium (~150 MB) into `~/.cache/ms-playwright` — needs
internet once. All app data lives in
`~/Library/Application Support/TockReservationBot/` (config, reservations, saved
session, logs, screenshots).

---

## Using the app

1. **Login / Add card** — opens a browser. Sign in to Tock, and add a payment card
   (**Profile → Payment methods**). Tock needs a card on file to finalize a
   reservation — *even free ones*. Then click **Finish login** to save the session.
2. **Edit your reservations** in the table (double-click a cell to edit). Columns:

   | column | required | meaning |
   |---|---|---|
   | `restaurant` | optional | name to match; **blank = any restaurant** |
   | `slug` | optional | exact Tock slug (e.g. `yardbirdhongkong`); most reliable |
   | `city_slug` | ✅ | from a Tock search URL `…/city/<city_slug>/search` |
   | `city` | ✅ | e.g. `Hong Kong` |
   | `latlng` | ✅ | e.g. `22.3193039,114.1693611` |
   | `date` | ✅ | `2026-08-14` |
   | `time_start` / `time_end` | ✅ | acceptable time window |
   | `party_size` | ✅ | guests |
   | `price` | optional | `$`–`$$$$` (Tock price filter); blank = any |
   | `type` | optional | defaults to `DINE_IN_EXPERIENCES` |
   | `completed` | auto | `yes` = booked/skip; set automatically after a booking |
   | `notes` | optional | your notes |

   Get `city_slug`, `city`, `latlng` by searching your city on Tock once and copying
   them out of the result URL.
3. **▶ Start** — begins monitoring. When a slot in your window appears, it books it,
   then marks that row **completed** so it won't book it again.
4. **■ Stop** — stops monitoring.

The **completed** column is the key to "don't book the same thing twice": completed
rows are skipped on start, and a row flips to completed automatically once booked.
Double-click a `completed` cell (or **Toggle completed**) to change it manually.

Everything the bot does is shown in the **Activity log** and saved to
`tock_bot.log`. On a booking you get a `booked_*.png` screenshot; if a checkout can't
be verified you get `unverified_*.png` and a clear warning to check your account.

---

## Command-line use (optional)

The engine also runs headless from a terminal:

```bash
pip install -r requirements.txt
python -m playwright install chromium
python tock_bot.py login     # sign in once (+ add a card on your account)
python tock_bot.py check     # dry run: report availability, book nothing
python tock_bot.py run        # monitor + auto-book
```

Config is `config.json`; reservations are `reservations.csv` (same columns as the
table). Key settings: `mode` (`auto_book`/`notify`), `poll_interval_seconds`,
`continuous` (keep trying until booked), `slot_search_anchors`, and
`checkout.agree_marketing_consent` (off by default).

### CVC re-prompt
Some venues re-ask for the card's CVC at checkout. Provide it for the session via an
env var — never stored in a file:
```bash
export TOCK_CVC=123
```

---

## Build it yourself

CI does this automatically (`.github/workflows/build-macos.yml` on `macos-14`). To
build locally on an Apple-Silicon Mac:

```bash
pip install -r requirements.txt pyinstaller
python -m playwright install chromium      # for local testing
pyinstaller --noconfirm --clean TockReservationBot.spec
open dist/TockReservationBot.app
```

## Notes & etiquette
- Keep `poll_interval_seconds` reasonable (30–60s) — don't hammer Tock.
- This automates **your own** account for **your own** party. Tock's Terms prohibit
  reselling/scalping reservations.
