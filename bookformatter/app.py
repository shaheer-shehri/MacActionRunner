"""
app.py - desktop front end for book_formatter
=============================================

A double-clickable window: pick the folder of scraped spreadsheets, paste the
OpenAI key once, press Run. Everything the CLI prints appears in the log pane.

Tkinter is used deliberately - it ships with Python and packages cleanly into a
Windows .exe and a macOS .app without any extra runtime.

    python app.py            # run from source
    python build_app.py      # produce the .exe / .app
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import traceback
from pathlib import Path


def _ensure_tcl() -> None:
    """Point Tcl/Tk at their library folders when the interpreter cannot find them.

    Some Windows Python installs ship Tcl in <prefix>/tcl/tcl8.6 while the Tk
    runtime only searches <prefix>/lib/tcl8.6, which makes Tk() fail with
    "Can't find a usable init.tcl". Setting the two variables costs nothing on a
    healthy install and repairs a broken one. Frozen apps carry their own copy.
    """
    if getattr(sys, "frozen", False) or os.environ.get("TCL_LIBRARY"):
        return
    prefix = Path(sys.base_prefix)
    for tcl_dir in (prefix / "tcl", prefix / "lib", prefix):
        for tcl in sorted(tcl_dir.glob("tcl8.*"), reverse=True):
            if (tcl / "init.tcl").exists():
                os.environ["TCL_LIBRARY"] = str(tcl)
                version = tcl.name.replace("tcl", "")
                tk_dir = tcl.with_name(f"tk{version}")
                if tk_dir.is_dir():
                    os.environ["TK_LIBRARY"] = str(tk_dir)
                return


_ensure_tcl()

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import book_formatter as bf

APP_NAME = "Book Listing Formatter"

# Settings live next to the user, not next to the app: a macOS .app bundle is
# read-only once installed, and a Windows install may sit under Program Files.
CONFIG_PATH = Path.home() / ".book_formatter.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(config: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        if os.name == "posix":
            CONFIG_PATH.chmod(0o600)  # the file holds an API key
    except OSError:
        pass


class FormatterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.minsize(760, 560)

        self.config_data = load_config()
        self.messages: queue.Queue[str | None] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_widgets()
        self._restore()
        self.after(100, self._drain_log)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- layout ----------------------------------------------------------- #
    def _build_widgets(self) -> None:
        pad = {"padx": 10, "pady": 6}
        self.columnconfigure(0, weight=1)

        form = ttk.Frame(self)
        form.grid(row=0, column=0, sticky="ew", **pad)
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Excel folder").grid(row=0, column=0, sticky="w")
        self.folder_var = tk.StringVar(value=str(bf.app_dir()))
        ttk.Entry(form, textvariable=self.folder_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(form, text="Browse…", command=self._pick_folder).grid(row=0, column=2)

        ttk.Label(form, text="OpenAI API key").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(form, textvariable=self.key_var, show="•")
        self.key_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Show", variable=self.show_key,
                        command=self._toggle_key).grid(row=1, column=2, pady=(6, 0))

        options = ttk.LabelFrame(self, text="Options")
        options.grid(row=1, column=0, sticky="ew", **pad)
        for column in range(6):
            options.columnconfigure(column, weight=1)

        ttk.Label(options, text="Model").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.model_var = tk.StringVar(value="gpt-4o-mini")
        ttk.Combobox(options, textvariable=self.model_var, width=16,
                     values=["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"]
                     ).grid(row=0, column=1, sticky="w")

        ttk.Label(options, text="Parallel calls").grid(row=0, column=2, sticky="e", padx=8)
        self.workers_var = tk.IntVar(value=4)
        ttk.Spinbox(options, from_=1, to=16, width=5, textvariable=self.workers_var
                    ).grid(row=0, column=3, sticky="w")

        ttk.Label(options, text="Row limit (0 = all)").grid(row=0, column=4, sticky="e", padx=8)
        self.limit_var = tk.IntVar(value=0)
        ttk.Spinbox(options, from_=0, to=100000, width=7, textvariable=self.limit_var
                    ).grid(row=0, column=5, sticky="w", padx=(0, 8))

        self.dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Dry run (no API calls)", variable=self.dry_run_var
                        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        self.infer_country_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Infer missing Country from the source site",
                        variable=self.infer_country_var
                        ).grid(row=1, column=2, columnspan=3, sticky="w", pady=(0, 8))

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="ew", padx=10)
        self.run_button = ttk.Button(actions, text="Run", command=self._start)
        self.run_button.pack(side="left")
        ttk.Button(actions, text="Open output folder", command=self._open_folder
                   ).pack(side="left", padx=8)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.pack(side="right")

        self.rowconfigure(3, weight=1)
        log_frame = ttk.Frame(self)
        log_frame.grid(row=3, column=0, sticky="nsew", **pad)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_widget = tk.Text(log_frame, wrap="none", height=18,
                                  font=("Menlo" if sys.platform == "darwin" else "Consolas", 10))
        self.log_widget.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, command=self.log_widget.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_widget.configure(yscrollcommand=scroll.set, state="disabled")

    # -- state ------------------------------------------------------------ #
    def _restore(self) -> None:
        if folder := self.config_data.get("folder"):
            if Path(folder).is_dir():
                self.folder_var.set(folder)
        self.key_var.set(self.config_data.get("api_key") or os.getenv("OPENAI_API_KEY", ""))
        self.model_var.set(self.config_data.get("model", self.model_var.get()))
        self.workers_var.set(self.config_data.get("workers", 4))

    def _remember(self) -> None:
        save_config({
            "folder": self.folder_var.get(),
            "api_key": self.key_var.get().strip(),
            "model": self.model_var.get(),
            "workers": int(self.workers_var.get()),
        })

    def _toggle_key(self) -> None:
        self.key_entry.configure(show="" if self.show_key.get() else "•")

    def _pick_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.folder_var.get() or str(Path.home()))
        if chosen:
            self.folder_var.set(chosen)

    def _open_folder(self) -> None:
        folder = Path(self.folder_var.get())
        if not folder.is_dir():
            messagebox.showwarning(APP_NAME, "That folder does not exist yet.")
            return
        if sys.platform == "darwin":
            os.system(f'open "{folder}"')
        elif os.name == "nt":
            os.startfile(folder)  # noqa: S606 - Windows shell open
        else:
            os.system(f'xdg-open "{folder}"')

    # -- running ------------------------------------------------------------ #
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        folder = Path(self.folder_var.get())
        if not folder.is_dir():
            messagebox.showerror(APP_NAME, "Choose a folder containing your .xlsx files.")
            return

        key = self.key_var.get().strip()
        if not key and not self.dry_run_var.get():
            messagebox.showerror(APP_NAME, "An OpenAI API key is required.")
            return
        if key:
            os.environ["OPENAI_API_KEY"] = key

        self._remember()
        self._clear_log()
        self.run_button.configure(state="disabled")
        self.progress.start(12)

        settings = bf.default_settings(
            folder=str(folder),
            model=self.model_var.get().strip() or "gpt-4o-mini",
            workers=max(1, int(self.workers_var.get())),
            limit=max(0, int(self.limit_var.get())),
            dry_run=bool(self.dry_run_var.get()),
            infer_country=bool(self.infer_country_var.get()),
        )

        bf.set_log_sink(self.messages.put)
        self.worker = threading.Thread(target=self._run_batch, args=(settings,), daemon=True)
        self.worker.start()

    def _run_batch(self, settings) -> None:
        try:
            code = bf.run(settings)
            self.messages.put("\nFinished." if code == 0 else "\nFinished with errors.")
        except Exception:
            self.messages.put("\nUnexpected error:\n" + traceback.format_exc())
        finally:
            self.messages.put(None)  # sentinel: the run is over

    # -- log pane ------------------------------------------------------------ #
    def _clear_log(self) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")

    def _append(self, text: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _drain_log(self) -> None:
        try:
            while True:
                item = self.messages.get_nowait()
                if item is None:
                    self.progress.stop()
                    self.run_button.configure(state="normal")
                else:
                    self._append(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel(APP_NAME, "A run is in progress. Quit anyway?"):
                return
        self._remember()
        self.destroy()


def self_check() -> int:
    """Build the window, render one frame, close it. Used to verify a packaged app.

    A --windowed build has no console, so the result is reported through the exit
    code: 0 = the bundle imports and Tk starts, 3 = it does not.
    """
    try:
        app = FormatterApp()
        app.update()
        app.destroy()
        return 0
    except Exception:
        traceback.print_exc()
        return 3


def main() -> int:
    if "--check" in sys.argv:
        return self_check()
    app = FormatterApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
