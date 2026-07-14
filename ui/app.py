"""Tkinter front-end for the NFC / QR review-print tool.

Flow: Settings (app-data folder + API key) -> Load CSV (orders shown in a table)
-> Run (per-order status updates live) -> Manual dialog only as a rare fallback
-> Summary + unresolved list -> Open output folder.

The batch runs on a worker thread; the worker talks to the UI through a queue,
and blocks on an Event only for the (rare) manual-entry modal.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from qrnfc import bootstrap
from qrnfc import config as cfg_mod
from qrnfc import csv_parser, variants
from qrnfc.models import LinkSource, Order
from qrnfc.pipeline import run_batch
from qrnfc.places import PlacesClient
from qrnfc.settings_store import LocalSettings

STATUS_COLOURS = {
    "provided": "#1a7f37",
    "places": "#0969da",
    "manual": "#9a6700",
    "unresolved": "#cf222e",
    "": "#57606a",
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NFC / QR Review Print Tool")
        self.geometry("960x640")
        self.minsize(820, 560)
        self.settings = LocalSettings.load()
        self.orders: list[Order] = []
        self.output_root = ""
        self._ui_q: queue.Queue = queue.Queue()
        self._running = False
        self._build()
        self.after(100, self._pump)
        self._refresh_folder_status()

    # ---- construction ----------------------------------------------------
    def _build(self):
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")
        bar.columnconfigure(1, weight=1)

        ttk.Label(bar, text="App-data folder:").grid(row=0, column=0, sticky="w")
        self.folder_var = tk.StringVar(value=self.settings.app_data_folder)
        ttk.Entry(bar, textvariable=self.folder_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(bar, text="Choose…", command=self._pick_folder).grid(row=0, column=2)
        ttk.Button(bar, text="Set up folder", command=self._setup_folder).grid(row=0, column=3, padx=(6, 0))

        ttk.Label(bar, text="Places API key:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.key_var = tk.StringVar(value=self.settings.places_api_key)
        ttk.Entry(bar, textvariable=self.key_var, show="*").grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Button(bar, text="Save", command=self._persist_settings).grid(row=1, column=2, pady=(6, 0))

        self.folder_status = ttk.Label(bar, text="", foreground="#57606a")
        self.folder_status.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        actions = ttk.Frame(self, padding=(10, 0))
        actions.pack(fill="x")
        ttk.Button(actions, text="Load CSV…", command=self._load_csv).pack(side="left")
        self.run_btn = ttk.Button(actions, text="Run", command=self._run, state="disabled")
        self.run_btn.pack(side="left", padx=6)
        ttk.Button(actions, text="Open output folder", command=self._open_output).pack(side="left")
        self.count_lbl = ttk.Label(actions, text="")
        self.count_lbl.pack(side="right")

        cols = ("row", "order", "sku", "variant", "company", "status", "output")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=16)
        widths = {"row": 40, "order": 150, "sku": 130, "variant": 120,
                  "company": 200, "status": 90, "output": 320}
        for c in cols:
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=widths[c], anchor="w")
        for src, colour in STATUS_COLOURS.items():
            self.tree.tag_configure(src or "none", foreground=colour)
        self.tree.pack(fill="both", expand=True, padx=10, pady=(8, 4))

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10)
        self.log = tk.Text(self, height=7, wrap="word")
        self.log.pack(fill="x", padx=10, pady=(6, 10))

    # ---- settings / folder ----------------------------------------------
    def _pick_folder(self):
        d = filedialog.askdirectory(title="Select the shared app-data folder")
        if d:
            self.folder_var.set(d)
            self._persist_settings()
            self._refresh_folder_status()

    def _persist_settings(self):
        self.settings.app_data_folder = self.folder_var.get().strip()
        self.settings.places_api_key = self.key_var.get().strip()
        self.settings.save()
        self._emit("Settings saved.")

    def _setup_folder(self):
        root = self.folder_var.get().strip()
        if not root:
            messagebox.showwarning("No folder", "Choose an app-data folder first.")
            return
        actions = bootstrap.scaffold(root)
        self._persist_settings()
        self._emit("Set up folder: " + (", ".join(actions) if actions else "already complete"))
        self._emit("Now copy the template PNGs into templates/<LANG>/ if not synced.")
        self._refresh_folder_status()

    def _refresh_folder_status(self):
        root = self.folder_var.get().strip()
        if not root or not os.path.isdir(root):
            self.folder_status.config(text="⚠ folder not set / not found", foreground="#cf222e")
            return
        st = bootstrap.status(root)
        ok = st["config"] and st["templates"] and st["template_count"] > 0
        msg = (f"config:{'✓' if st['config'] else '✗'}  "
               f"templates:{st['template_count']} png  output:{'✓' if st['output'] else '✗'}")
        self.folder_status.config(text=msg, foreground="#1a7f37" if ok else "#9a6700")

    # ---- load / run ------------------------------------------------------
    def _load_csv(self):
        if not self.settings.folder_ok():
            messagebox.showerror("Folder missing",
                                 "Set up the app-data folder (config + templates) first.")
            return
        path = filedialog.askopenfilename(title="Select shipping CSV",
                                          filetypes=[("CSV", "*.csv")])
        if not path:
            return
        self._csv_path = path
        try:
            cfg = cfg_mod.load(self.settings.app_data_folder)
            self.orders = csv_parser.read_orders(path, labels=cfg.labels)
            for o in self.orders:
                variants.decode_variant(o)
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return
        self._populate_table()
        self.run_btn.config(state="normal")
        self._emit(f"Loaded {len(self.orders)} orders from {os.path.basename(path)}.")

    def _populate_table(self):
        self.tree.delete(*self.tree.get_children())
        for o in self.orders:
            v = o.variant.template_key if o.variant else "?"
            self.tree.insert("", "end", iid=str(o.row_index),
                             values=(o.row_index + 1, o.order_number, o.sku, v,
                                     o.company, "", ""), tags=("none",))
        self.count_lbl.config(text=f"{len(self.orders)} orders")

    def _run(self):
        if self._running:
            return
        self._persist_settings()
        self._running = True
        self.run_btn.config(state="disabled")
        self.progress["value"] = 0
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        cfg = cfg_mod.load(self.settings.app_data_folder)
        self.output_root = cfg.output_root
        places = None
        if self.settings.places_api_key:
            try:
                places = PlacesClient(self.settings.places_api_key)
            except Exception as e:
                self._ui_q.put(("log", f"Places disabled: {e}"))
        else:
            self._ui_q.put(("log", "No API key — orders needing lookup go to manual."))

        def progress_cb(i, total, order):
            self._ui_q.put(("progress", (i, total, order)))

        try:
            unresolved = run_batch(self.orders, cfg, places, manual_cb=self._manual,
                                   progress_cb=progress_cb)
            self._ui_q.put(("done", unresolved))
        except Exception as e:
            self._ui_q.put(("log", f"ERROR: {e}"))
            self._ui_q.put(("done", []))

    def _manual(self, order: Order) -> str:
        ev = threading.Event()
        box = {"result": ""}
        self._ui_q.put(("manual", (order, box, ev)))
        ev.wait()
        return box["result"]

    # ---- UI-thread pump --------------------------------------------------
    def _pump(self):
        try:
            while True:
                kind, payload = self._ui_q.get_nowait()
                getattr(self, f"_on_{kind}")(payload)
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _on_progress(self, payload):
        i, total, order = payload
        self.progress["maximum"] = total
        self.progress["value"] = i
        src = order.link_source.value
        out = os.path.basename(order.output_path) if order.output_path else ""
        iid = str(order.row_index)
        if self.tree.exists(iid):
            vals = list(self.tree.item(iid, "values"))
            vals[5], vals[6] = src, out
            self.tree.item(iid, values=vals, tags=(src or "none",))
            self.tree.see(iid)

    def _on_done(self, unresolved):
        self._running = False
        self.run_btn.config(state="normal")
        done = len(self.orders) - len(unresolved)
        self._emit(f"DONE — {done} rendered, {len(unresolved)} unresolved.")
        for o in unresolved:
            self._emit(f"  UNRESOLVED  {o.order_number}  {o.company}  :: "
                       f"{'; '.join(o.notes) or 'no link'}")

    def _on_manual(self, payload):
        order, box, ev = payload
        box["result"] = ManualDialog(self, order).result
        ev.set()

    def _on_log(self, msg):
        self._emit(msg)

    # ---- misc ------------------------------------------------------------
    def _open_output(self):
        if not self.output_root or not os.path.isdir(self.output_root):
            messagebox.showinfo("No output", "Nothing generated yet.")
            return
        if sys.platform == "win32":
            os.startfile(self.output_root)  # noqa
        elif sys.platform == "darwin":
            subprocess.run(["open", self.output_root])
        else:
            subprocess.run(["xdg-open", self.output_root])

    def _emit(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")


class ManualDialog(tk.Toplevel):
    """Rare fallback: no unique Place ID could be resolved automatically."""

    def __init__(self, master, order: Order):
        super().__init__(master)
        self.title(f"Manual link — {order.company}")
        self.result = ""
        self.resizable(False, False)
        info = (f"No Place ID could be auto-resolved for order {order.order_number}.\n"
                f"Company:  {order.company}\nAddress:  {order.address}\n\n"
                f"Paste a Google review link, or leave blank to skip (stays unresolved):")
        ttk.Label(self, text=info, justify="left").pack(anchor="w", padx=12, pady=10)
        self.entry = ttk.Entry(self, width=76)
        self.entry.pack(padx=12)
        self.entry.focus_set()
        row = ttk.Frame(self); row.pack(pady=10)
        ttk.Button(row, text="Use link", command=self._ok).pack(side="left", padx=4)
        ttk.Button(row, text="Skip", command=self._skip).pack(side="left", padx=4)
        self.bind("<Return>", lambda _e: self._ok())
        self.grab_set()
        self.transient(master)
        self.wait_window()

    def _ok(self):
        self.result = self.entry.get().strip()
        self.destroy()

    def _skip(self):
        self.result = ""
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
