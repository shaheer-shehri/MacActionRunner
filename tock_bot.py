# -*- coding: utf-8 -*-
"""
Tock reservation bot.

Monitors https://www.exploretock.com for open tables matching a list of
targets (restaurant, date, time window, party size) defined in a CSV, and
books them automatically using your own logged-in Tock session.

Commands
--------
    python tock_bot.py login    Open a browser so you can log into Tock once.
                                 The session is saved and reused (no password
                                 is ever stored by this script).
    python tock_bot.py check     One pass over every target. Reports what slots
                                 are available but NEVER books. Use this to
                                 verify your CSV and the page selectors.
    python tock_bot.py run       Poll continuously and book (or alert) when a
                                 matching slot appears, per config "mode".

Configuration lives in config.json. Targets live in reservations.csv.
"""

import argparse
import csv
import json
import logging
import os
import random
import re
import sys
import time
import urllib.request
from urllib.parse import quote
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://www.exploretock.com"

# A time token like "7:00 PM", "19:00", "5:15pm".
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\b")

# Only a stream handler at import time - a bundled .app directory is read-only,
# so file logging is attached later via add_file_log(writable_dir).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("tock")


def add_file_log(data_dir):
    """Attach a rotating-free file handler in a writable directory. Safe to call
    more than once (won't duplicate)."""
    try:
        os.makedirs(data_dir, exist_ok=True)
        path = os.path.join(data_dir, "tock_bot.log")
        for h in logging.getLogger().handlers:
            if isinstance(h, logging.FileHandler) and \
                    os.path.abspath(getattr(h, "baseFilename", "")) == os.path.abspath(path):
                return path
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                          "%Y-%m-%d %H:%M:%S"))
        logging.getLogger().addHandler(fh)
        return path
    except Exception as exc:
        log.warning("Could not attach file log in %s: %s", data_dir, exc)
        return None


# --------------------------------------------------------------------------- #
# Config + targets
# --------------------------------------------------------------------------- #
def load_config(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_targets(path):
    """Read reservations.csv into a list of target dicts, validating each row.

    Tock searches by CITY, not by restaurant, so every row needs the city
    coordinates. Grab them once from the site: search your city on
    exploretock.com and copy the `latlng`, `city`, and city slug straight out
    of the resulting URL (…/city/<city_slug>/search?city=<city>&latlng=<latlng>…).
    The restaurant is then matched inside the results by `slug` or `restaurant`.
    """
    targets = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):  # row 1 = header
            # restaurant/slug are OPTIONAL. Leave both blank to book the first
            # available slot from ANY restaurant in this city search.
            restaurant = (row.get("restaurant") or "").strip()
            slug = (row.get("slug") or "").strip().strip("/")

            city_slug = (row.get("city_slug") or "").strip().strip("/")
            city = (row.get("city") or "").strip()
            latlng = (row.get("latlng") or "").strip()
            if not city_slug or not latlng:
                log.warning("Row %d skipped: needs 'city_slug' and 'latlng' "
                            "(copy them from a Tock city-search URL).", i)
                continue

            try:
                date = normalize_date(row["date"])
                start = to_minutes(row["time_start"])
                end = to_minutes(row["time_end"])
                size = int(str(row["party_size"]).strip())
            except (KeyError, ValueError) as exc:
                log.warning("Row %d skipped: bad date/time/size (%s).", i, exc)
                continue

            if start is None or end is None:
                log.warning("Row %d skipped: unreadable time window.", i)
                continue

            price_raw = (row.get("price") or "").strip()
            price = normalize_price(price_raw)
            if price is None:
                log.warning("Row %d: unrecognized price %r - ignoring price filter.",
                            i, price_raw)
                price = ""

            completed = str(row.get("completed") or "").strip().lower() in (
                "1", "yes", "y", "true", "done", "x")

            targets.append({
                "restaurant": restaurant,
                "slug": slug,
                "city_slug": city_slug,
                "city": city or city_slug.replace("-", " ").title(),
                "latlng": latlng,
                "date": date,
                "time_start": start,          # minutes since midnight
                "time_end": end,
                "party_size": size,
                "type": (row.get("type") or "DINE_IN_EXPERIENCES").strip(),
                "price": price,               # "" = no filter, else $..$$$$
                "notes": (row.get("notes") or "").strip(),
                "completed": completed,       # already booked -> skip
                "done": completed,            # completed rows start "done"
                "attempts": 0,
                "label": restaurant or slug or f"ANY in {city or city_slug}",
            })
    return targets


# Column order used when writing reservations.csv back to disk.
CSV_FIELDS = ["restaurant", "slug", "city_slug", "city", "latlng", "date",
              "time_start", "time_end", "party_size", "price", "type",
              "completed", "notes"]


def write_targets(path, targets):
    """Persist targets back to CSV (used to mark rows completed). Preserves the
    documented column order and quotes fields containing commas (e.g. latlng)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for t in targets:
            w.writerow({
                "restaurant": t.get("restaurant", ""),
                "slug": t.get("slug", ""),
                "city_slug": t.get("city_slug", ""),
                "city": t.get("city", ""),
                "latlng": t.get("latlng", ""),
                "date": t.get("date", ""),
                "time_start": fmt_minutes(t["time_start"]) if isinstance(t.get("time_start"), int) else t.get("time_start", ""),
                "time_end": fmt_minutes(t["time_end"]) if isinstance(t.get("time_end"), int) else t.get("time_end", ""),
                "party_size": t.get("party_size", ""),
                "price": t.get("price", ""),
                "type": t.get("type", "DINE_IN_EXPERIENCES"),
                "completed": "yes" if t.get("completed") else "",
                "notes": t.get("notes", ""),
            })
    os.replace(tmp, path)


def normalize_date(raw):
    raw = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{raw}'")


def to_minutes(raw):
    """'19:00', '7:00 PM', '5pm' -> minutes since midnight, or None."""
    m = TIME_RE.search(str(raw))
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def fmt_minutes(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"


def normalize_price(raw):
    """Accept '$'/'$$'/'$$$'/'$$$$' or 1/2/3/4 -> the '$' string Tock's filter
    uses. Blank or 'all' -> '' (no filter). Returns None for unrecognized input
    so the caller can warn."""
    s = (raw or "").strip()
    if not s or s.lower() == "all":
        return ""
    if s in ("$", "$$", "$$$", "$$$$"):
        return s
    if s in ("1", "2", "3", "4"):
        return "$" * int(s)
    return None


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
def notify(cfg, title, message, data_dir=HERE):
    log.info("HIT: %s | %s", title, message)
    try:
        with open(os.path.join(data_dir, "hits.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {title} | {message}\n")
    except Exception:
        pass

    if cfg.get("beep"):
        try:
            import winsound
            for _ in range(3):
                winsound.Beep(880, 220)
                time.sleep(0.08)
        except Exception:
            print("\a", end="", flush=True)

    webhook = (cfg.get("webhook_url") or "").strip()
    if webhook:
        try:
            data = json.dumps({"content": f"**{title}**\n{message}"}).encode("utf-8")
            req = urllib.request.Request(
                webhook, data=data, headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as exc:
            log.warning("Webhook failed: %s", exc)


# --------------------------------------------------------------------------- #
# Bot
# --------------------------------------------------------------------------- #
class TockBot:
    def __init__(self, cfg, data_dir=HERE):
        self.cfg = cfg
        self.timeout = int(cfg.get("page_timeout_ms", 30000))
        # Writable base dir for the saved session, screenshots, logs, hits.
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    def search_url(self, target, anchor_min=None):
        """Tock city-search URL, e.g.
        /city/hong-kong/search?city=Hong%20Kong&date=2026-07-22
            &latlng=22.31%2C114.16&size=2&time=17%3A00&type=DINE_IN_EXPERIENCES
        `time` anchors the search; results surface the slots nearest it. We then
        filter the offered slots to the row's window."""
        anchor = target["time_start"] if anchor_min is None else anchor_min
        path = f"{BASE_URL}/city/{target['city_slug']}/search"
        q = (f"city={quote(target['city'])}"
             f"&date={target['date']}"
             f"&latlng={quote(target['latlng'])}"
             f"&size={target['party_size']}"
             f"&time={quote(fmt_minutes(anchor))}"
             f"&type={quote(target['type'])}")
        # Optional price filter as a URL param: $=1 .. $$$$=4 (priceRange=N).
        if target.get("price"):
            q += f"&priceRange={len(target['price'])}"
        return f"{path}?{q}"

    def open_context(self, p):
        session_dir = os.path.join(self.data_dir, self.cfg.get("session_dir", "tock_session"))
        os.makedirs(session_dir, exist_ok=True)
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=session_dir,
            headless=bool(self.cfg.get("headless", False)),
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx.set_default_timeout(self.timeout)
        return ctx

    # -- login ------------------------------------------------------------- #
    def login(self):
        with sync_playwright() as p:
            ctx = self.open_context(p)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
            print("\n" + "=" * 66)
            print(" A browser window is open. Log into your Tock account there.")
            print(" Complete any 2FA / CAPTCHA. Leave yourself logged in.")
            print(" When your account name shows in the top-right, come back here")
            print(" and press ENTER to save the session.")
            print("=" * 66 + "\n")
            input("Press ENTER once you are logged in... ")
            log.info("Session saved to '%s'.", self.cfg.get("session_dir"))
            ctx.close()

    # -- reading slots ----------------------------------------------------- #
    # For a given time-slot button, climb to the restaurant result card and
    # read the card's link href (contains the slug) and its name heading.
    CARD_JS = r"""
    el => {
      let n = el, item = null;
      for (let i = 0; i < 12 && n; i++) {
        n = n.parentElement; if (!n) break;
        const link = n.querySelector('a[href^="/"]');
        const head = n.querySelector('h1,h2,h3');
        if (link && head) { item = n; break; }
      }
      if (!item) return null;
      const link = item.querySelector('a[href^="/"]');
      const head = item.querySelector('h1,h2,h3');
      return {
        href: (link.getAttribute('href') || '').split('?')[0].replace(/^\/+/, ''),
        name: (head.innerText || '').trim().split('\n')[0]
      };
    }"""

    def _matches_target(self, info, target):
        # No restaurant/slug specified -> accept ANY restaurant in the search.
        if not target["slug"] and not target["restaurant"]:
            return True
        href = (info.get("href") or "").lower()
        name = (info.get("name") or "").lower()
        if target["slug"]:
            return href == target["slug"].lower()
        r = target["restaurant"].lower()
        return r in name or name in r

    def _scroll_results(self, page, rounds=6):
        """Tock lazy-loads restaurant cards as you scroll the results list.
        Nudge the last known slot button into view a few times so a target
        further down the list gets rendered. Stops once the count settles."""
        last = -1
        for _ in range(rounds):
            btns = page.locator('[data-testid="select-time"]')
            count = btns.count()
            if count == last:
                break
            last = count
            try:
                btns.last.scroll_into_view_if_needed(timeout=4000)
            except Exception:
                break
            page.wait_for_timeout(700)

    def _anchor_times(self, target):
        """Tock's city cards surface the slots NEAREST the `time` param, so we
        query the search at several anchor times across the window to reveal
        later slots too (the restaurant page itself needs UI-driving to list
        them, which is fragile)."""
        start, end = target["time_start"], target["time_end"]
        n = max(1, int(self.cfg.get("slot_search_anchors", 2)))
        if n <= 1 or (end - start) < 45:
            return [start]
        if n == 2:
            return [start, end]
        step = (end - start) / (n - 1)
        return sorted({int(start + i * step) for i in range(n)})

    def _scan_page(self, page, target):
        """Scan the currently-loaded search page for in-window slots at the
        target restaurant. Returns {minutes, text, restaurant} (NO element
        handle - handles go stale on navigation; booking re-locates the slot)."""
        out = []
        for btn in page.locator('[data-testid="select-time"]').all():
            try:
                if not btn.is_visible():
                    continue
                info = btn.evaluate(self.CARD_JS)
                if not info or not self._matches_target(info, target):
                    continue
                text = (btn.inner_text() or "").strip()
            except Exception:
                continue
            slot_min = to_minutes(text)
            if slot_min is None:
                continue
            if target["time_start"] <= slot_min <= target["time_end"]:
                out.append({"minutes": slot_min, "text": text,
                            "restaurant": info.get("name")})
        return out

    def _load_search(self, page, target, anchor_min):
        """Load the city search for one anchor time. The price filter is carried
        by the URL (priceRange param), so no modal interaction is needed."""
        url = self.search_url(target, anchor_min)
        log.info("[%s] Loading search @ anchor %s", target["label"], fmt_minutes(anchor_min))
        log.info("[%s]   URL: %s", target["label"], url)
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=self.timeout)
        except PWTimeout:
            log.info("[%s]   (networkidle timed out; continuing)", target["label"])
        page.wait_for_timeout(2000)
        self._scroll_results(page)
        total = page.locator('[data-testid="select-time"]').count()
        no_results = "No results" in (page.inner_text("body") or "")
        log.info("[%s]   Page ready: %d slot button(s) on page%s",
                 target["label"], total, " [No results]" if no_results else "")

    def find_slots(self, page, target):
        """Return in-window slots at the target restaurant, de-duplicated by
        time and earliest-first, by scanning the search at several time anchors."""
        matches = []
        for anchor in self._anchor_times(target):
            self._load_search(page, target, anchor)
            matches.extend(self._scan_page(page, target))

        seen, unique = set(), []
        for s in sorted(matches, key=lambda x: x["minutes"]):
            if s["minutes"] in seen:
                continue
            seen.add(s["minutes"])
            unique.append(s)
        return unique

    def _find_button(self, page, target, minutes):
        """Locate the live select-time button for a specific restaurant+time on
        the currently-loaded page (used right before clicking, to avoid stale
        handles)."""
        for btn in page.locator('[data-testid="select-time"]').all():
            try:
                if not btn.is_visible():
                    continue
                info = btn.evaluate(self.CARD_JS)
                if not info or not self._matches_target(info, target):
                    continue
                if to_minutes((btn.inner_text() or "").strip()) == minutes:
                    return btn
            except Exception:
                continue
        return None

    # -- booking ----------------------------------------------------------- #
    def click_first_present(self, page, texts, timeout=8000):
        """Click the first button/link whose (case-insensitive) text matches
        any candidate. Returns the matched text, or None."""
        deadline = time.time() + timeout / 1000
        while time.time() < deadline:
            for want in texts:
                loc = page.get_by_role("button", name=re.compile(re.escape(want), re.I))
                if loc.count() == 0:
                    loc = page.get_by_role("link", name=re.compile(re.escape(want), re.I))
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    return want
            page.wait_for_timeout(500)
        return None

    def fill_cvc_if_prompted(self, page):
        """Some venues re-ask for the card's CVC at checkout even with a card on
        file. If so, fill it from the TOCK_CVC environment variable ONLY.
        The CVC is never read from, or written to, any file on disk."""
        if not self.cfg.get("fill_cvc_if_prompted", True):
            return
        cvc = os.environ.get("TOCK_CVC", "").strip()
        if not cvc:
            return
        # Match a CVC/CVV/security-code field by common name/label/placeholder.
        candidates = [
            "input[name*='cvc' i]", "input[name*='cvv' i]",
            "input[autocomplete='cc-csc']",
            "input[placeholder*='CVC' i]", "input[placeholder*='CVV' i]",
            "input[aria-label*='security code' i]",
        ]
        for sel in candidates:
            loc = page.locator(sel)
            try:
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.fill(cvc)
                    log.info("Filled CVC field (%s) from TOCK_CVC env var.", sel)
                    return
            except Exception:
                continue

    # Read the label text sitting next to a checkbox (MUI wraps it in a <label>).
    CHECKBOX_LABEL_JS = r"""
    el => {
      const lab = el.closest('label');
      if (lab && lab.innerText.trim()) return lab.innerText.trim();
      let n = el;
      for (let i = 0; i < 5 && n; i++) {
        n = n.parentElement; if (!n) break;
        const t = (n.innerText || '').trim();
        if (t.length > 8) return t;
      }
      return '';
    }"""

    def tick_checkboxes(self, page):
        """On the confirm-purchase page, tick the REQUIRED acknowledgment
        checkbox(es) so 'Complete reservation' becomes enabled. The optional
        marketing-consent box is left unchecked unless explicitly enabled in
        config (checkout.agree_marketing_consent)."""
        ck = self.cfg.get("checkout", {})
        want_policy = ck.get("agree_cancellation_policy", True)
        want_marketing = ck.get("agree_marketing_consent", False)

        boxes = page.locator('input[type="checkbox"]')
        n = boxes.count()
        log.info("   Checkout: %d checkbox(es) found (agree_policy=%s, agree_marketing=%s)",
                 n, want_policy, want_marketing)
        for i in range(n):
            cb = boxes.nth(i)
            try:
                label = (cb.evaluate(self.CHECKBOX_LABEL_JS) or "").lower()
            except Exception:
                label = ""
            try:
                testid = (cb.get_attribute("data-testid") or "").lower()
            except Exception:
                testid = ""
            # Marketing/email opt-in is optional. Identify it by its testid
            # (e.g. checkout-opt-in-email) or its label wording.
            is_marketing = (
                any(k in testid for k in ("opt-in", "optin", "email", "marketing"))
                or any(w in label for w in
                       ("marketing", "promotion", "offer", "communication"))
            )
            should = want_marketing if is_marketing else want_policy
            kind = "marketing/optional" if is_marketing else "required"
            if not should:
                log.info("   Checkbox #%d [%s] SKIP (testid=%s): %s",
                         i + 1, kind, testid or "-", label[:55] or "(unlabeled)")
                continue
            try:
                if cb.is_checked():
                    log.info("   Checkbox #%d [%s] already checked: %s", i + 1, kind,
                             label[:60] or "(unlabeled)")
                    continue
            except Exception:
                pass
            self._tick(cb)
            log.info("   Checkbox #%d [%s] TICKED: %s", i + 1, kind, label[:60] or "(unlabeled)")

    def _tick(self, cb):
        """MUI hides the real <input>; try force-check, else click its label."""
        try:
            cb.check(force=True, timeout=4000)
            return
        except Exception:
            pass
        try:
            cb.evaluate("el => { const l = el.closest('label') || el.parentElement;"
                        " if (l) l.click(); }")
        except Exception as exc:
            log.warning("Could not tick a checkbox: %s", exc)

    # Non-committal ways to dismiss an interstitial (never "Agree and Continue").
    DISMISS_LABELS = ("Skip", "No thanks", "No, thanks", "Not now",
                      "Maybe later", "Dismiss")

    def dismiss_popups(self, page, rounds=3):
        """Close interstitial modals (e.g. 'Enable text alerts from Tock') that
        pop up on the checkout page and can cover the confirm button.

        Only ever acts INSIDE an open dialog, so it can never touch the checkout
        page's own abandon (X) control, and it never clicks an opt-in/continue
        button. Returns True if it closed at least one."""
        closed_any = False
        for _ in range(rounds):
            dialog = page.locator('[role="dialog"]:visible, [role="alertdialog"]:visible')
            try:
                if dialog.count() == 0:
                    break  # no modal open -> nothing to do
            except Exception:
                break
            scope = dialog.first

            done = False
            # 1) A safe dismiss button inside the dialog.
            for lab in self.DISMISS_LABELS:
                try:
                    btn = scope.get_by_role("button", name=re.compile(
                        rf"^\s*{re.escape(lab)}\s*$", re.I))
                    if btn.count() == 0:
                        btn = scope.get_by_text(lab, exact=True)
                    if btn.count() > 0 and btn.first.is_visible():
                        btn.first.click(timeout=2000)
                        log.info("   Dismissed popup via '%s'.", lab)
                        page.wait_for_timeout(600)
                        closed_any = done = True
                        break
                except Exception:
                    pass
            if done:
                continue

            # 2) The dialog's own close (X) control - still scoped to the dialog.
            for sel in ('button[aria-label*="close" i]',
                        '[data-testid*="close" i]', '[aria-label="Close"]'):
                try:
                    x = scope.locator(sel)
                    if x.count() > 0 and x.first.is_visible():
                        x.first.click(timeout=2000)
                        log.info("   Closed popup via dialog %s.", sel)
                        page.wait_for_timeout(600)
                        closed_any = done = True
                        break
                except Exception:
                    pass
            if not done:
                break  # dialog present but nothing safe to click; leave it
        return closed_any

    def _confirm_button(self, page, texts):
        """Return (locator, description) for the Complete-reservation button.
        Prefers Tock's stable data-testid; falls back to button text."""
        primary = page.locator('[data-testid="purchase-button"]')
        if primary.count() > 0:
            return primary.first, "data-testid=purchase-button"
        for want in texts:
            cand = page.get_by_role("button", name=re.compile(re.escape(want), re.I))
            if cand.count() > 0:
                return cand.first, f"text '{want}'"
        return None, None

    def wait_and_click_confirm(self, page, texts, timeout_ms=20000):
        """Wait for the Complete-reservation button to become ENABLED (some
        venues grey it out until a required box is ticked; others enable it
        immediately), then click it. Returns a description of what was clicked,
        or None."""
        deadline = time.time() + timeout_ms / 1000
        last_log = 0.0
        while time.time() < deadline:
            b, desc = self._confirm_button(page, texts)
            if b is not None:
                try:
                    vis, en = b.is_visible(), b.is_enabled()
                    if time.time() - last_log > 2:
                        log.info("   Confirm button (%s): visible=%s enabled=%s",
                                 desc, vis, en)
                        last_log = time.time()
                    if vis and en:
                        log.info("   Confirm button (%s) ENABLED - clicking now.", desc)
                        try:
                            b.click(timeout=4000)
                            return desc
                        except Exception as exc:
                            # Likely a popup intercepted the click - clear it and retry.
                            log.info("   Click intercepted (%s); dismissing popup and "
                                     "retrying.", type(exc).__name__)
                            self.dismiss_popups(page)
                except Exception:
                    pass
            elif time.time() - last_log > 2:
                log.info("   No confirm button yet (want data-testid=purchase-button "
                         "or text: %s)", ", ".join(texts))
                last_log = time.time()
            page.wait_for_timeout(400)
        log.warning("   Confirm button never became clickable within %ds.",
                    int(timeout_ms / 1000))
        return None

    def book_from_button(self, page, btn, target, slot):
        """Click the slot's LIVE button (already located on the current page —
        no re-navigation, so it can't go stale), which HOLDS the table and opens
        the confirm-purchase page; then tick the required acknowledgment, fill
        CVC if asked, and click the (now enabled) confirm button."""
        log.info("[%s] STEP 1/4: clicking slot '%s' (this holds the table)...",
                 target["label"], slot["text"])
        btn.click()  # holds the table and opens the confirm-purchase page
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)
        log.info("[%s] STEP 2/4: now on checkout page: %s", target["label"], page.url)
        self.dismiss_popups(page)  # e.g. "Enable text alerts from Tock"

        # Some venues insert an intermediate step before confirm-purchase.
        step = self.click_first_present(page, self.cfg.get("checkout_button_texts", []))
        if step:
            log.info("[%s]   intermediate checkout step: clicked '%s'.", target["label"], step)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1500)
            log.info("[%s]   now at: %s", target["label"], page.url)
            self.dismiss_popups(page)

        # Confirm-purchase page: required checkbox -> enables the button.
        log.info("[%s] STEP 3/4: ticking required acknowledgment(s)...", target["label"])
        self.tick_checkboxes(page)
        self.fill_cvc_if_prompted(page)
        self.dismiss_popups(page)  # in case a popup appeared just before confirm

        if self._payment_required_hint(page):
            log.warning("[%s] Checkout is asking for CARD DETAILS - it looks like NO "
                        "payment method is saved on your Tock account. Tock needs a card "
                        "on file to finalize even free reservations. The bot does NOT enter "
                        "card numbers by design. Fix: add a card once at "
                        "exploretock.com (Profile > Payment methods), then re-run.",
                        target["label"])

        log.info("[%s] STEP 4/4: submitting and verifying the reservation...", target["label"])
        texts = self.cfg.get("confirm_button_texts", [])
        safe = target["slug"] or (target["restaurant"] or "target").replace(" ", "_")
        result = self._submit_and_verify(page, texts, target)

        if result is True:
            page.screenshot(path=os.path.join(self.data_dir, f"booked_{safe}.png"))
            log.info("[%s] ===== BOOKING CONFIRMED ===== (screenshot booked_%s.png)",
                     target["label"], safe)
            return True

        if result == "unverified":
            page.screenshot(path=os.path.join(self.data_dir, f"unverified_{safe}.png"))
            log.warning("[%s] Clicked Complete reservation but COULD NOT VERIFY it "
                        "finalized. CHECK YOUR TOCK ACCOUNT NOW. Browser left on the page; "
                        "screenshot unverified_%s.png. Not retrying (to avoid a possible "
                        "double booking).", target["label"], safe)
            return True  # stop this target to avoid double-booking

        # result is False -> nothing was submitted; safe to retry next cycle.
        page.screenshot(path=os.path.join(self.data_dir, f"stuck_{safe}.png"))
        log.warning("[%s] Did not submit (confirm button never clickable / not on "
                    "confirm page). Will retry next cycle. Screenshot stuck_%s.png.",
                    target["label"], safe)
        return False

    def _payment_required_hint(self, page):
        """Heuristic: is the checkout asking for a card number? That usually
        means no payment method is saved on the account. Card fields are often
        inside a payment iframe (Braintree/Stripe/Spreedly)."""
        sels = (
            "input[autocomplete='cc-number']",
            "input[name*='cardnumber' i]", "input[name*='card_number' i]",
            "input[placeholder*='card number' i]",
            "iframe[name*='card' i]", "iframe[title*='card' i]",
            "iframe[src*='braintree' i]", "iframe[src*='stripe' i]",
            "iframe[src*='spreedly' i]",
        )
        for s in sels:
            try:
                loc = page.locator(s)
                if loc.count() > 0 and loc.first.is_visible():
                    return True
            except Exception:
                continue
        return False

    def _submit_and_verify(self, page, texts, target):
        """Click Complete reservation, clear any post-submit popup, then VERIFY
        the booking actually finalized. Returns:
          True         -> confirmed
          "unverified" -> clicked but couldn't confirm (do NOT auto-retry)
          False        -> never submitted (safe to retry)"""
        desc = self.wait_and_click_confirm(page, texts)
        if not desc:
            return False  # button never became clickable; nothing submitted

        log.info("[%s]   clicked Complete reservation; clearing any post-submit popup...",
                 target["label"])
        page.wait_for_timeout(1500)
        self.dismiss_popups(page)  # e.g. "Enable text alerts" shown after submit

        if self._wait_for_confirmation(page):
            return True

        # Not confirmed yet. If we're still on the confirm-purchase page with the
        # button available, the submit clearly didn't take -> re-click once.
        url = (page.url or "").lower()
        b, _ = self._confirm_button(page, texts)
        if "confirm-purchase" in url and b is not None:
            try:
                if b.is_visible() and b.is_enabled():
                    log.info("[%s]   still on confirm page; dismissing popup and "
                             "re-clicking Complete reservation.", target["label"])
                    self.dismiss_popups(page)
                    b.click(timeout=4000)
                    page.wait_for_timeout(1500)
                    self.dismiss_popups(page)
                    if self._wait_for_confirmation(page):
                        return True
            except Exception as exc:
                log.info("[%s]   re-click failed: %s", target["label"], exc)
            if "confirm-purchase" in (page.url or "").lower():
                return False  # still sitting on confirm page -> not submitted
        return "unverified"

    # Signals that a booking finalized (URL fragments and on-page text).
    CONFIRM_URL_HINTS = ("receipt", "confirmation", "confirmed", "purchase-complete",
                         "/profile/reservations", "order-complete")
    CONFIRM_TEXT_HINTS = ("reservation is confirmed", "reservation confirmed",
                          "booking confirmed", "you're all set", "you are all set",
                          "see you", "your reservation for", "confirmation number",
                          "added to your reservations")

    def _wait_for_confirmation(self, page, timeout_ms=12000):
        """Wait for a positive signal that the reservation finalized: a
        confirmation/receipt URL, success text, or leaving confirm-purchase with
        no purchase button left. Returns True/False."""
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            url = (page.url or "").lower()
            if "confirm-purchase" not in url and any(h in url for h in self.CONFIRM_URL_HINTS):
                log.info("   Confirmation detected via URL: %s", page.url)
                return True
            try:
                body = (page.inner_text("body") or "").lower()
            except Exception:
                body = ""
            if any(t in body for t in self.CONFIRM_TEXT_HINTS):
                log.info("   Confirmation detected via page text.")
                return True
            if "confirm-purchase" not in url and \
                    page.locator('[data-testid="purchase-button"]').count() == 0:
                log.info("   Left checkout with no purchase button remaining "
                         "(likely confirmed): %s", page.url)
                return True
            page.wait_for_timeout(500)
        return False

    def _scan_and_book(self, page, target):
        """For each anchor time: load the search, and the moment an in-window
        slot appears, alert and click it RIGHT THERE (no second navigation).
        Returns True only if the booking was submitted."""
        anchors = self._anchor_times(target)
        log.info("[%s] AUTO-BOOK scan over %d anchor(s): %s", target["label"],
                 len(anchors), [fmt_minutes(a) for a in anchors])
        for anchor in anchors:
            self._load_search(page, target, anchor)
            slots = sorted(self._scan_page(page, target), key=lambda s: s["minutes"])
            log.info("[%s]   in-window matches at this anchor: %s",
                     target["label"], [s["text"] for s in slots] or "none")
            if not slots:
                continue

            chosen = slots[0]  # earliest in-window slot on this page
            found = ", ".join(
                f"{s['text']} @ {s['restaurant']}" if s.get("restaurant") else s["text"]
                for s in slots)
            notify(self.cfg["notify"], "Tock slot available",
                   f"{target['label']} - {target['date']} party {target['party_size']}: "
                   f"{found}  ({self.search_url(target, anchor)})",
                   self.data_dir)
            log.info("[%s]   -> chosen slot: %s. Locating live button...",
                     target["label"], chosen["text"])

            btn = self._find_button(page, target, chosen["minutes"])
            if btn is None:
                log.warning("[%s]   slot %s vanished before click; trying next anchor.",
                            target["label"], chosen["text"])
                continue

            log.info("[%s]   live button found. Starting booking (attempt %d).",
                     target["label"], target["attempts"] + 1)
            target["attempts"] += 1
            try:
                return self.book_from_button(page, btn, target, chosen)
            except Exception as exc:
                log.warning("[%s] booking attempt errored: %s", target["label"], exc)
                page.screenshot(path=os.path.join(self.data_dir, "error_booking.png"))
                return False

        log.info("[%s] %s %s-%s party %d - no matching slots.",
                 target["label"], target["date"],
                 fmt_minutes(target["time_start"]), fmt_minutes(target["time_end"]),
                 target["party_size"])
        return False

    # -- single pass (used by 'check' and each 'run' cycle) ---------------- #
    def process(self, page, target, do_book):
        try:
            if do_book:
                return self._scan_and_book(page, target)
            slots = self.find_slots(page, target)
        except Exception as exc:
            log.warning("[%s] error while checking: %s", target["label"], exc)
            return False

        # check / notify-only path (no booking)
        if not slots:
            log.info("[%s] %s %s-%s party %d - no matching slots.",
                     target["label"], target["date"],
                     fmt_minutes(target["time_start"]), fmt_minutes(target["time_end"]),
                     target["party_size"])
            return False

        found = ", ".join(
            f"{s['text']} @ {s['restaurant']}" if s.get("restaurant") else s["text"]
            for s in slots)
        notify(self.cfg["notify"], "Tock slot available",
               f"{target['label']} - {target['date']} party {target['party_size']}: "
               f"{found}  ({self.search_url(target)})",
               self.data_dir)
        return True

    # -- commands ---------------------------------------------------------- #
    def check(self, targets):
        log.info("=" * 70)
        log.info("MODE: CHECK (DRY RUN) - reports availability, will NOT book.")
        log.info("      To actually book, run:  python tock_bot.py run")
        log.info("=" * 70)
        with sync_playwright() as p:
            ctx = self.open_context(p)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            for t in targets:
                log.info("-" * 70)
                log.info("TARGET: %s | %s | %s-%s | party %d | price %s",
                         t["label"], t["date"], fmt_minutes(t["time_start"]),
                         fmt_minutes(t["time_end"]), t["party_size"], t["price"] or "any")
                self.process(page, t, do_book=False)
            log.info("-" * 70)
            log.info("Check pass complete.")
            ctx.close()

    def run(self, targets, should_stop=None, on_event=None, targets_path=None):
        """Poll and book. Optional hooks let a GUI drive it:
          should_stop() -> bool   : return True to stop the loop promptly.
          on_event(kind, target, msg): status updates ("target", "booked",
                                       "no_slot", "unverified", "cycle", "done").
          targets_path            : if given, `completed` is persisted to that
                                    CSV whenever a target is booked."""
        should_stop = should_stop or (lambda: False)
        emit = on_event or (lambda *a, **k: None)

        do_book = self.cfg.get("mode", "auto_book") == "auto_book"
        interval = int(self.cfg.get("poll_interval_seconds", 45))
        jitter = int(self.cfg.get("poll_jitter_seconds", 20))
        stop_on_success = bool(self.cfg.get("stop_target_after_success", True))
        continuous = bool(self.cfg.get("continuous", True))
        max_attempts = int(self.cfg.get("max_booking_attempts_per_target", 2))

        pending = [t for t in targets if not t["done"]]
        log.info("=" * 70)
        log.info("MODE: RUN | booking=%s (config mode=%r)",
                 "ON (auto_book)" if do_book else "OFF (notify only)", self.cfg.get("mode"))
        log.info("      %d target(s) active (%d already completed), poll every %d-%ds",
                 len(pending), len(targets) - len(pending), interval, interval + jitter)
        if do_book:
            log.info("      Will click slots and COMPLETE reservations (real bookings).")
        log.info("      Continuous: %s | Stop from the app or Ctrl+C.", continuous)
        log.info("=" * 70)

        def mark_completed(t):
            t["completed"] = True
            t["done"] = True
            if targets_path:
                try:
                    write_targets(targets_path, targets)
                    log.info("[%s] marked completed in %s", t["label"],
                             os.path.basename(targets_path))
                except Exception as exc:
                    log.warning("Could not persist completed flag: %s", exc)

        with sync_playwright() as p:
            ctx = self.open_context(p)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                while any(not t["done"] for t in targets):
                    if should_stop():
                        log.info("Stop requested; ending run.")
                        break
                    for t in targets:
                        if t["done"]:
                            continue
                        if should_stop():
                            break
                        if do_book and not continuous and t["attempts"] >= max_attempts:
                            log.warning("[%s] hit max attempts (%d); giving up.",
                                        t["label"], max_attempts)
                            t["done"] = True
                            continue

                        log.info("-" * 70)
                        log.info("TARGET: %s | %s | %s-%s | party %d | price %s | attempt %d",
                                 t["label"], t["date"], fmt_minutes(t["time_start"]),
                                 fmt_minutes(t["time_end"]), t["party_size"],
                                 t["price"] or "any", t["attempts"] + 1)
                        emit("target", t, "checking")
                        ok = self.process(page, t, do_book=do_book)
                        if ok and do_book and stop_on_success:
                            mark_completed(t)
                            emit("booked", t, "booked")
                        elif not ok:
                            emit("no_slot", t, "no slot / not booked")
                        page.wait_for_timeout(random.randint(800, 2000))

                    remaining = [t["label"] for t in targets if not t["done"]]
                    if not remaining or should_stop():
                        break
                    wait_s = interval + random.randint(0, jitter)
                    log.info("Cycle done. Waiting %ds. Still watching: %s",
                             wait_s, ", ".join(remaining))
                    emit("cycle", None, f"waiting {wait_s}s; watching {len(remaining)}")
                    # Sleep in short slices so Stop is responsive.
                    slept = 0
                    while slept < wait_s and not should_stop():
                        time.sleep(1)
                        slept += 1
            except KeyboardInterrupt:
                log.info("Stopped by user.")
            finally:
                ctx.close()
        emit("done", None, "run finished")
        log.info("Run finished.")


# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Tock reservation bot")
    parser.add_argument("command", choices=["login", "check", "run"])
    parser.add_argument("--config", default=os.path.join(HERE, "config.json"))
    args = parser.parse_args()

    add_file_log(HERE)
    cfg = load_config(args.config)
    bot = TockBot(cfg)

    if args.command == "login":
        bot.login()
        return

    targets_path = os.path.join(HERE, cfg.get("targets_csv", "reservations.csv"))
    targets = read_targets(targets_path)
    if not targets:
        log.error("No valid targets in %s. Nothing to do.", targets_path)
        return

    if args.command == "check":
        bot.check(targets)
    else:
        bot.run(targets, targets_path=targets_path)


if __name__ == "__main__":
    main()
