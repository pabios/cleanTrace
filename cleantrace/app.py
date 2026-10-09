"""Interface graphique Tkinter de CleanTrace (thème : ``theme.py``, inspiré de shadcn/ui).

Disposition :
    ┌ en-tête : CleanTrace · version ················ Aide · Réinitialiser · Exporter · Ouvrir ┐
    │ panneau latéral (cartes)          │ carte « Graphique » : courbes + barre de zoom         │
    │  - Voies de mesure                │                                                       │
    │  - Nettoyage                      │                                                       │
    │  - Base de temps                  │                                                       │
    │  - Enceinte climatique            │                                                       │
    │  - Correction au clic             │                                                       │
    └ barre d'état ─────────────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import queue
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List

import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from . import __version__
from .cleaning import CleaningOptions
from .dialogs import CleaningDialog
from .editing import ClickCorrector
from .export import Key
from .help import HelpWindow
from .loader import write_extract
from .plotting import PlotManager, format_hms
from .session import EXPORT_STEPS, TIME_MODES, Session
from .theme import C, CheckImages, ScrollFrame, apply_theme, bordered, card, separator

APP_TITLE = "CleanTrace — MultiPlotter pour bancs d'essai"
FILE_TYPES = [
    ("Fichiers de mesure", "*.csv *.txt *.dat *.CSV *.TXT *.DAT"),
    ("Tous les fichiers", "*.*"),
]
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "exemples"
EXAMPLE_FILES = ["GL980_Mes-_260601-170139.CSV", "nanodac_Rd_Z.txt"]


class CleanTraceApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.session = Session()
        self._checked: Dict[Key, bool] = {}
        self._item_key: Dict[str, Key] = {}  # id Treeview -> voie
        self._file_item: Dict[str, str] = {}  # nom de fichier -> id Treeview
        self._gid_key: Dict[str, Key] = {}  # gid de courbe -> voie
        self._key_color: Dict[Key, str] = {}  # voie -> couleur de sa courbe
        self._last_dir = str(EXAMPLES_DIR if EXAMPLES_DIR.is_dir() else Path.home())
        self.busy = False  # un traitement long tourne en arrière-plan
        self._action_buttons: List[ttk.Button] = []

        root.title("{}  (v{})".format(APP_TITLE, __version__))
        # Taille adaptée à l'écran (portable 1366×768 compris), sans jamais le dépasser
        width = min(1440, root.winfo_screenwidth() - 40)
        height = min(900, root.winfo_screenheight() - 90)
        root.geometry("{}x{}+{}+{}".format(width, height, max(0, (root.winfo_screenwidth() - width) // 2), 20))
        root.minsize(min(1000, width), min(600, height))
        root.report_callback_exception = self._on_unexpected_error
        self.fonts = apply_theme(root)
        self.check_images = CheckImages(root)

        self._build_header()
        self._build_statusbar()
        body = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        body.add(self._build_sidebar(body), weight=0)
        body.add(self._build_plot(body), weight=1)
        self._update_empty_state()
        self._set_status("Prêt. Ouvrez un ou plusieurs fichiers de mesure.")

    # ================================================================ construction

    def _build_header(self) -> None:
        bar = tk.Frame(self.root, background=C["card"])
        bar.pack(fill=tk.X)
        inner = ttk.Frame(bar, style="Card.TFrame", padding=(16, 10))
        inner.pack(fill=tk.X)
        separator(self.root)

        brand = ttk.Frame(inner, style="Card.TFrame")
        brand.pack(side=tk.LEFT)
        logo = tk.Canvas(brand, width=28, height=28, background=C["card"], highlightthickness=0)
        logo.create_rectangle(1, 1, 27, 27, fill=C["primary"], outline=C["primary"])
        logo.create_line(6, 18, 11, 18, 14, 9, 17, 20, 20, 13, 23, 13, fill=C["primary_fg"], width=2)
        logo.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(brand, text="CleanTrace", style="Brand.TLabel").pack(side=tk.LEFT)
        ttk.Label(brand, text="v" + __version__, style="Badge.TLabel").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(brand, text="Mesures de bancs d'essai", style="Muted.Card.TLabel").pack(side=tk.LEFT, padx=(12, 0))

        actions = ttk.Frame(inner, style="Card.TFrame")
        actions.pack(side=tk.RIGHT)
        ttk.Button(actions, text="Aide", style="Ghost.TButton",
                   command=lambda: HelpWindow.open(self.root)).pack(side=tk.LEFT, padx=(0, 6))
        for text, command, style in (
            ("Réinitialiser", self.reset_all, "TButton"),
            ("Exporter en CSV…", self.export_csv, "TButton"),
            ("Ouvrir des fichiers…", self.open_files, "Primary.TButton"),
        ):
            button = ttk.Button(actions, text=text, command=command, style=style)
            button.pack(side=tk.LEFT, padx=(0, 6))
            self._action_buttons.append(button)

    def _build_sidebar(self, parent) -> ttk.Frame:
        scroll = self.sidebar = ScrollFrame(parent, width=410)
        side = scroll.inner

        # --- US-02 : voies de mesure
        outer, box = card(side, "Voies de mesure", "Cochez les voies à afficher, nettoyer et exporter.")
        outer.pack(fill=tk.X, padx=(0, 12), pady=(0, 12))
        row = ttk.Frame(box, style="Card.TFrame")
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(row, text="Tout cocher", style="Small.TButton",
                   command=lambda: self.select_all(True)).pack(side=tk.LEFT)
        ttk.Button(row, text="Tout décocher", style="Small.TButton",
                   command=lambda: self.select_all(False)).pack(side=tk.LEFT, padx=(6, 0))
        tree_frame = ttk.Frame(box, style="Card.TFrame")
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_frame, selectmode="none", height=11, show="tree")
        self.tree.column("#0", width=350, stretch=True)
        self.tree.tag_configure("file", font=self.fonts.strong)
        self.tree.tag_configure("off", foreground=C["muted_fg"])
        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.lbl_reference = ttk.Label(box, text="", style="Muted.Card.TLabel", wraplength=350, justify=tk.LEFT)
        self.lbl_reference.pack(anchor=tk.W, pady=(8, 0))

        # --- US-03 : nettoyage automatique
        def help_action(section):
            return lambda header: ttk.Button(header, text="?", style="Icon.TButton", width=2,
                                             command=lambda: HelpWindow.open(self.root, section)).pack(side=tk.RIGHT)

        outer, clean = card(side, "Nettoyage", "Pics de saturation et bruit de repos des voies cochées.",
                            actions=help_action("Nettoyage"))
        outer.pack(fill=tk.X, padx=(0, 12), pady=(0, 12))
        self.chk_noise = tk.BooleanVar(value=True)
        self.chk_peaks = tk.BooleanVar(value=True)
        ttk.Checkbutton(clean, text="Supprimer les pics de saturation", variable=self.chk_peaks,
                        style="Card.TCheckbutton").pack(anchor=tk.W)
        ttk.Checkbutton(clean, text="Forcer à 0 le bruit de repos", variable=self.chk_noise,
                        style="Card.TCheckbutton").pack(anchor=tk.W)
        row = ttk.Frame(clean, style="Card.TFrame")
        row.pack(fill=tk.X, pady=(10, 0))
        for text, command, style in (
            ("Nettoyer…", self.clean_selected, "Primary.TButton"),
            ("Annuler le nettoyage", self.restore_selected, "TButton"),
        ):
            button = ttk.Button(row, text=text, command=command, style=style)
            button.pack(side=tk.LEFT, padx=(0, 6))
            self._action_buttons.append(button)

        # --- Superposition de fichiers : base de temps et grille d'export
        outer, base = card(side, "Base de temps", "Comment superposer plusieurs fichiers.",
                           actions=help_action("Base de temps"))
        outer.pack(fill=tk.X, padx=(0, 12), pady=(0, 12))
        self.time_mode_var = tk.StringVar(value=TIME_MODES["real"])
        mode_box = ttk.Combobox(base, textvariable=self.time_mode_var, values=list(TIME_MODES.values()),
                                state="readonly")
        mode_box.pack(fill=tk.X)
        mode_box.bind("<<ComboboxSelected>>", self._on_time_mode)
        self.lbl_window = ttk.Label(base, text="", style="Muted.Card.TLabel", wraplength=350, justify=tk.LEFT)
        self.lbl_window.pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(base, text="Grille d'export", style="Strong.Card.TLabel").pack(anchor=tk.W, pady=(10, 4))
        self.export_step_var = tk.StringVar(value=EXPORT_STEPS[None])
        step_box = ttk.Combobox(base, textvariable=self.export_step_var, values=list(EXPORT_STEPS.values()),
                                state="readonly")
        step_box.pack(fill=tk.X)
        step_box.bind("<<ComboboxSelected>>", self._on_export_step)

        # --- US-04 : décalage temporel des courbes climatiques
        outer, shift = card(side, "Enceinte climatique",
                            "Décale les courbes °C / %HR si l'enceinte réagit avec retard.")
        outer.pack(fill=tk.X, padx=(0, 12), pady=(0, 12))
        row = ttk.Frame(shift, style="Card.TFrame")
        row.pack(fill=tk.X)
        self.offset_var = tk.DoubleVar(value=0.0)
        self.offset_scale = ttk.Scale(row, from_=-30, to=30, orient=tk.HORIZONTAL,
                                      variable=self.offset_var, command=self._on_offset)
        self.offset_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_offset = ttk.Label(row, text="0,0 min", style="Card.TLabel", width=9, anchor=tk.E)
        self.lbl_offset.pack(side=tk.LEFT, padx=(8, 6))
        ttk.Button(row, text="0", style="Icon.TButton", width=2,
                   command=lambda: self._set_offset(0.0)).pack(side=tk.LEFT)

        # --- US-05 : correction au clic
        outer, edit = card(side, "Correction au clic",
                           "Clic gauche sur un point abîmé : il est interpolé avec ses voisins.")
        outer.pack(fill=tk.X, padx=(0, 12), pady=(0, 4))
        self.chk_click_edit = tk.BooleanVar(value=True)
        ttk.Checkbutton(edit, text="Activée (sauf pendant zoom / déplacement)", variable=self.chk_click_edit,
                        style="Card.TCheckbutton").pack(anchor=tk.W)
        return scroll

    def _build_plot(self, parent) -> tk.Frame:
        outer = bordered(parent)
        frame = ttk.Frame(outer, style="Card.TFrame", padding=(8, 8, 8, 4))
        frame.pack(fill=tk.BOTH, expand=True)
        self.figure = Figure(figsize=(10, 6), dpi=100, facecolor=C["card"])
        self.canvas = FigureCanvasTkAgg(self.figure, master=frame)
        toolbar = NavigationToolbar2Tk(self.canvas, frame, pack_toolbar=False)
        toolbar.update()
        _flatten_toolbar(toolbar)
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        line = tk.Frame(frame, height=1, background=C["border"])
        line.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 2))
        widget = self.canvas.get_tk_widget()
        widget.configure(background=C["card"], highlightthickness=0)
        widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.plot = PlotManager(self.figure)
        self.corrector = ClickCorrector(
            self.figure, self._on_point_clicked,
            is_enabled=lambda: self.chk_click_edit.get() and not self.busy,
        )

        # État vide : invitation à ouvrir des fichiers
        self.empty_panel, empty = card(frame, padding=28)
        icon = tk.Canvas(empty, width=56, height=56, background=C["card"], highlightthickness=0)
        icon.create_oval(2, 2, 54, 54, fill=C["muted"], outline=C["muted"])
        icon.create_line(15, 34, 22, 34, 27, 20, 32, 38, 37, 27, 42, 27, fill=C["fg_soft"], width=2.5,
                         capstyle=tk.ROUND, joinstyle=tk.ROUND)
        icon.pack(pady=(0, 12))
        ttk.Label(empty, text="Aucun fichier ouvert", style="Title.Card.TLabel").pack()
        ttk.Label(empty, text="Ouvrez un export Graphtec, nanodac… (CSV, TXT, DAT).\n"
                              "Le format est détecté automatiquement.",
                  style="Muted.Card.TLabel", justify=tk.CENTER).pack(pady=(4, 16))
        buttons = ttk.Frame(empty, style="Card.TFrame")
        buttons.pack()
        ttk.Button(buttons, text="Ouvrir des fichiers…", style="Primary.TButton",
                   command=self.open_files).pack(side=tk.LEFT, padx=(0, 6))
        if all((EXAMPLES_DIR / f).is_file() for f in EXAMPLE_FILES):
            ttk.Button(buttons, text="Essayer avec les exemples",
                       command=lambda: self.open_files([str(EXAMPLES_DIR / f) for f in EXAMPLE_FILES])
                       ).pack(side=tk.LEFT)

        # Indicateur de chargement, affiché par-dessus le graphique
        self.busy_panel, busy = card(frame, padding=22)
        self.busy_text = tk.StringVar()
        ttk.Label(busy, text="Traitement en cours…", style="Title.Card.TLabel").pack(anchor=tk.W)
        ttk.Label(busy, textvariable=self.busy_text, style="Muted.Card.TLabel", wraplength=380,
                  justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 14))
        self.busy_bar = ttk.Progressbar(busy, mode="indeterminate", length=380)
        self.busy_bar.pack(fill=tk.X)
        return outer

    def _build_statusbar(self) -> None:
        self.status = tk.StringVar()
        bar = ttk.Frame(self.root, padding=(16, 5))
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        separator(self.root).pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bar, textvariable=self.status, style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Label(bar, text="CleanTrace v" + __version__, style="Muted.TLabel").pack(side=tk.RIGHT)

    # ==================================================================== actions

    def open_files(self, paths: List[str] = None) -> None:
        """US-01 : import (boîte de dialogue, ou liste de chemins pour les scripts)."""
        if paths is None:
            paths = filedialog.askopenfilenames(
                parent=self.root, title="Ouvrir des fichiers de mesure",
                initialdir=self._last_dir, filetypes=FILE_TYPES,
            )
        if not paths:
            return
        self._last_dir = str(Path(paths[0]).parent)
        self.run_in_background(
            "Chargement de {} fichier(s)…".format(len(paths)),
            lambda progress: self.session.read_files(paths, progress),
            self._on_files_read,
        )

    def _on_files_read(self, result) -> None:
        loaded, errors = result
        self.session.add_measurements(loaded)
        for m in loaded:
            for ch in m.channels:
                self._checked[(m.name, ch.label)] = True
        self._rebuild_tree()
        self._update_offset_range()
        self.redraw()
        if loaded:
            self._set_status("{} fichier(s) chargé(s).".format(len(loaded)))
            notes = ["• {} : {}".format(m.name, " ".join(m.warnings)) for m in loaded if m.warnings]
            notes += ["• " + m.align_note for m in self.session.measurements.values() if m.align_note]
            if notes:
                messagebox.showwarning("Import", "Fichiers chargés avec remarques :\n\n" + "\n".join(notes),
                                       parent=self.root)
        for path, message in errors:
            self._report_unreadable(path, message)

    def _report_unreadable(self, path: Path, message: str) -> None:
        """Fichier refusé : explication + extrait à envoyer pour adapter le logiciel."""
        if not messagebox.askyesno(
            "Fichier non conforme",
            message + "\n\nEnregistrer un extrait de ce fichier (début et fin, quelques Ko) "
            "pour l'envoyer au développeur ?",
            icon=messagebox.ERROR, parent=self.root,
        ):
            return
        target = filedialog.asksaveasfilename(
            parent=self.root, title="Enregistrer l'extrait",
            initialfile="{}_extrait.txt".format(path.stem), defaultextension=".txt",
            filetypes=[("Texte", "*.txt")],
        )
        if target:
            write_extract(path, target)
            messagebox.showinfo("Extrait enregistré", "Extrait enregistré :\n{}".format(target), parent=self.root)

    def select_all(self, state: bool) -> None:
        if self.busy:
            return
        for key in self._checked:
            self._checked[key] = state
        self._refresh_checkmarks()
        self.redraw()

    def reset_all(self) -> None:
        if self.busy or not self.session.measurements:
            return
        if not messagebox.askyesno("Réinitialiser", "Décharger tous les fichiers ?\n"
                                   "Les nettoyages et corrections non exportés seront perdus.",
                                   parent=self.root):
            return
        self.session.clear()
        self._checked.clear()
        self._set_offset(0.0)
        self._rebuild_tree()
        self.redraw()
        self._set_status("Tous les fichiers ont été déchargés.")

    def clean_selected(self) -> None:
        keys = self.selected_keys()
        if not keys:
            messagebox.showinfo("Nettoyage", "Cochez au moins une voie.", parent=self.root)
            return
        if self.busy:
            return
        return CleaningDialog(self, keys)

    def apply_cleaning(self, keys, options: CleaningOptions, thresholds=None) -> None:
        """Applique le nettoyage réglé dans la fenêtre « Nettoyer… » (en arrière-plan)."""

        def done(report):
            self.redraw()
            message = "Nettoyage de {} voie(s) : {} pic(s) supprimé(s), {} point(s) de bruit forcés à 0.".format(
                len(keys), report.peak_points, report.noise_points)
            if options.remove_noise and report.noise_points == 0:
                message += " Aucun repos sous le seuil : voies qui ne reviennent pas à 0, ou seuil trop bas."
            self._set_status(message)

        self.run_in_background(
            "Nettoyage de {} voie(s)…".format(len(keys)),
            lambda progress: self.session.apply_cleaning(keys, options, thresholds), done,
        )

    def restore_selected(self) -> None:
        keys = self.selected_keys()
        if keys and not self.busy:
            self.session.restore_raw(keys)
            self.redraw()
            self._set_status("Données brutes restaurées pour {} voie(s).".format(len(keys)))

    def export_csv(self) -> None:
        """US-06 : export des voies cochées."""
        keys = self.selected_keys()
        if not keys:
            messagebox.showinfo("Export", "Cochez au moins une voie à exporter.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Exporter les données nettoyées",
            defaultextension=".csv", initialfile="cleantrace_export.csv",
            filetypes=[("CSV (séparateur ;)", "*.csv")],
        )
        if not path:
            return

        def done(df):
            messagebox.showinfo(
                "Export terminé",
                "{} lignes × {} voies exportées dans :\n{}".format(len(df), len(keys), path),
                parent=self.root,
            )
            self._set_status("Export : {}".format(path))

        self.run_in_background(
            "Export de {} voie(s) vers {}…".format(len(keys), Path(path).name),
            lambda progress: self.session.export_csv(path, keys), done,
            error_title="Export impossible",
        )

    # ======================================================= traitements longs

    def run_in_background(self, message: str, work, on_done, error_title: str = "Erreur") -> None:
        """Exécute ``work(progress)`` dans un thread, avec l'indicateur de chargement.

        Tkinter n'est pas thread-safe : le thread ne touche jamais à l'interface, il
        envoie ses messages dans une file que la boucle Tkinter relève toutes les 100 ms.
        """
        if self.busy:
            return
        self._set_busy(True, message)
        messages: "queue.Queue" = queue.Queue()

        def target():
            try:
                result = work(lambda text: messages.put(("progress", text)))
                messages.put(("done", result))
            except Exception as exc:  # remonté à l'utilisateur dans la boucle Tkinter
                messages.put(("error", exc, traceback.format_exc()))

        threading.Thread(target=target, daemon=True).start()
        self.root.after(100, self._poll_background, messages, on_done, error_title)

    def _poll_background(self, messages, on_done, error_title) -> None:
        try:
            while True:
                item = messages.get_nowait()
                if item[0] == "progress":
                    self.busy_text.set(item[1])
                    self._set_status(item[1])
                    continue
                self._set_busy(False)
                if item[0] == "done":
                    on_done(item[1])
                else:
                    print(item[2])
                    messagebox.showerror(error_title, str(item[1]), parent=self.root)
                return
        except queue.Empty:
            self.root.after(100, self._poll_background, messages, on_done, error_title)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        for button in self._action_buttons:
            button.config(state=state)
        if busy:
            self.busy_text.set(message)
            self._set_status(message)
            self.empty_panel.place_forget()
            self.busy_panel.place(relx=0.5, rely=0.45, anchor=tk.CENTER)
            self.busy_panel.lift()
            self.busy_bar.start(12)
            self.root.config(cursor="watch")
        else:
            self.busy_bar.stop()
            self.busy_panel.place_forget()
            self.root.config(cursor="")
            self._update_empty_state()

    def _update_empty_state(self) -> None:
        if self.session.measurements or self.busy:
            self.empty_panel.place_forget()
        else:
            self.empty_panel.place(relx=0.5, rely=0.45, anchor=tk.CENTER)
            self.empty_panel.lift()

    # ================================================================== affichage

    def selected_keys(self) -> List[Key]:
        return [key for key in self.session.all_keys() if self._checked.get(key)]

    def redraw(self) -> None:
        keys = self.selected_keys()
        series = self.session.series(keys)
        self._gid_key = {s.gid: key for s, key in zip(series, keys)}
        self.plot.time_offset_min = self.session.time_offset_min
        self.plot.percent_axis = self.session.percent_axis
        self.plot.draw(series)
        self._key_color = {self._gid_key[gid]: color for gid, color in self.plot.colors.items()}
        self._refresh_checkmarks()
        self._update_empty_state()

    def _rebuild_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._item_key.clear()
        self._file_item.clear()
        ref = self.session.reference
        for m in self.session.measurements.values():
            file_id = self.tree.insert("", tk.END, text=" " + m.name, open=True, tags=("file",))
            self._file_item[m.name] = file_id
            for ch in m.channels:
                item = self.tree.insert(file_id, tk.END, text=" " + ch.label)
                self._item_key[item] = (m.name, ch.label)
        self._refresh_checkmarks()
        lines = ["{}{} · {} · {}".format("★ " if m is ref and len(self.session.measurements) > 1 else "",
                                          m.name, m.source, m.period_label)
                 for m in self.session.measurements.values()]
        if len(lines) > 1:
            lines.append("★ référence de temps")
        self.lbl_reference.config(text="\n".join(lines))
        self._update_window_label()

    def _update_window_label(self) -> None:
        s = self.session
        text = ""
        if s.time_mode == "common" and len(s.measurements) > 1:
            if s.window is None:
                text = ("Aucune période commune entre ces fichiers : affichage complet. "
                        "Essayez « Débuts à 0 » ou « Durée étirée ».")
            else:
                duration = s.window[1] - s.window[0]
                start = s.window_start
                text = "Période commune : {} → {} ({})".format(
                    start.strftime("%d/%m %H:%M:%S") if start is not None else format_hms(s.window[0]),
                    (start + pd.Timedelta(minutes=duration)).strftime("%d/%m %H:%M:%S")
                    if start is not None else format_hms(s.window[1]),
                    format_hms(duration))
        elif s.time_mode == "stretch":
            text = "Chaque fichier va de 0 à 100 % de sa propre durée (le temps est déformé)."
        elif s.time_mode == "zero":
            text = "Chaque fichier démarre à 0 (heures réelles ignorées)."
        self.lbl_window.config(text=text)

    def _on_time_mode(self, _event=None) -> None:
        if self.busy:
            return
        label = self.time_mode_var.get()
        mode = next(k for k, v in TIME_MODES.items() if v == label)
        self.session.set_time_mode(mode)
        # Le décalage de l'enceinte (en minutes) n'a pas de sens sur un axe en %
        self.offset_scale.state(["disabled"] if self.session.percent_axis else ["!disabled"])
        self._update_window_label()
        self.redraw()
        self._set_status("Base de temps : {}.".format(label))

    def _on_export_step(self, _event=None) -> None:
        label = self.export_step_var.get()
        self.session.export_step_s = next(k for k, v in EXPORT_STEPS.items() if v == label)
        self._set_status("Grille d'export : {}.".format(label))

    def _refresh_checkmarks(self) -> None:
        """Case cochée / décochée + pastille de la couleur de la courbe (= légende)."""
        for item, key in self._item_key.items():
            on = bool(self._checked.get(key))
            image = self.check_images.get("on" if on else "off", self._key_color.get(key) if on else None)
            self.tree.item(item, image=image, tags=() if on else ("off",))
        for name, file_id in self._file_item.items():
            states = [self._checked.get(self._item_key[c]) for c in self.tree.get_children(file_id)]
            state = "on" if all(states) else "off" if not any(states) else "partial"
            self.tree.item(file_id, image=self.check_images.get(state), tags=("file",))

    def _on_tree_click(self, event):
        if self.busy:
            return "break"
        item = self.tree.identify_row(event.y)
        if not item or "indicator" in self.tree.identify_element(event.x, event.y):
            return None  # clic sur la flèche d'ouverture : comportement normal
        if item in self._item_key:
            key = self._item_key[item]
            self._checked[key] = not self._checked.get(key)
        else:  # fichier : coche / décoche toutes ses voies
            children = [self._item_key[c] for c in self.tree.get_children(item)]
            new_state = not all(self._checked.get(k) for k in children)
            for k in children:
                self._checked[k] = new_state
        self._refresh_checkmarks()
        self.redraw()
        return "break"

    def _on_offset(self, _value=None) -> None:
        value = round(float(self.offset_var.get()) * 2) / 2  # pas de 0,5 min
        self.offset_var.set(value)
        self.lbl_offset.config(text="{:+.1f} min".format(value).replace(".", ",") if value else "0,0 min")
        self.session.time_offset_min = value
        self.plot.set_time_offset(value)

    def _set_offset(self, value: float) -> None:
        self.offset_var.set(value)
        self._on_offset()

    def _update_offset_range(self) -> None:
        span = max(10.0, round(self.session.total_duration_min * 0.25))
        self.offset_scale.config(from_=-span, to=span)

    def _on_point_clicked(self, gid: str, plotted_index: int) -> None:
        """US-05 : interpolation du point cliqué, sur les données complètes."""
        key = self._gid_key.get(gid)
        if key is None:
            return
        index = self.plot.original_index(gid, plotted_index)
        value = self.session.correct_point(key, index)
        self.plot.update_data(gid, self.session.measurements[key[0]].data[key[1]].to_numpy())
        self._set_status("Point corrigé : {} [{}], indice {} → {:.6g}".format(key[1], key[0], index, value))

    def _set_status(self, text: str) -> None:
        self.status.set(text)

    def _on_unexpected_error(self, exc_type, exc, tb) -> None:
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        print(details)
        messagebox.showerror("Erreur inattendue", "{}\n\n(détails dans la console)".format(exc), parent=self.root)


def _flatten_toolbar(toolbar) -> None:
    """Barre de zoom Matplotlib aux couleurs du thème (fond blanc, sans relief)."""
    for widget in [toolbar] + list(toolbar.winfo_children()):
        for option, value in (("background", C["card"]), ("highlightthickness", 0),
                              ("activebackground", C["muted"]), ("relief", tk.FLAT), ("bd", 0),
                              ("foreground", C["muted_fg"])):
            try:
                widget.configure(**{option: value})
            except tk.TclError:
                pass


def _enable_windows_dpi_awareness() -> None:
    """Évite un affichage flou sur les écrans haute résolution sous Windows."""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def run() -> None:
    """Point d'entrée : crée la fenêtre et lance la boucle Tkinter."""
    _enable_windows_dpi_awareness()
    root = tk.Tk()
    CleanTraceApp(root)
    root.mainloop()
