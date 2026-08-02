"""
Florida Land Machine — desktop window.

This is the double-clickable front end. It shows where the Input/Output folders
are, lets the operator open them, and runs the whole pipeline with a live scrolling
log so it is obvious the app is working. It contains no business logic itself — it
just drives app.main.run().
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog

from . import main as pipeline
from . import settings

APP_TITLE = "Florida Land Machine"


def _open_folder(path: Path) -> None:
    """Reveal a folder in the OS file browser."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:  # noqa: BLE001
        pass


def scaffold(root: Path) -> None:
    """
    Make sure the working folders exist next to the app, and drop a starter
    Buy Boxes workbook + Quick Start guide on first launch if they are missing.
    """
    (root / "Input").mkdir(parents=True, exist_ok=True)
    (root / "Output").mkdir(parents=True, exist_ok=True)
    (root / "Builder Buy Boxes").mkdir(parents=True, exist_ok=True)

    workbook = root / "Builder Buy Boxes" / "Master_Buyer_Buy_Boxes.xlsx"
    if not workbook.exists():
        template = pipeline.bundled_resource("Master_Buyer_Buy_Boxes.xlsx")
        if template.exists():
            shutil.copyfile(template, workbook)

    guide = root / "QUICK START.txt"
    if not guide.exists():
        bundled_guide = pipeline.bundled_resource("QUICK START.txt")
        if bundled_guide.exists():
            shutil.copyfile(bundled_guide, guide)


class App(ttk.Frame):
    def __init__(self, master: tk.Tk, root_dir: Path):
        super().__init__(master, padding=12)
        self.master = master
        self.root_dir = root_dir
        self.queue: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.pack(fill="both", expand=True)
        self._build()
        self.after(120, self._drain_queue)

    def _build(self) -> None:
        self.master.title(APP_TITLE)
        self.master.geometry("760x520")

        header = ttk.Label(self, text=APP_TITLE, font=("Helvetica", 18, "bold"))
        header.pack(anchor="w")

        folder_row = ttk.Frame(self)
        folder_row.pack(fill="x", pady=(2, 8))
        self.loc = ttk.Label(folder_row, foreground="#555",
                             text=f"Working folder:  {self.root_dir}")
        self.loc.pack(side="left")
        ttk.Button(folder_row, text="Change Working Folder…",
                   command=self._choose_folder).pack(side="right")

        steps = ttk.Label(
            self, justify="left", foreground="#333",
            text=("1.  Click 'Import Buy Boxes…' and pick YOUR workbook (it is copied into\n"
                  "     place for you — you don't need to know the folder).\n"
                  "2.  'Open Input Folder' -> put each county's files in a subfolder.\n"
                  "3.  Click Run.  Then use 'Open Output Folder' for your lists.\n"
                  "(Optional: 'Change Working Folder…' to use a folder of your choice.)"))
        steps.pack(anchor="w", pady=(0, 10))

        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(0, 8))
        ttk.Button(btns, text="Open Input Folder",
                   command=lambda: _open_folder(self.root_dir / "Input")).pack(side="left")
        ttk.Button(btns, text="Open Output Folder",
                   command=lambda: _open_folder(self.root_dir / "Output")).pack(side="left", padx=6)
        ttk.Button(btns, text="Import Buy Boxes…",
                   command=self._import_buy_boxes).pack(side="left")
        ttk.Button(btns, text="Open Buy Boxes Folder",
                   command=lambda: _open_folder(self.root_dir / "Builder Buy Boxes")).pack(side="left", padx=6)
        self.run_btn = ttk.Button(btns, text="▶  Run", command=self._start)
        self.run_btn.pack(side="right")
        self.diag_btn = ttk.Button(btns, text="Diagnostics", command=self._diagnostics)
        self.diag_btn.pack(side="right", padx=6)

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))

        self.log = scrolledtext.ScrolledText(self, height=18, wrap="word",
                                             font=("Menlo", 11), state="disabled")
        self.log.pack(fill="both", expand=True)

        self.status = ttk.Label(self, text="Ready.", foreground="#357a38")
        self.status.pack(anchor="w", pady=(8, 0))

    # -- import the user's Buy Boxes workbook ------------------------------
    def _import_buy_boxes(self) -> None:
        src = filedialog.askopenfilename(
            title="Choose YOUR Buy Boxes workbook (Master_Buyer_Buy_Boxes.xlsx)",
            initialdir=str(Path.home()),
            filetypes=[("Excel workbook", "*.xlsx *.xlsm *.xls"), ("All files", "*.*")])
        if not src:
            return
        from . import buyers
        dest_dir = self.root_dir / "Builder Buy Boxes"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "Master_Buyer_Buy_Boxes.xlsx"
        try:
            shutil.copyfile(src, dest)
        except Exception as exc:  # noqa: BLE001
            self._sink(f"Could not import that file: {exc}")
            return

        info = buyers.inspect_workbook(dest)
        self._sink(f"Imported your workbook to:\n  {dest}")
        if info.get("error"):
            self._sink(f"⚠️  But it could not be read: {info['error']}")
        elif info.get("is_template"):
            self._sink("⚠️  That file looks like the EXAMPLE template (builders named "
                       "'EXAMPLE'). Please import your REAL workbook instead.")
        elif info.get("active", 0) == 0:
            self._sink("⚠️  Imported, but 0 active builders were found. Check the 'Active' "
                       "column, then click Diagnostics.")
        else:
            self._sink(f"✅  {info['active']} active builder(s) loaded. You're ready — click Run.")

    # -- working folder selection ------------------------------------------
    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(
            title="Choose the folder for Input, Output and Builder Buy Boxes",
            initialdir=str(self.root_dir), mustexist=True)
        if not chosen:
            return
        path = Path(chosen)
        settings.save_working_dir(path)
        self.root_dir = path
        try:
            scaffold(path)
        except Exception:  # noqa: BLE001
            pass
        self.loc.configure(text=f"Working folder:  {path}")
        self._sink(f"Working folder set to: {path}")
        self._sink("Your Input, Output and Builder Buy Boxes folders are here now. "
                   "Put your workbook and county folders here, then click Run.")

    # -- logging plumbing (worker thread -> queue -> UI) --------------------
    def _sink(self, text: str) -> None:
        self.queue.put(text)

    def _drain_queue(self) -> None:
        try:
            while True:
                line = self.queue.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(120, self._drain_queue)

    # -- run control -------------------------------------------------------
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.run_btn.configure(state="disabled")
        self.status.configure(text="Working... (large counties can take a few minutes)",
                              foreground="#a06000")
        self.progress.start(12)
        self.worker = threading.Thread(target=self._run_pipeline, daemon=True)
        self.worker.start()

    def _run_pipeline(self) -> None:
        try:
            scaffold(self.root_dir)
            code = pipeline.main(sink=self._sink)
        except Exception as exc:  # noqa: BLE001
            self._sink(f"\nERROR: {exc}")
            code = 1
        self.after(0, lambda: self._finish(code))

    # -- diagnostics (quick check, no full processing) ---------------------
    def _diagnostics(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.diag_btn.configure(state="disabled")
        self.status.configure(text="Running diagnostics...", foreground="#a06000")

        def work() -> None:
            from . import diagnostics
            try:
                scaffold(self.root_dir)
                diag = diagnostics.preflight(self.root_dir)
                self._sink(diag.render())
                try:
                    saved = diag.save(self.root_dir / "Output" / "_Run Reports")
                    self._sink(f"\nDiagnostics saved: {saved}")
                except Exception:  # noqa: BLE001
                    pass
            except Exception as exc:  # noqa: BLE001
                self._sink(f"\nDiagnostics error: {exc}")
            self.after(0, self._finish_diag)

        threading.Thread(target=work, daemon=True).start()

    def _finish_diag(self) -> None:
        self.diag_btn.configure(state="normal")
        self.status.configure(text="Diagnostics complete.", foreground="#357a38")

    def _finish(self, code: int) -> None:
        self.progress.stop()
        self.run_btn.configure(state="normal")
        if code == 0:
            self.status.configure(text="Done. Opening the Output folder...",
                                  foreground="#357a38")
            _open_folder(self.root_dir / "Output")
        else:
            self.status.configure(text="Finished with problems - see the log above.",
                                  foreground="#b00020")


def launch() -> int:
    root_dir = pipeline.find_root()
    try:
        scaffold(root_dir)
    except Exception:  # noqa: BLE001
        pass
    win = tk.Tk()
    try:
        win.call("tk", "scaling", 1.3)
    except Exception:  # noqa: BLE001
        pass
    App(win, root_dir)
    win.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(launch())
