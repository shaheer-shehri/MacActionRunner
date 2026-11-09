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
from qrnfc import (csv_parser, link_export, manual_entry, order_export,
                   template_registry, variants)
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
        ttk.Button(actions, text="New print file…", command=self._manual_order).pack(side="left", padx=6)
        ttk.Button(actions, text="Open output folder", command=self._open_output).pack(side="left")
        ttk.Button(actions, text="Open link list", command=self._open_links).pack(side="left", padx=6)
        ttk.Button(actions, text="Open export file", command=self._open_export).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Edit templates", command=self._edit_templates).pack(side="left")
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
                variants.decode_variant(o, cfg.colour_codes)
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
                                   progress_cb=progress_cb,
                                   log_cb=lambda m: self._ui_q.put(("log", m)))
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
        if len(order.output_paths) > 1:
            out += f"  (+{len(order.output_paths) - 1} more)"
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
        self._reveal(self.output_root)

    def _manual_order(self):
        """Create one print file by hand (email / eBay orders, no CSV)."""
        if not self.settings.folder_ok():
            messagebox.showerror("Folder missing",
                                 "Set up the app-data folder (config + templates) first.")
            return
        try:
            cfg = cfg_mod.load(self.settings.app_data_folder)
        except Exception as e:
            messagebox.showerror("Config error", str(e))
            return
        places = None
        if self.settings.places_api_key:
            try:
                places = PlacesClient(self.settings.places_api_key)
            except Exception as e:
                self._emit(f"Places disabled: {e}")
        self.output_root = cfg.output_root
        dlg = ManualOrderDialog(self, cfg, places)
        if dlg.created_path:
            self._emit(f"Created {os.path.basename(dlg.created_path)}")

    def _edit_templates(self):
        """Open config/templates.csv — the editable variant registry."""
        if not self.settings.app_data_folder:
            messagebox.showerror("Folder missing", "Choose an app-data folder first.")
            return
        path = template_registry.path_in(self.settings.app_data_folder)
        if not os.path.isfile(path):
            try:
                template_registry.write_default(path)
            except OSError as e:
                messagebox.showerror("Could not create", str(e))
                return
        self._reveal(path)

    def _open_links(self):
        """Open the NFC-writing worklist (links.csv) in the default app."""
        path = os.path.join(self.output_root or "", link_export.FILENAME)
        if not os.path.isfile(path):
            messagebox.showinfo("No link list",
                                "Run a batch first — the link list is written "
                                "alongside the print files.")
            return
        self._reveal(path)

    def _open_export(self):
        """Open the per-order export file (export.csv) in the default app."""
        path = os.path.join(self.output_root or "", order_export.FILENAME)
        if not os.path.isfile(path):
            messagebox.showinfo("No export file",
                                "Run a batch first — the export file is written "
                                "alongside the print files.")
            return
        self._reveal(path)

    @staticmethod
    def _reveal(path: str):
        if sys.platform == "win32":
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    def _emit(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")


class ManualDialog(tk.Toplevel):
    """Rare fallback: no unique Place ID could be resolved automatically.

    Order number / company / address are shown in read-only fields so they can be
    selected and copied (to pull up the order). The input accepts a bare Place ID
    — the tool builds the review link from it — or a full review link.
    """

    def __init__(self, master, order: Order):
        super().__init__(master)
        self.title(f"Manual lookup — order {order.order_number}")
        self.result = ""
        self.resizable(False, False)

        ttk.Label(self, text="No Place ID could be auto-resolved. Look it up and "
                             "paste the Place ID (or a full review link) below.",
                  justify="left").grid(row=0, column=0, columnspan=2, sticky="w",
                                       padx=12, pady=(10, 8))

        # Copyable order details (read-only entries).
        # NOTE: insert the text directly instead of using a per-iteration
        # tk.StringVar — a StringVar bound to a local goes out of scope at the
        # next loop iteration, CPython frees it, its __del__ unsets the Tcl
        # variable, and the Entry renders EMPTY. That bug hid the company and
        # address here, forcing a manual lookup of data the tool already had.
        self.order = order
        for i, (label, value) in enumerate([
            ("Order number", order.order_number),
            ("Company", order.company),
            ("Address", order.address),
        ], start=1):
            ttk.Label(self, text=label + ":").grid(row=i, column=0, sticky="e", padx=(12, 4))
            e = ttk.Entry(self, width=64)
            e.insert(0, value or "")
            e.configure(state="readonly")
            e.grid(row=i, column=1, sticky="w", padx=(0, 12), pady=1)

        # Why did it land here? (e.g. "provided link rejected: unrecognized
        # link format", "places: no candidates"). Without this the operator
        # can't tell a bad link from a missing API key.
        why = "; ".join(order.notes) or "no link supplied"
        ttk.Label(self, text="Reason:").grid(row=4, column=0, sticky="e", padx=(12, 4))
        ttk.Label(self, text=why, foreground="#9a6700", wraplength=430,
                  justify="left").grid(row=4, column=1, sticky="w", padx=(0, 12))

        ttk.Label(self, text="Place ID / link:").grid(row=5, column=0, sticky="e",
                                                      padx=(12, 4), pady=(8, 0))
        self.entry = ttk.Entry(self, width=64)
        self.entry.grid(row=5, column=1, sticky="w", padx=(0, 12), pady=(8, 0))
        self.entry.focus_set()

        row = ttk.Frame(self)
        row.grid(row=6, column=0, columnspan=2, pady=10)
        ttk.Button(row, text="Search on Google", command=self._search).pack(side="left", padx=4)
        ttk.Button(row, text="Place ID Explorer", command=self._explorer).pack(side="left", padx=4)
        ttk.Button(row, text="Use", command=self._ok).pack(side="left", padx=4)
        ttk.Button(row, text="Skip", command=self._skip).pack(side="left", padx=4)
        self.bind("<Return>", lambda _e: self._ok())
        self.grab_set()
        self.transient(master)
        self.wait_window()

    def _search(self):
        """Open a Google search for the parsed company + address, so the
        operator doesn't have to retype data the tool already parsed."""
        import urllib.parse
        import webbrowser
        q = " ".join(x for x in (self.order.company, self.order.address) if x)
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(q))

    def _explorer(self):
        import webbrowser
        webbrowser.open("https://developers.google.com/maps/documentation/"
                        "javascript/examples/places-placeid-finder")

    def _ok(self):
        self.result = self.entry.get().strip()
        self.destroy()

    def _skip(self):
        self.result = ""
        self.destroy()


class ManualOrderDialog(tk.Toplevel):
    """Create a single print file without a CSV (email / eBay / phone orders).

    The variant dropdown is populated from the editable registry
    (config/templates.csv), so a variant the client adds there appears here
    with no code change.
    """

    def __init__(self, master, cfg, places=None):
        super().__init__(master)
        self.title("New print file")
        self.cfg = cfg
        self.places = places
        self.created_path = ""
        self.resizable(False, False)

        langs = sorted({d for d in os.listdir(cfg.templates_root)
                        if os.path.isdir(os.path.join(cfg.templates_root, d))})             if os.path.isdir(cfg.templates_root) else ["DE"]
        codes = list(cfg.colour_codes)

        # Keep every StringVar on self: a Var bound only to a local is garbage
        # collected, which silently blanks the widget bound to it.
        self.vars = {}
        row = 0

        def field(label, key, default=""):
            nonlocal row
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="e", padx=(12, 4), pady=3)
            v = tk.StringVar(value=default)
            self.vars[key] = v
            ttk.Entry(self, textvariable=v, width=52).grid(
                row=row, column=1, sticky="w", padx=(0, 12), pady=3)
            row += 1

        def combo(label, key, values, default):
            nonlocal row
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="e", padx=(12, 4), pady=3)
            v = tk.StringVar(value=default)
            self.vars[key] = v
            ttk.Combobox(self, textvariable=v, values=values, state="readonly",
                         width=20).grid(row=row, column=1, sticky="w", padx=(0, 12), pady=3)
            row += 1

        ttk.Label(self, text="Creates one print file and adds it to the link list.\n"
                             "The link box takes a bare Place ID or a full review link.",
                  foreground="#57606a").grid(row=row, column=0, columnspan=2,
                                             sticky="w", padx=12, pady=(10, 6))
        row += 1

        field("Reference (name / order ID):", "reference")
        combo("Sign language:", "language", langs, langs[0] if langs else "DE")
        combo("Shape:", "shape", sorted(variants.SHAPES), "D02")
        combo("Variant:", "code", codes, codes[0] if codes else "BLK")
        combo("Size:", "size", sorted(variants.SIZES), "A5")
        field("Company:", "company")
        field("Address:", "address")
        # Country = the marketplace the order came from; it is the last part of
        # the filename. Separate from the sign language above, which can differ
        # (an English sign bought on the French marketplace).
        combo("Country (marketplace):", "country", langs, langs[0] if langs else "DE")
        field("Place ID / review link (optional):", "link")
        field("Material (optional, e.g. Eiche):", "material")

        self.status = ttk.Label(self, text="", foreground="#57606a", wraplength=430,
                                justify="left")
        self.status.grid(row=row, column=0, columnspan=2, sticky="w", padx=12)
        row += 1

        bar = ttk.Frame(self)
        bar.grid(row=row, column=0, columnspan=2, pady=10)
        self.create_btn = ttk.Button(bar, text="Create print file", command=self._create)
        self.create_btn.pack(side="left", padx=4)
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="left", padx=4)

        self.grab_set()
        self.transient(master)
        self.wait_window()

    def _get(self, key):
        return self.vars[key].get().strip()

    def _create(self):
        if not self._get("reference"):
            self.status.config(text="A reference is required — it becomes the filename.",
                               foreground="#cf222e")
            return
        if not self._get("company") and not self._get("link"):
            self.status.config(text="Enter a company (for the Places lookup) or a "
                                    "Place ID / review link.", foreground="#cf222e")
            return

        self.create_btn.config(state="disabled")
        self.status.config(text="Resolving link and rendering…", foreground="#57606a")
        self.update_idletasks()
        try:
            order = manual_entry.create(
                reference=self._get("reference"),
                language=self._get("language"),
                shape=self._get("shape"),
                code=self._get("code"),
                size=self._get("size"),
                company=self._get("company"),
                address=self._get("address"),
                cfg=self.cfg,
                places=self.places,
                link=self._get("link"),
                material_text=self._get("material"),
                country=self._get("country"),
            )
        except Exception as e:
            self.status.config(text=f"Failed: {e}", foreground="#cf222e")
            self.create_btn.config(state="normal")
            return

        self.created_path = order.output_path
        self.status.config(
            text=f"Created {os.path.basename(order.output_path)}  "
                 f"(link source: {order.link_source.value})", foreground="#1a7f37")
        self.create_btn.config(state="normal")



def main():
    App().mainloop()


if __name__ == "__main__":
    main()
