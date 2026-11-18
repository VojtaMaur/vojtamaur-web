#!/usr/bin/env python3
"""Windows export manager. Python 3.10+, standard library only.

Run beside the exporters in scripts/, or pass --project-root PATH.
Exporters are inspected as source; opening this app never runs an export.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from export_manager_core import ProcessRunner, Step, build_plan, discover, parse_extra_args
from export_manager_help import BUILD_HELP, HELP, LABELS as HELP_LABELS, SECTION_CHOICES, SECTION_DEFAULTS

DOCS = "https://vojtamaur.cz/documentation/"
LABELS = {
    "lang": "Jazyk", "language": "Jazyk", "section": "Sekce", "scope": "Rozsah",
    "format": "Formát", "quality": "Kvalita JPG", "dpi": "Rozlišení (DPI)",
    "max-edge": "Nejdelší hrana (px)", "pages": "Stránky / rozsahy", "max-pages": "Limit stránek (náhled)",
    "slug": "Konkrétní články (slug)", "output": "Výstupní soubor", "output-dir": "Výstupní složka",
    "pdf": "Zdrojové PDF", "source-manifest": "Manifest zdrojového PDF", "mode": "Režim",
    "image-quality": "Kvalita obrázků", "gif-mode": "Animované GIFy", "image-dpi": "DPI obrázků",
    "jpeg-quality": "Kvalita JPEG (1–100)", "pdf-quality": "Kvalita PDF", "compress": "Komprese",
    "pdfa": "Archivní PDF/A", "target-size": "Cílová velikost", "target": "Cíl", "limit": "Limit velikosti",
    "from-date": "Od data (YYYY-MM-DD)", "to-date": "Do data (YYYY-MM-DD)", "metadata": "Metadata",
    "separate": "Samostatné soubory", "font-size": "Velikost písma", "font": "Soubor písma",
    "bold-font": "Tučné písmo", "no-footer": "Bez patičky", "backend": "Převodník",
    "ghostscript": "Ghostscript", "pdftoppm": "Poppler (pdftoppm)", "timestamp": "Čas edice",
    "no-timestamp": "Použít staré názvy (přepisují výstup)", "dist": "Složka sestaveného webu",
    "project-root": "Kořen projektu", "timeout": "Časový limit (s)", "batch-size": "Velikost dávky",
    "max-file-mb": "Limit souboru (MB)", "build-command": "Vlastní příkaz sestavení",
    "verify": "Ověřit existující edici", "input": "Vstupní soubor", "list-values": "Vypsat dostupné hodnoty",
    "command": "Operace", "dry-run": "Pouze kontrola bez zápisu", "languages": "Jazyky",
}
LABELS.update({key.lstrip("-"): value for key, value in HELP_LABELS.items()})
PRIMARY = ["--lang", "--language", "--scope", "--section", "--slug", "--format", "--mode",
           "--image-quality", "--gif-mode", "--pdf-quality", "--compress", "--quality", "--dpi",
           "--max-edge", "--max-pages", "--pages", "--target", "--limit", "--from-date", "--to-date", "command"]


def pretty_command(command):
    return subprocess.list2cmdline([str(x) for x in command])


class ScrollFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, background="#f7f8fb")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, padding=(16, 12, 16, 16))
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))


class Manager(tk.Tk):
    def __init__(self, project_root):
        super().__init__()
        self.project_root = project_root.resolve()
        self.title("Vojta Maur — Správce exportů")
        self.geometry(f"{min(1180, self.winfo_screenwidth() - 60)}x{min(820, self.winfo_screenheight() - 100)}")
        self.minsize(820, 500)
        self.configure(bg="#f7f8fb")
        self.state_path = self.project_root / "exports" / "export-manager" / "settings.json"
        self.saved = self.read_settings()
        self.checked = set(self.saved.get("_checked_exports", []))
        self.rebuild = tk.BooleanVar(value=bool(self.saved.get("_rebuild_web", False)))
        self.build_command = tk.StringVar(value=self.saved.get("_build_command", "build:web:translate:signed"))
        # Session-only inputs. Never put either variable into saved settings/jobs.
        self.api_key = tk.StringVar(value=os.environ.get("DEEPL_AUTH_KEY", ""))
        self.gnupghome = tk.StringVar(value=os.environ.get("GNUPGHOME", ""))
        self.specs = []
        self.current = None
        self.fields = {}
        self.section_controls = {}
        self.jobs = []
        self.step_jobs = {}
        self.active_job = None
        self.events = queue.Queue()
        self.runner = ProcessRunner(self.events)
        self.preview_timer = None
        self.loading = False
        self.style_ui()
        self.make_ui()
        self.load_catalog()
        self.rebuild.trace_add("write", lambda *a: self.schedule_preview())
        self.build_command.trace_add("write", lambda *a: self.schedule_preview())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind_all("<MouseWheel>", self.wheel, add=True)
        self.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        self.bind("<F5>", lambda e: self.load_catalog())
        self.after(120, self.poll_events)

    def report_callback_exception(self, exc_type, exc, traceback):
        import traceback as tb
        message = self.redact("".join(tb.format_exception(exc_type, exc, traceback)))
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            (self.state_path.parent / "gui-error.log").write_text(message, encoding="utf-8")
        except OSError:
            pass
        messagebox.showerror("Chyba manageru", self.redact(str(exc)), parent=self)

    def style_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background="#f7f8fb", foreground="#202b3c")
        style.configure("TButton", padding=(11, 7))
        style.configure("Accent.TButton", background="#244fc8", foreground="white", font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#183da7"), ("disabled", "#c5ccdc")])
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 22))
        style.configure("Heading.TLabel", font=("Segoe UI Semibold", 15))
        style.configure("Sub.TLabel", foreground="#647086")
        style.configure("Note.TLabel", background="#eaf0ff", foreground="#24447e", padding=12)
        style.configure("Treeview", rowheight=31, background="white", fieldbackground="white", borderwidth=0)
        style.map("Treeview", background=[("selected", "#e2eaff")], foreground=[("selected", "#173d9d")])
        style.configure("TNotebook.Tab", padding=(18, 9))
        style.configure("TCheckbutton", padding=(0, 3))

    def make_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1, minsize=160)
        header = ttk.Frame(self, padding=(22, 16, 22, 12))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Správce exportů", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Dokumentace ↗", command=lambda: webbrowser.open(DOCS)).pack(side="right")
        ttk.Button(header, text="Otevřít exporty", command=lambda: self.open_folder(self.project_root / "exports")).pack(side="right", padx=8)
        ttk.Label(self, text=f"VOJTAMAUR.CZ   /   {self.project_root}", style="Sub.TLabel", padding=(24, 0, 24, 8)).grid(row=1, column=0, sticky="w")
        body = ttk.Panedwindow(self, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew", padx=18)
        sidebar = ttk.Frame(body, width=286)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(4, weight=1)
        body.add(sidebar, weight=0)
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self.filter_catalog())
        ttk.Label(sidebar, text="ZAŠKRTNI EXPORTY KE SPUŠTĚNÍ", style="Sub.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.search_entry = ttk.Entry(sidebar, textvariable=self.search)
        self.search_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        ttk.Label(sidebar, text="Kliknutí na název otevře nastavení.", style="Sub.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 7))
        select_bar = ttk.Frame(sidebar)
        select_bar.grid(row=3, column=0, sticky="ew", pady=(0, 7))
        ttk.Button(select_bar, text="Vybrat zobrazené", command=lambda: self.check_visible(True)).pack(side="left")
        ttk.Button(select_bar, text="Zrušit výběr", command=lambda: self.check_visible(False)).pack(side="left", padx=5)
        tree_frame = ttk.Frame(sidebar)
        tree_frame.grid(row=4, column=0, sticky="nsew", padx=(0, 10))
        self.catalog = ttk.Treeview(tree_frame, columns=("name",), show="tree headings", selectmode="browse")
        self.catalog.heading("#0", text="✓")
        self.catalog.column("#0", width=40, minwidth=40, stretch=False)
        self.catalog.heading("name", text="Export / nastavení")
        self.catalog.column("name", width=220, minwidth=150)
        bar = ttk.Scrollbar(tree_frame, command=self.catalog.yview)
        self.catalog.configure(yscrollcommand=bar.set)
        self.catalog.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.catalog.bind("<<TreeviewSelect>>", self.select_export)
        self.catalog.bind("<Button-1>", self.catalog_click, add=True)
        self.catalog.bind("<space>", self.catalog_space)
        self.count = ttk.Label(sidebar, text="", style="Sub.TLabel")
        self.count.grid(row=5, column=0, sticky="w", pady=6)
        ttk.Button(sidebar, text="Obnovit seznam  ·  F5", command=self.load_catalog).grid(row=6, column=0, sticky="ew", padx=(0, 10))
        right = ttk.Frame(body, padding=(16, 0, 0, 0))
        body.add(right, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)
        self.heading = ttk.Label(right, text="Vyber export", style="Heading.TLabel")
        self.heading.grid(row=0, column=0, sticky="w")
        self.summary = ttk.Label(right, text="", wraplength=780, style="Sub.TLabel")
        self.summary.grid(row=1, column=0, sticky="ew", pady=(5, 5))
        right.bind("<Configure>", lambda e: self.summary.configure(wraplength=max(260, e.width - 20)))
        self.doc_button = ttk.Button(right, text="Dokumentace tohoto exportu ↗", command=self.open_export_docs)
        self.doc_button.grid(row=2, column=0, sticky="w", pady=(0, 7))
        self.notebook = ttk.Notebook(right)
        self.notebook.grid(row=3, column=0, sticky="nsew")
        self.params = ScrollFrame(self.notebook)
        self.params.body.bind("<Configure>", self.fit_parameter_text, add=True)
        self.queue_tab = ttk.Frame(self.notebook, padding=14)
        self.log_tab = ttk.Frame(self.notebook, padding=14)
        self.help_tab = ttk.Frame(self.notebook, padding=14)
        self.build_tab = ScrollFrame(self.notebook)
        self.build_tab.body.bind("<Configure>", self.fit_parameter_text, add=True)
        for tab, title in [(self.params, "Nastavení"), (self.queue_tab, "Sestava (0)"), (self.log_tab, "Průběh"), (self.build_tab, "Příprava webu"), (self.help_tab, "Nápověda")]:
            self.notebook.add(tab, text=title)
        self.make_queue()
        self.make_log()
        self.make_build_settings()
        self.help_text = tk.Text(self.help_tab, wrap="word", font=("Segoe UI", 11), relief="flat", padx=14, pady=12, background="white")
        help_bar = ttk.Scrollbar(self.help_tab, command=self.help_text.yview)
        self.help_text.configure(yscrollcommand=help_bar.set)
        self.help_text.pack(side="left", fill="both", expand=True)
        help_bar.pack(side="right", fill="y")
        self.preview_label = ttk.Label(right, text="POSTUP PRO OTEVŘENÝ EXPORT", style="Sub.TLabel")
        self.preview_label.grid(row=4, column=0, sticky="w", pady=(7, 3))
        self.preview = tk.Text(right, height=3, wrap="word", font=("Consolas", 9), relief="flat", background="#eaf0f7", padx=8, pady=5)
        self.preview.grid(row=5, column=0, sticky="ew")
        self.preview.configure(state="disabled")
        self.notebook.bind("<<NotebookTabChanged>>", self.layout_tab)
        self.status = tk.StringVar(value="Zaškrtni exporty vlevo a spusť vybrané. Kliknutím na název změníš nastavení.")
        footer = ttk.Frame(self, padding=(18, 10, 18, 12))
        footer.grid(row=3, column=0, sticky="ew")
        controls = ttk.Frame(footer)
        controls.pack(fill="x")
        self.run_button = ttk.Button(controls, text="▶  Spustit vybrané (0)", style="Accent.TButton", command=self.run_checked)
        self.run_button.pack(side="left")
        self.run_current_button = ttk.Button(controls, text="Spustit tento export", command=self.run_selected)
        self.run_current_button.pack(side="left", padx=7)
        ttk.Button(controls, text="+ Do sestavy", command=self.add_job).pack(side="left")
        self.stop_button = ttk.Button(controls, text="Zastavit", state="disabled", command=self.cancel_run)
        self.stop_button.pack(side="right")
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.pack(fill="x", pady=(10, 5))
        self.status_label = ttk.Label(footer, textvariable=self.status, style="Sub.TLabel", wraplength=1100)
        self.status_label.pack(anchor="w")
        footer.bind("<Configure>", lambda e: self.status_label.configure(wraplength=max(200, e.width - 40)))

    def layout_tab(self, event=None):
        selected = self.notebook.select()
        details = selected in (str(self.params), str(self.help_tab))
        for widget in (self.summary, self.doc_button):
            widget.grid() if details else widget.grid_remove()
        for widget in (self.preview_label, self.preview):
            widget.grid() if selected == str(self.params) else widget.grid_remove()

    def make_queue(self):
        self.queue_tab.columnconfigure(0, weight=1)
        self.queue_tab.rowconfigure(2, weight=1)
        # Reserve the controls before giving the remaining space to the list.
        # Two short rows also fit beside the export sidebar in a small window.
        bar = ttk.Frame(self.queue_tab)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.queue_action_buttons = []
        for label, action in [("↑", lambda: self.move_job(-1)), ("↓", lambda: self.move_job(1)), ("Odebrat", self.remove_job)]:
            button = ttk.Button(bar, text=label, command=action)
            button.pack(side="left", padx=(0, 5))
            self.queue_action_buttons.append(button)
        self.queue_remove_button = self.queue_action_buttons[-1]
        self.run_queue_button = ttk.Button(bar, text="Spustit sestavu", command=self.run_queue)
        self.run_queue_button.pack(side="right")
        files = ttk.Frame(self.queue_tab)
        files.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        for label, action in [("Uložit sestavu…", self.save_batch), ("Načíst sestavu…", self.load_batch)]:
            button = ttk.Button(files, text=label, command=action)
            button.pack(side="left", padx=(0, 5))
            self.queue_action_buttons.append(button)
        table = ttk.Frame(self.queue_tab)
        table.grid(row=2, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.queue_tree = ttk.Treeview(table, columns=("name", "args", "state"), show="headings", selectmode="browse", height=3)
        for key, title, width in [("name", "Export", 180), ("args", "Parametry", 250), ("state", "Stav", 115)]:
            self.queue_tree.heading(key, text=title)
            self.queue_tree.column(key, width=width, minwidth=65)
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table, command=self.queue_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.queue_tree.configure(yscrollcommand=scrollbar.set)

    def make_log(self):
        bar = ttk.Frame(self.log_tab)
        bar.pack(fill="x", pady=(0, 8))
        self.step_label = ttk.Label(bar, text="Zatím nebyl spuštěn žádný export.", style="Sub.TLabel", wraplength=580)
        self.step_label.pack(side="left")
        ttk.Button(bar, text="Otevřít logy", command=lambda: self.open_folder(self.state_path.parent / "logs")).pack(side="right")
        self.log = tk.Text(self.log_tab, wrap="word", font=("Consolas", 10), relief="flat", background="#172235", foreground="#e5edfc", padx=12, pady=12)
        log_scroll = ttk.Scrollbar(self.log_tab, command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def make_build_settings(self):
        body = self.build_tab.body
        ttk.Label(body, text="Příprava webu před exporty", style="Heading.TLabel").pack(anchor="w")
        ttk.Checkbutton(body, text="Před vybranými exporty obnovit web", variable=self.rebuild).pack(anchor="w", pady=(10, 5))
        ttk.Label(body, text="Postup sestavení webu", style="Sub.TLabel").pack(anchor="w", pady=(8, 3))
        try:
            scripts = json.loads((self.project_root / "package.json").read_text(encoding="utf-8"))["scripts"]
        except (OSError, ValueError, KeyError):
            scripts = {}
        commands = [name for name in ("build:web:translate:signed", "build:web:translate", "build:web:signed", "build:web", "build:web:strict:signed", "build:web:strict") if name in scripts]
        if self.build_command.get() not in commands and commands:
            self.build_command.set(commands[0])
        ttk.Combobox(body, textvariable=self.build_command, values=commands, state="readonly").pack(fill="x")
        ttk.Label(body, text="Výchozí postup doplní chybějící překlady a podepíše web i Gemini.\nBěžný výběr exportů sdílí jedno sestavení webu. Bez obnovy se použije stávající dist/.", style="Sub.TLabel", wraplength=600).pack(anchor="w", pady=(6, 15))
        session = ttk.LabelFrame(body, text=" Přístupové údaje · jen pro toto otevřené okno ", padding=12)
        session.pack(fill="x")
        ttk.Label(session, text="DeepL API klíč (DEEPL_AUTH_KEY)").pack(anchor="w")
        self.api_key_entry = ttk.Entry(session, textvariable=self.api_key, show="•")
        self.api_key_entry.pack(fill="x", pady=(4, 12))
        ttk.Label(session, text="Složka GnuPG (GNUPGHOME)").pack(anchor="w")
        line = ttk.Frame(session)
        line.pack(fill="x", pady=(4, 10))
        ttk.Entry(line, textvariable=self.gnupghome).pack(side="left", fill="x", expand=True)
        def browse_home():
            selected = filedialog.askdirectory(parent=self, title="Vybrat složku GNUPGHOME")
            if selected:
                self.gnupghome.set(selected)
        ttk.Button(line, text="Vybrat…", command=browse_home).pack(side="left", padx=(6, 0))
        ttk.Button(session, text="Zapomenout dočasné údaje", command=self.clear_credentials).pack(anchor="w")
        ttk.Label(session, text="Oba údaje zůstávají pouze v paměti a předávají se spuštěným procesům.\nNeukládají se do nastavení, sestav ani zdrojových souborů. V logu se skrývají.\nPřevezmou se také z prostředí, ze kterého manager spustíš.", style="Sub.TLabel", wraplength=580).pack(anchor="w", pady=(10, 0))

    def clear_credentials(self):
        self.api_key.set("")
        self.gnupghome.set("")

    def redact(self, text):
        import re
        for value in (self.api_key.get(), self.gnupghome.get()):
            if value:
                variants = {value, value.replace("\\", "/"), value.replace("/", "\\")}
                for variant in variants:
                    text = re.sub(re.escape(variant), "[dočasný údaj]", text, flags=re.IGNORECASE)
        return text

    def safe_saved_data(self, value):
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, list):
            return [self.safe_saved_data(item) for item in value]
        if isinstance(value, dict):
            return {key: self.safe_saved_data(item) for key, item in value.items() if key not in ("DEEPL_AUTH_KEY", "GNUPGHOME")}
        return value

    def open_export_docs(self):
        if self.current:
            info = self.info(self.current)
            webbrowser.open(info.get("docs_url") or DOCS + ("#" + info["docs_anchor"] if info.get("docs_anchor") else ""))

    def catalog_click(self, event):
        item = self.catalog.identify_row(event.y)
        if item in self.spec_map and self.catalog.identify_column(event.x) == "#0":
            self.toggle_checked(item)
            return "break"

    def catalog_space(self, event=None):
        selection = self.catalog.selection()
        if selection and selection[0] in self.spec_map:
            self.toggle_checked(selection[0])
        return "break"

    def toggle_checked(self, spec_id):
        if spec_id in self.checked:
            self.checked.remove(spec_id)
        else:
            self.checked.add(spec_id)
        self.update_checked_ui()

    def check_visible(self, checked):
        if checked:
            self.checked.update(spec.id for spec in self.specs if self.catalog.exists(spec.id))
        else:
            self.checked.clear()
        self.update_checked_ui()

    def update_checked_ui(self):
        for spec in self.specs:
            if self.catalog.exists(spec.id):
                self.catalog.item(spec.id, text="☑" if spec.id in self.checked else "☐")
        self.run_button.configure(text=f"▶  Spustit vybrané ({len(self.checked)})")
        visible = sum(self.catalog.exists(spec.id) for spec in self.specs)
        self.count.configure(text=f"Vybráno {len(self.checked)} · zobrazeno {visible} exportů")

    def fit_parameter_text(self, event):
        width = max(240, event.width - 38)
        def fit(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Label) and child.cget("wraplength"):
                    if int(child.cget("wraplength")) != width:
                        child.configure(wraplength=width)
                fit(child)
        fit(event.widget)

    def read_settings(self):
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def remember(self):
        if self.current is not None and not self.loading:
            self.saved[self.current.id] = {"values": {k: v.get() for k, (_, v) in self.fields.items()},
                "extras": self.extras.get(), "fresh_pdf": self.fresh_pdf.get()}

    def persist(self):
        self.remember()
        self.saved["_checked_exports"] = sorted(self.checked)
        self.saved["_rebuild_web"] = self.rebuild.get()
        self.saved["_build_command"] = self.build_command.get()
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.safe_saved_data(self.saved), ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError as exc:
            self.status.set(f"Nastavení se nepodařilo uložit: {exc}")

    def info(self, spec):
        return BUILD_HELP.get(spec.npm_name) or HELP.get(Path(spec.script).name, {})

    def title_for(self, spec):
        title = self.info(spec).get("title", spec.title)
        if spec.npm_name.endswith(":metaweb") and "metaweb" not in title.lower():
            title += " · Metaweb"
        return title

    def load_catalog(self):
        self.remember()
        selected = self.current.id if self.current else self.saved.get("_last_export")
        try:
            self.specs = discover(self.project_root)
        except Exception as exc:
            messagebox.showerror("Seznam exportů", str(exc), parent=self)
            return
        self.spec_map = {spec.id: spec for spec in self.specs}
        self.checked.intersection_update(self.spec_map)
        self.filter_catalog()
        if selected in self.spec_map and self.catalog.exists(selected):
            self.catalog.selection_set(selected)
            self.catalog.see(selected)
            self.select_export(spec=self.spec_map[selected])
        elif selected in self.spec_map:
            self.select_export(spec=self.spec_map[selected])
        elif self.specs:
            visible = [s for s in self.specs if self.catalog.exists(s.id)]
            first = next((s for s in visible if Path(s.script).name == "export-site-pdf.py"), visible[0] if visible else self.specs[0])
            if self.catalog.exists(first.id):
                self.catalog.selection_set(first.id)
                self.catalog.see(first.id)
            self.select_export(spec=first)

    def filter_catalog(self):
        selected = self.catalog.selection()
        self.catalog.delete(*self.catalog.get_children())
        query = self.search.get().strip().casefold()
        groups = {}
        visible = 0
        for spec in sorted(self.specs, key=lambda item: (self.info(item).get("group", item.group), self.title_for(item).casefold())):
            info = self.info(spec)
            title = self.title_for(spec)
            if query and query not in f"{title} {spec.script} {spec.npm_name} {info.get('summary', '')}".casefold():
                continue
            group = info.get("group", spec.group)
            if group not in groups:
                groups[group] = self.catalog.insert("", "end", text="", values=(group.upper(),), tags=("category",))
            self.catalog.insert("", "end", iid=spec.id, text="☑" if spec.id in self.checked else "☐", values=(title,))
            visible += 1
        self.count.configure(text=f"{visible} exportů · načítáno ze skriptů")
        self.catalog.tag_configure("category", foreground="#6d7890", font=("Segoe UI Semibold", 9))
        self.update_checked_ui()
        if selected and self.catalog.exists(selected[0]):
            self.catalog.selection_set(selected)

    def select_export(self, event=None, spec=None):
        if spec is None:
            selection = self.catalog.selection()
            if not selection or selection[0] not in self.spec_map:
                return
            spec = self.spec_map[selection[0]]
        if spec is self.current:
            return
        self.remember()
        self.current = spec
        self.saved["_last_export"] = spec.id
        self.loading = True
        saved = self.saved.get(spec.id, {})
        for child in self.params.body.winfo_children():
            child.destroy()
        self.fields = {}
        self.section_controls = {}
        info = self.info(spec)
        self.heading.configure(text=self.title_for(spec))
        self.summary.configure(text=info.get("summary", spec.description or "Parametry se načítají přímo ze zdrojového skriptu."))
        self.params.canvas.yview_moveto(0)
        body = self.params.body
        workflow = ttk.LabelFrame(body, text=" Před exportem ", padding=12)
        workflow.pack(fill="x", pady=(0, 14))
        if spec.npm_name.startswith(("build:usb", "build:web")):
            ttk.Label(workflow, text="Tato položka sama sestaví web. Před spuštěním zkontroluj její nápovědu.", style="Sub.TLabel", wraplength=690).pack(anchor="w")
            ttk.Button(workflow, text="Změnit postup a zadat dočasné přístupy…", command=lambda: self.notebook.select(self.build_tab)).pack(anchor="w", pady=(2, 4))
        else:
            ttk.Checkbutton(workflow, text="Před exporty obnovit web (společná volba)", variable=self.rebuild).pack(anchor="w")
            ttk.Button(workflow, text="Změnit postup a zadat dočasné přístupy…", command=lambda: self.notebook.select(self.build_tab)).pack(anchor="w", pady=(2, 4))
        built = self.project_root / "dist" / "ALL_POSTS.json"
        try:
            stamp = datetime.fromtimestamp(built.stat().st_mtime).strftime("%d. %m. %Y v %H:%M")
            state = f"Index v dist/: {stamp}. Po úpravě článků nebo médií web znovu sestav."
        except OSError:
            state = "Index v dist/ chybí. Před exportem nejprve sestav web."
        ttk.Label(workflow, text=state, style="Sub.TLabel", wraplength=690).pack(anchor="w", pady=(3, 0))
        self.fresh_pdf = tk.BooleanVar(value=bool(saved.get("fresh_pdf", True)))
        if Path(spec.script).name == "export-site-images.py":
            ttk.Checkbutton(workflow, text="Nejdřív vytvořit nové PDF (doporučeno)", variable=self.fresh_pdf, command=self.schedule_preview).pack(anchor="w", pady=(8, 0))
            ttk.Label(workflow, text="PDF a obrázky dostanou stejný čas edice. Bez této volby se použije existující PDF.\nPro vlastní PDF tuto volbu vypni a nastav Zdrojové PDF v dalších parametrech.", style="Sub.TLabel", wraplength=690).pack(anchor="w")
        ttk.Label(body, text="Volitelné parametry", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(body, text="Prázdné pole = výchozí nastavení skriptu. U každého pole je uveden původní přepínač.", style="Sub.TLabel", wraplength=690).pack(anchor="w", pady=(4, 12))
        normal = ttk.Frame(body)
        normal.pack(fill="x")
        advanced = ttk.Frame(body)
        primary = [o for o in spec.options if o.flag in PRIMARY]
        other = [o for o in spec.options if o.flag not in PRIMARY and o.flag not in ("--help", "--version")]
        primary.sort(key=lambda o: PRIMARY.index(o.flag))
        for option in primary:
            self.option_row(normal, option, saved.get("values", {}).get(option.flag))
        self.advanced_visible = tk.BooleanVar(value=False)
        def toggle():
            if self.advanced_visible.get():
                advanced.pack(fill="x", before=extras_box)
            else:
                advanced.pack_forget()
        if other:
            ttk.Checkbutton(body, text=f"Další parametry ({len(other)})", variable=self.advanced_visible, command=toggle).pack(anchor="w", pady=(9, 5))
            for option in other:
                self.option_row(advanced, option, saved.get("values", {}).get(option.flag))
        extras_box = ttk.LabelFrame(body, text=" Vlastní argumenty ", padding=10)
        extras_box.pack(fill="x", pady=(12, 8))
        self.extras = tk.StringVar(value=saved.get("extras", ""))
        self.extras.trace_add("write", lambda *a: self.schedule_preview())
        ttk.Entry(extras_box, textvariable=self.extras).pack(fill="x")
        ttk.Label(extras_box, text='Pro nové nebo zvláštní volby. Cesty s mezerami uzavři do dvojitých uvozovek.\nOpakované přepínače piš např. --section volna-tvorba --section vystavy.', style="Sub.TLabel", wraplength=680).pack(anchor="w", pady=(5, 0))
        ttk.Button(body, text="Obnovit výchozí nastavení", command=self.reset_form).pack(anchor="w", pady=(6, 8))
        self.render_help(spec)
        self.loading = False
        self.refresh_preview()

    def option_row(self, parent, option, saved):
        flag = option.flag
        key = flag.lstrip("-")
        row = ttk.Frame(parent, padding=(0, 0, 0, 11))
        row.pack(fill="x")
        label = LABELS.get(key, key.replace("-", " ").capitalize())
        if flag in ("--section", "--selection"):
            self.section_row(row, option, saved)
            return
        boolean = option.action in ("store_true", "store_false", "count", "BooleanOptionalAction", "store_const")
        if boolean:
            variable = tk.BooleanVar(value=bool(saved))
            ttk.Checkbutton(row, text=f"{label}   ({flag})", variable=variable, command=self.schedule_preview).pack(anchor="w")
        else:
            variable = tk.StringVar(value=str(saved) if saved is not None else "")
            ttk.Label(row, text=f"{label}   {flag}" + ("  · povinné" if option.required else "")).pack(anchor="w", pady=(0, 3))
            line = ttk.Frame(row)
            line.pack(fill="x")
            choices = [str(c) for c in option.choices]
            if choices and len(choices) <= 24 and option.nargs in ("", "?", "1", 1, None):
                control = ttk.Combobox(line, textvariable=variable, values=[""] + choices, state="readonly")
            else:
                control = ttk.Entry(line, textvariable=variable)
            control.pack(side="left", fill="x", expand=True)
            path_option = any(term in key for term in ("output", "input", "file", "font", "ghostscript", "pdftoppm", "manifest", "project-root")) or key in ("pdf", "dist", "content", "verapdf")
            if path_option:
                ttk.Button(line, text="…", width=3, command=lambda: self.browse_option(option, variable)).pack(side="left", padx=(6, 0))
            variable.trace_add("write", lambda *a: self.schedule_preview())
        hint = option.help or ""
        default = str(option.default) if option.default not in (None, "", "None") else ""
        if default:
            hint = f"Výchozí: {default}" + (f"  ·  {hint}" if hint else "")
        if hint:
            ttk.Label(row, text=hint, style="Sub.TLabel", wraplength=680).pack(anchor="w", pady=(3, 0))
        self.fields[flag] = (option, variable)

    def section_row(self, row, option, saved):
        ttk.Label(row, text=f"Sekce   {option.flag}").pack(anchor="w", pady=(0, 5))
        defaults = set(SECTION_DEFAULTS.get(Path(self.current.script).name, [key for key, _ in SECTION_CHOICES]))
        selected = set(str(saved).split(",")) if saved else defaults.copy()
        selected.discard("")
        if "all" in selected:
            selected = {key for key, _ in SECTION_CHOICES}
        choices = list(SECTION_CHOICES)
        known = {key for key, _ in choices}
        choices.extend((key, key) for key in sorted(selected - known) if key != "__none__")
        variable = tk.StringVar(value=saved or "")
        checks = {key: tk.BooleanVar(value=key in selected) for key, _ in choices}
        def changed():
            values = [key for key, _ in choices if checks[key].get()]
            variable.set("" if set(values) == defaults else ",".join(values) if values else "__none__")
            self.schedule_preview()
        for key, title in choices:
            ttk.Checkbutton(row, text=title, variable=checks[key], command=changed).pack(anchor="w")
        def reset():
            for key, check in checks.items():
                check.set(key in defaults)
            variable.set("")
            self.schedule_preview()
        ttk.Button(row, text="Výchozí sekce", command=reset).pack(anchor="w", pady=(4, 0))
        ttk.Label(row, text="Lze zaškrtnout více sekcí najednou.", style="Sub.TLabel").pack(anchor="w", pady=(4, 0))
        self.fields[option.flag] = (option, variable)
        self.section_controls[option.flag] = (checks, changed)

    def browse_option(self, option, variable):
        key = option.flag.lstrip("-")
        directory = key.endswith("dir") or key in ("dist", "content", "project-root", "verify")
        if self.current and Path(self.current.script).name in ("generate-gemini-capsule.mjs", "export-site-rosetta.mjs") and key == "output":
            directory = True
        kwargs = {"parent": self, "initialdir": str(self.project_root), "title": LABELS.get(key, key)}
        if directory:
            value = filedialog.askdirectory(**kwargs)
        elif key in ("output", "output-file"):
            value = filedialog.asksaveasfilename(**kwargs)
        else:
            value = filedialog.askopenfilename(**kwargs)
        if value:
            variable.set(value)

    def render_help(self, spec):
        info = self.info(spec)
        tips = info.get("tips", [])
        if isinstance(tips, str):
            tips = [tips]
        text = self.title_for(spec) + "\n\n" + info.get("summary", spec.description or "")
        if tips:
            text += "\n\n" + "\n\n".join("• " + tip for tip in tips)
        text += "\n\nJak manager funguje\n\n• Zaškrtni exporty vlevo a klikni na Spustit vybrané. Otevírat jejich nastavení není nutné.\n• Kliknutí na název otevře parametry. Sekce lze vybrat zaškrtnutím více voleb.\n• Na kartě Příprava webu zvol postup sestavení a zadej dočasné přístupy. Výchozí je překlad a podpis.\n• Přístupové údaje zůstávají v paměti, neukládají se do nastavení ani sestav a v logu se skrývají.\n• Běžné parametry a zaškrtnuté exporty se pamatují. Vlastní opakované varianty můžeš uložit na kartě Sestava.\n• Po přidání export-*.py/.mjs/.js do scripts/ nebo export:* do package.json stiskni F5.\n• Neznámé volby lze zadat do Vlastních argumentů.\n• Logy a běžná nastavení jsou v exports/export-manager/.\n• Zastavit ukončí běžící export i jeho potomky; rozpracované výstupy mohou zůstat neúplné."
        text += "\n\nZdroj: " + str(spec.script) + "\nPříkaz: " + pretty_command(spec.command)
        if info.get("output"):
            text += "\nVýstup: " + info["output"]
        text += "\nDokumentace: " + DOCS + ("#" + info["docs_anchor"] if info.get("docs_anchor") else "")
        text += "\n\nPrvní příprava prostředí\n\nManager potřebuje jen Python s Tkinterem. Samotné exporty mohou potřebovat balíčky z requirements-*-export.txt, Playwright Chromium, Ghostscript či Poppler podle dokumentace. Původní export-all.bat zůstává použitelný."
        self.set_text(self.help_text, text)

    def reset_form(self):
        if not self.current:
            return
        self.saved.pop(self.current.id, None)
        spec_id = self.current.id
        self.current = None
        if self.catalog.exists(spec_id):
            self.catalog.selection_set(spec_id)
        self.select_export(spec=self.spec_map[spec_id])

    def get_args(self):
        return self.arguments_for(self.current, {key: variable.get() for key, (_, variable) in self.fields.items()}, self.extras.get())

    def arguments_for(self, spec, values, extras=""):
        args = []
        for option in spec.options:
            flag = option.flag
            value = values.get(flag, "")
            if option.action in ("store_true", "store_false", "count", "BooleanOptionalAction", "store_const"):
                if value:
                    args.append(flag)
                continue
            value = str(value).strip()
            if flag in ("--section", "--selection") and value == "__none__":
                raise ValueError("Vyber alespoň jednu sekci nebo obnov výchozí sekce.")
            if not value:
                if option.required:
                    raise ValueError(f"Vyplň povinný parametr {flag}.")
                continue
            if option.type_name in ("int", "float"):
                try:
                    (int if option.type_name == "int" else float)(value)
                except ValueError:
                    raise ValueError(f"Parametr {flag} musí být číslo.") from None
            if option.nargs not in ("", None, "?", "1", 1):
                tokens = parse_extra_args(value)
            else:
                tokens = [value]
            if flag.startswith("-"):
                args.append(flag)
            args.extend(tokens)
        args.extend(parse_extra_args(extras))
        return args

    def schedule_preview(self):
        if self.loading:
            return
        if self.preview_timer:
            self.after_cancel(self.preview_timer)
        self.preview_timer = self.after(180, self.refresh_preview)

    def refresh_preview(self):
        self.preview_timer = None
        if not self.current:
            return
        try:
            plan = build_plan(self.project_root, self.current, self.get_args(), rebuild=self.rebuild.get() and not self.current.npm_name.startswith(("build:usb", "build:web")), fresh_pdf=self.fresh_pdf.get(), build_command=self.build_command.get())
            text = "\n".join(f"{i}. {s.title}\n   {pretty_command(s.command)}" for i, s in enumerate(plan, 1))
            stamps = {s.env.get("VOJTAMAUR_EXPORT_TIMESTAMP") for s in plan if s.env.get("VOJTAMAUR_EXPORT_TIMESTAMP")}
            if stamps:
                text += "\n   Sdílená edice PDF → obrázky: " + ", ".join(sorted(stamps))
        except ValueError as exc:
            text = "Uprav nastavení: " + str(exc)
        self.set_text(self.preview, text)

    @staticmethod
    def set_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled")

    def current_job(self):
        if not self.current:
            raise ValueError("Nejprve vyber export vlevo.")
        args = self.get_args()
        rebuild = self.rebuild.get() and not self.current.npm_name.startswith(("build:usb", "build:web"))
        build_plan(self.project_root, self.current, args, rebuild, self.fresh_pdf.get(), self.build_command.get())
        return {"id": self.current.id, "args": args, "rebuild": rebuild, "fresh_pdf": self.fresh_pdf.get(), "state": "Čeká"}

    def add_job(self):
        try:
            job = self.current_job()
        except ValueError as exc:
            messagebox.showerror("Nastavení exportu", str(exc), parent=self)
            return
        self.jobs.append(job)
        self.refresh_queue()
        self.persist()
        self.status.set(f"Přidáno do fronty: {self.title_for(self.current)} ({len(self.jobs)} celkem).")

    def refresh_queue(self):
        self.queue_tree.delete(*self.queue_tree.get_children())
        for i, job in enumerate(self.jobs):
            spec = self.spec_map.get(job["id"])
            title = self.title_for(spec) if spec else job["id"]
            flags = pretty_command(job["args"]) or "Výchozí parametry"
            if job.get("rebuild"):
                flags = "Sestavit web; " + flags
            self.queue_tree.insert("", "end", iid=str(i), values=(title, flags, job.get("state", "Čeká")))
        self.notebook.tab(self.queue_tab, text=f"Sestava ({len(self.jobs)})")

    def move_job(self, direction):
        if self.runner.running or not self.queue_tree.selection():
            return
        index = int(self.queue_tree.selection()[0])
        target = index + direction
        if 0 <= target < len(self.jobs):
            self.jobs[index], self.jobs[target] = self.jobs[target], self.jobs[index]
            self.refresh_queue()
            self.queue_tree.selection_set(str(target))

    def remove_job(self):
        if self.runner.running or not self.queue_tree.selection():
            return
        self.jobs.pop(int(self.queue_tree.selection()[0]))
        self.refresh_queue()

    def save_batch(self):
        path = filedialog.asksaveasfilename(parent=self, title="Uložit sestavu exportů", defaultextension=".json", filetypes=[("Sestava exportů", "*.json")], initialdir=str(self.state_path.parent))
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(self.safe_saved_data({"version": 1, "jobs": self.jobs}), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Uložení sestavy", str(exc), parent=self)

    def load_batch(self):
        if self.runner.running:
            return
        path = filedialog.askopenfilename(parent=self, title="Načíst sestavu exportů", filetypes=[("Sestava exportů", "*.json")], initialdir=str(self.state_path.parent))
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            jobs = payload["jobs"]
            if not isinstance(jobs, list) or len(jobs) > 1000:
                raise ValueError("Neplatná sestava exportů.")
            for job in jobs:
                if not isinstance(job, dict) or job.get("id") not in self.spec_map:
                    raise ValueError("Sestava obsahuje export, který v projektu chybí. Obnov seznam pomocí F5.")
                if not isinstance(job.get("args"), list) or not all(isinstance(v, str) for v in job["args"]):
                    raise ValueError("Neplatné parametry v sestavě.")
                job["state"] = "Čeká"
            self.jobs = jobs
            self.refresh_queue()
            self.notebook.select(self.queue_tab)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Načtení sestavy", str(exc), parent=self)

    def run_selected(self):
        try:
            job = self.current_job()
            self.start_jobs([job], queued=False)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Spuštění exportu", str(exc), parent=self)

    def run_checked(self):
        if self.runner.running:
            return
        if not self.checked:
            messagebox.showinfo("Vybrat exporty", "Zaškrtni exporty v levém sloupci a klikni na Spustit vybrané.", parent=self)
            return
        try:
            self.remember()
            jobs = []
            specs = [spec for spec in self.specs if spec.id in self.checked]
            # USB replaces dist with a file-based edition, so it belongs after consumers of the web build.
            specs.sort(key=lambda spec: 0 if spec.npm_name == "build:web" else 2 if spec.npm_name.startswith("build:usb") else 1)
            for spec in specs:
                saved = self.saved.get(spec.id, {})
                try:
                    args = self.arguments_for(spec, saved.get("values", {}), saved.get("extras", ""))
                except ValueError as exc:
                    raise ValueError(f"{self.title_for(spec)}: {exc}") from None
                jobs.append({"id": spec.id, "args": args,
                    "rebuild": self.rebuild.get() and not spec.npm_name.startswith(("build:usb", "build:web")),
                    "fresh_pdf": bool(saved.get("fresh_pdf", True)), "state": "Čeká"})
            self.start_jobs(jobs, queued=True)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Spuštění vybraných exportů", self.redact(str(exc)), parent=self)

    def run_queue(self):
        if not self.jobs:
            messagebox.showinfo("Fronta je prázdná", "Vyber export, nastav parametry a použij Přidat do fronty.", parent=self)
            return
        try:
            self.start_jobs(self.jobs, queued=True)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Spuštění fronty", str(exc), parent=self)

    def start_jobs(self, jobs, queued):
        if self.runner.running:
            return
        plan = []
        self.step_jobs = {}
        rebuilt = False
        for index, job in enumerate(jobs):
            spec = self.spec_map.get(job["id"])
            if not spec:
                raise ValueError(f"Export {job['id']} už v projektu není.")
            is_online = spec.npm_name == "build:web"
            rebuild = bool(job.get("rebuild")) and not rebuilt and not is_online
            steps = build_plan(self.project_root, spec, job["args"], rebuild=rebuild, fresh_pdf=bool(job.get("fresh_pdf", True)), build_command=self.build_command.get())
            created_by_build = (rebuilt or rebuild) and not job["args"] and (
                Path(spec.script).name == "generate-source-bundle.mjs" or
                (Path(spec.script).name == "generate-gemini-capsule.mjs" and ":translate" in self.build_command.get()))
            if created_by_build:
                # Recreating these defaults immediately after a signed build would invalidate its signature.
                steps = [step for step in steps if step.command != spec.command]
            rebuilt = rebuilt or rebuild or is_online
            if spec.npm_name.startswith("build:usb"):
                rebuilt = False
            for step in steps:
                plan.append(step)
                if queued:
                    self.step_jobs[len(plan)] = index
            job["state"] = "Součást sestavení" if created_by_build else "Čeká"
        if not plan:
            return
        runtime_env = {"DEEPL_AUTH_KEY": self.api_key.get().strip(), "GNUPGHOME": self.gnupghome.get().strip()}
        command_text = " ".join(part for step in plan for part in step.command)
        if ":translate" in command_text and not runtime_env["DEEPL_AUTH_KEY"]:
            self.notebook.select(self.build_tab)
            raise ValueError("Pro zvolený překladový postup vyplň dočasný DeepL API klíč na kartě Příprava webu.")
        signed = ":signed" in command_text or "sign-build.mjs" in command_text
        if signed and not runtime_env["GNUPGHOME"]:
            self.notebook.select(self.build_tab)
            raise ValueError("Pro podpis vyber složku GNUPGHOME na kartě Příprava webu.")
        if signed and not Path(runtime_env["GNUPGHOME"]).is_dir():
            self.notebook.select(self.build_tab)
            raise ValueError("Vybraná složka GNUPGHOME neexistuje.")
        if queued:
            self.jobs = jobs
        self.active_job = None
        self.was_queued = queued
        log_path = self.state_path.parent / "logs" / (datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f") + ".log")
        self.persist()
        self.set_text(self.log, "")
        self.progress.configure(value=0, maximum=len(plan))
        self.runner.start(plan, self.project_root, log_path, runtime_env=runtime_env)
        self.run_button.configure(state="disabled")
        self.run_current_button.configure(state="disabled")
        self.run_queue_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.notebook.select(self.log_tab)
        self.status.set(f"Spouštím {len(plan)} kroků. Log: {log_path.name}")
        self.refresh_queue()

    def cancel_run(self):
        self.runner.cancel()
        self.stop_button.configure(state="disabled")
        self.status.set("Ukončuji běžící export a jeho podprocesy…")

    def poll_events(self):
        try:
            # Limit each UI pass so a verbose exporter cannot freeze the window.
            for _ in range(250):
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", str(value))
                    if int(self.log.index("end-1c").split(".")[0]) > 9000:
                        self.log.delete("1.0", "2000.0")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif kind == "step":
                    index, total, title = value
                    self.progress.configure(value=index - 1, maximum=total)
                    self.step_label.configure(text=f"Krok {index}/{total}: {title}")
                    self.status.set(f"Probíhá {index}/{total}: {title}")
                    if self.was_queued:
                        next_job = self.step_jobs.get(index)
                        if self.active_job is not None and self.active_job != next_job:
                            self.jobs[self.active_job]["state"] = "Hotovo"
                        self.active_job = next_job
                        if next_job is not None:
                            self.jobs[next_job]["state"] = "Běží"
                        self.refresh_queue()
                elif kind == "done":
                    ok, message = value
                    self.run_button.configure(state="normal")
                    self.run_current_button.configure(state="normal")
                    self.run_queue_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status.set(message)
                    self.step_label.configure(text=message)
                    if ok:
                        self.progress.configure(value=self.progress["maximum"])
                    if self.was_queued:
                        if self.active_job is not None:
                            self.jobs[self.active_job]["state"] = "Hotovo" if ok else "Přerušeno / chyba"
                        self.refresh_queue()
        except queue.Empty:
            pass
        self.after(120, self.poll_events)

    def wheel(self, event):
        active = {str(self.params): self.params, str(self.build_tab): self.build_tab}.get(self.notebook.select())
        if active is None:
            return
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
            if widget and str(widget).startswith(str(active)) and not isinstance(widget, ttk.Combobox):
                active.canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass

    def open_folder(self, folder):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError as exc:
            messagebox.showerror("Otevření složky", str(exc), parent=self)

    def close(self):
        if self.runner.running:
            if not messagebox.askyesno("Běží export", "Ukončit běžící export i jeho podprocesy a zavřít manager?", parent=self):
                return
            self.runner.cancel()
            self.status.set("Ukončuji export…")
            self.after(150, self.close_when_stopped)
            return
        self.persist()
        self.clear_credentials()
        self.destroy()

    def close_when_stopped(self):
        if self.runner.running:
            self.after(150, self.close_when_stopped)
        else:
            self.persist()
            self.clear_credentials()
            self.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--check", action="store_true", help="Inspect exports and exit without opening a window or running exports.")
    args = parser.parse_args()
    if not (args.project_root / "package.json").is_file() or not (args.project_root / "scripts").is_dir():
        parser.error("Nenalezen projekt s package.json a složkou scripts. Použij --project-root CESTA.")
    if args.check:
        specs = discover(args.project_root)
        for spec in specs:
            print(f"{spec.id}: {len(spec.options)} parametrů | {pretty_command(spec.command)}")
        print(f"Celkem {len(specs)} exportů. Žádný export nebyl spuštěn.")
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    Manager(args.project_root).mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # pythonw has no console: startup failures must still be visible.
        import traceback
        details = traceback.format_exc()
        root_path = Path(__file__).resolve().parent.parent
        if "--project-root" in sys.argv:
            try:
                root_path = Path(sys.argv[sys.argv.index("--project-root") + 1])
            except (IndexError, ValueError):
                pass
        error_path = root_path / "exports" / "export-manager" / "startup-error.log"
        try:
            error_path.parent.mkdir(parents=True, exist_ok=True)
            error_path.write_text(details, encoding="utf-8")
        except OSError:
            pass
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"Manager se nepodařilo otevřít:\n\n{error}\n\nPodrobnosti: {error_path}", "Správce exportů", 0x10)
        else:
            print(details, file=sys.stderr)
        raise SystemExit(1)
