# -*- coding: utf-8 -*-
"""
Tock Reservation Bot - desktop GUI (Tkinter).

Buttons:
  Login        Open a browser to sign into Tock and add a payment card. The
               session is saved; the bot never stores your password or card.
  Start        Begin monitoring the reservations table and auto-book matches.
  Stop         Stop monitoring.
Table:
  Editable reservation rows with a "completed" column. Completed rows are
  skipped, and a row is auto-marked completed once the bot books it.

Data (config, reservations.csv, saved session, logs, screenshots) lives in a
writable per-user folder so it works inside a read-only .app bundle.
"""

import os
import sys
import queue
import shutil
import logging
import threading
import subprocess

import tkinter as tk
from tkinter import ttk, messagebox

# Point Playwright at a writable browser cache before it is imported anywhere.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                      os.path.expanduser("~/.cache/ms-playwright"))

import tock_bot as engine  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


APP_NAME = "TockReservationBot"


def user_data_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def resource_path(name):
    """Path to a bundled default file (works both frozen and from source)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def ensure_user_files(data_dir):
    for name in ("config.json", "reservations.csv"):
        dst = os.path.join(data_dir, name)
        if not os.path.exists(dst):
            src = resource_path(name)
            if os.path.exists(src):
                shutil.copy(src, dst)


def playwright_cli():
    """Cross-platform Playwright CLI invocation: the bundled node runs cli.js.
    Works on macOS/Linux (node) and Windows (node.exe), frozen or from source."""
    import playwright
    base = os.path.join(os.path.dirname(playwright.__file__), "driver")
    node = os.path.join(base, "node.exe" if sys.platform == "win32" else "node")
    cli = os.path.join(base, "package", "cli.js")
    return [node, cli]


# --------------------------------------------------------------------------- #
class LogQueueHandler(logging.Handler):
    """Feed log records to the GUI thread via a queue."""
    def __init__(self, q):
        super().__init__()
        self.q = q
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            self.q.put(("log", self.format(record)))
        except Exception:
            pass


class App:
    COLS = engine.CSV_FIELDS  # canonical column order

    def __init__(self, root):
        self.root = root
        self.data_dir = user_data_dir()
        ensure_user_files(self.data_dir)
        engine.add_file_log(self.data_dir)

        self.cfg_path = os.path.join(self.data_dir, "config.json")
        self.csv_path = os.path.join(self.data_dir, "reservations.csv")
        self.cfg = engine.load_config(self.cfg_path)

        self.q = queue.Queue()
        self.stop_flag = threading.Event()
        self.login_done = threading.Event()
        self.worker = None
        self.login_thread = None
        self.browser_ready = False
        self.targets = []

        logging.getLogger().addHandler(LogQueueHandler(self.q))
        logging.getLogger().setLevel(logging.INFO)

        root.title("Tock Reservation Bot")
        root.geometry("1180x680")
        self._build_ui()
        self._load_table()
        self.root.after(120, self._drain_queue)
        logging.getLogger("tock").info("Data folder: %s", self.data_dir)

    # -- UI ---------------------------------------------------------------- #
    def _build_ui(self):
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")
        self.btn_login = ttk.Button(bar, text="Login / Add card", command=self.on_login)
        self.btn_login.pack(side="left")
        self.btn_start = ttk.Button(bar, text="▶ Start", command=self.on_start)
        self.btn_start.pack(side="left", padx=(8, 0))
        self.btn_stop = ttk.Button(bar, text="■ Stop", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(bar, text="Add row", command=self.add_row).pack(side="left")
        ttk.Button(bar, text="Delete row", command=self.delete_row).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Toggle completed", command=self.toggle_completed).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Save", command=self.save_table).pack(side="left", padx=(8, 0))
        self.status = ttk.Label(bar, text="Idle", anchor="e")
        self.status.pack(side="right")

        mid = ttk.Frame(self.root, padding=(8, 0))
        mid.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(mid, columns=self.COLS, show="headings", height=10)
        for c in self.COLS:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=110 if c not in ("notes", "latlng") else 150,
                             anchor="w", stretch=False)
        ysb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(mid, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)
        self.tree.tag_configure("completed", foreground="#3a7d3a")
        self.tree.bind("<Double-1>", self._on_double_click)

        hint = ttk.Label(self.root, padding=(10, 2),
                         text="Double-click a cell to edit. Double-click the "
                              "'completed' cell to toggle. Booked rows are marked "
                              "completed automatically and skipped next time.")
        hint.pack(fill="x")

        logf = ttk.LabelFrame(self.root, text="Activity log", padding=6)
        logf.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.logbox = tk.Text(logf, height=12, wrap="word", state="disabled",
                              font=("Menlo" if sys.platform == "darwin" else "Consolas", 10))
        lsb = ttk.Scrollbar(logf, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=lsb.set)
        self.logbox.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")

    # -- table <-> csv ----------------------------------------------------- #
    def _row_values(self, t):
        def tm(v):
            return engine.fmt_minutes(v) if isinstance(v, int) else v
        return [t.get("restaurant", ""), t.get("slug", ""), t.get("city_slug", ""),
                t.get("city", ""), t.get("latlng", ""), t.get("date", ""),
                tm(t.get("time_start", "")), tm(t.get("time_end", "")),
                t.get("party_size", ""), t.get("price", ""),
                t.get("type", "DINE_IN_EXPERIENCES"),
                "yes" if t.get("completed") else "", t.get("notes", "")]

    def _load_table(self):
        self.targets = engine.read_targets(self.csv_path)
        self._refresh_table()

    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        for t in self.targets:
            vals = self._row_values(t)
            tag = ("completed",) if t.get("completed") else ()
            self.tree.insert("", "end", values=vals, tags=tag)

    def _table_to_dicts(self):
        rows = []
        for iid in self.tree.get_children():
            vals = self.tree.item(iid, "values")
            rows.append(dict(zip(self.COLS, vals)))
        return rows

    def save_table(self):
        """Write the grid back to reservations.csv via a raw-dict round-trip."""
        import csv
        try:
            with open(self.csv_path, "w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=self.COLS)
                w.writeheader()
                for row in self._table_to_dicts():
                    w.writerow(row)
            self.targets = engine.read_targets(self.csv_path)
            self._refresh_table()
            self._set_status("Saved.")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    # -- cell editing ------------------------------------------------------ #
    def _on_double_click(self, event):
        if self.worker and self.worker.is_alive():
            return  # no editing while running
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not iid or not col:
            return
        cidx = int(col[1:]) - 1
        colname = self.COLS[cidx]
        if colname == "completed":
            vals = list(self.tree.item(iid, "values"))
            vals[cidx] = "" if vals[cidx] else "yes"
            self.tree.item(iid, values=vals,
                           tags=("completed",) if vals[cidx] else ())
            return
        self._edit_cell(iid, cidx)

    def _edit_cell(self, iid, cidx):
        x, y, w, h = self.tree.bbox(iid, self.COLS[cidx])
        vals = list(self.tree.item(iid, "values"))
        ent = ttk.Entry(self.tree)
        ent.insert(0, vals[cidx])
        ent.select_range(0, "end")
        ent.focus()
        ent.place(x=x, y=y, width=w, height=h)

        def commit(_=None):
            vals[cidx] = ent.get()
            self.tree.item(iid, values=vals)
            ent.destroy()
        ent.bind("<Return>", commit)
        ent.bind("<FocusOut>", commit)
        ent.bind("<Escape>", lambda e: ent.destroy())

    def add_row(self):
        blank = ["", "", "hong-kong", "Hong Kong", "22.3193039,114.1693611",
                 "2026-01-01", "18:00", "21:00", "2", "", "DINE_IN_EXPERIENCES", "", ""]
        self.tree.insert("", "end", values=blank)

    def delete_row(self):
        for iid in self.tree.selection():
            self.tree.delete(iid)

    def toggle_completed(self):
        ci = self.COLS.index("completed")
        for iid in self.tree.selection():
            vals = list(self.tree.item(iid, "values"))
            vals[ci] = "" if vals[ci] else "yes"
            self.tree.item(iid, values=vals,
                           tags=("completed",) if vals[ci] else ())

    # -- browser bootstrap ------------------------------------------------- #
    def _ensure_browser(self):
        if self.browser_ready:
            return True
        logging.getLogger("tock").info("Preparing browser (first run downloads "
                                       "Chromium, ~150MB)...")
        try:
            proc = subprocess.run(playwright_cli() + ["install", "chromium"],
                                  env=dict(os.environ), check=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True)
            if proc.stdout:
                logging.getLogger("tock").info(proc.stdout.strip()[-500:])
            self.browser_ready = True
            return True
        except Exception as exc:
            logging.getLogger("tock").error("Browser install failed: %s", exc)
            self.q.put(("error", "Could not install the Chromium browser. Check "
                                 "your internet connection and try again."))
            return False

    # -- login ------------------------------------------------------------- #
    def on_login(self):
        if self.login_thread and self.login_thread.is_alive():
            # Second click = finish login.
            self.login_done.set()
            self.btn_login.config(text="Login / Add card")
            return
        self.login_done.clear()
        self.btn_login.config(text="Finish login (click when signed in)")
        self._set_status("Opening login browser...")
        self.login_thread = threading.Thread(target=self._login_worker, daemon=True)
        self.login_thread.start()

    def _login_worker(self):
        if not self._ensure_browser():
            self.q.put(("login_reset", None))
            return
        try:
            bot = engine.TockBot(self.cfg, data_dir=self.data_dir)
            with sync_playwright() as p:
                ctx = bot.open_context(p)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(engine.BASE_URL + "/login", wait_until="domcontentloaded")
                logging.getLogger("tock").info(
                    "Sign in to Tock and add a payment card (Profile > Payment "
                    "methods). Then click 'Finish login'.")
                self.login_done.wait()
                ctx.close()
            logging.getLogger("tock").info("Session saved.")
        except Exception as exc:
            logging.getLogger("tock").error("Login error: %s", exc)
        finally:
            self.q.put(("login_reset", None))

    # -- start / stop ------------------------------------------------------ #
    def on_start(self):
        if self.worker and self.worker.is_alive():
            return
        self.save_table()  # persist edits, reload targets
        if not self.targets:
            messagebox.showwarning("No reservations", "Add at least one reservation row.")
            return
        active = [t for t in self.targets if not t["completed"]]
        if not active:
            messagebox.showinfo("All completed", "Every row is marked completed. "
                                "Uncheck a row's 'completed' to search for it.")
            return
        self.stop_flag.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._set_status("Running...")
        self.worker = threading.Thread(target=self._run_worker, daemon=True)
        self.worker.start()

    def _run_worker(self):
        if not self._ensure_browser():
            self.q.put(("run_stopped", None))
            return
        try:
            bot = engine.TockBot(self.cfg, data_dir=self.data_dir)
            bot.run(self.targets,
                    should_stop=self.stop_flag.is_set,
                    on_event=self._on_event,
                    targets_path=self.csv_path)
        except Exception as exc:
            logging.getLogger("tock").error("Run error: %s", exc)
        finally:
            self.q.put(("run_stopped", None))

    def on_stop(self):
        self.stop_flag.set()
        self._set_status("Stopping...")
        self.btn_stop.config(state="disabled")

    def _on_event(self, kind, target, msg):
        # Called from the worker thread - marshal to the GUI thread.
        if kind == "booked":
            self.q.put(("refresh", None))
        label = target["label"] if target else ""
        self.q.put(("status", f"{kind}: {label} {msg}".strip()))

    # -- queue pump -------------------------------------------------------- #
    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "status":
                    self._set_status(payload)
                elif kind == "refresh":
                    self.targets = engine.read_targets(self.csv_path)
                    self._refresh_table()
                elif kind == "error":
                    messagebox.showerror("Error", payload)
                elif kind == "login_reset":
                    self.btn_login.config(text="Login / Add card")
                    self._set_status("Idle")
                elif kind == "run_stopped":
                    self.btn_start.config(state="normal")
                    self.btn_stop.config(state="disabled")
                    self._set_status("Stopped")
        except queue.Empty:
            pass
        self.root.after(120, self._drain_queue)

    def _append_log(self, text):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _set_status(self, text):
        self.status.config(text=text)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
