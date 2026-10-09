"""Interface graphique Tkinter de CleanTrace.

Disposition :
    ┌ barre d'outils : Ouvrir · Exporter · Réinitialiser ─────────────────────────┐
    │ panneau gauche                      │ graphique Matplotlib + barre de zoom   │
    │  - voies par fichier (cases à cocher)│                                        │
    │  - nettoyage automatique            │                                        │
    │  - décalage température / humidité  │                                        │
    │  - correction au clic               │                                        │
    └ barre d'état ───────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import queue
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from . import __version__
from .cleaning import CleaningOptions
from .editing import ClickCorrector
from .export import Key
from .loader import write_extract
from .plotting import PlotManager
from .session import Session

APP_TITLE = "CleanTrace — MultiPlotter pour bancs d'essai"
CHECKED, UNCHECKED, PARTIAL = "☑", "☐", "◩"
FILE_TYPES = [
    ("Fichiers de mesure", "*.csv *.txt *.dat *.CSV *.TXT *.DAT"),
    ("Tous les fichiers", "*.*"),
]
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "exemples"


class CleanTraceApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.session = Session()
        self._checked: Dict[Key, bool] = {}
        self._item_key: Dict[str, Key] = {}  # id Treeview -> voie
        self._file_item: Dict[str, str] = {}  # nom de fichier -> id Treeview
        self._gid_key: Dict[str, Key] = {}  # gid de courbe -> voie
        self._last_dir = str(EXAMPLES_DIR if EXAMPLES_DIR.is_dir() else Path.home())
        self.busy = False  # un traitement long tourne en arrière-plan
        self._action_buttons: List[ttk.Button] = []

        root.title(APP_TITLE)
        root.geometry("1400x860")
        root.minsize(1000, 640)
        root.report_callback_exception = self._on_unexpected_error

        self._build_toolbar()
        body = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        body.add(self._build_sidebar(body), weight=0)
        body.add(self._build_plot(body), weight=1)
        self._build_statusbar()
        self._set_status("Prêt. Ouvrez un ou plusieurs fichiers de mesure.")

    # ================================================================ construction

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(6, 6))
        bar.pack(fill=tk.X)
        for text, command, pad in (
            ("Ouvrir des fichiers…", self.open_files, 0),
            ("Exporter en CSV…", self.export_csv, 6),
            ("Réinitialiser", self.reset_all, 0),
        ):
            button = ttk.Button(bar, text=text, command=command)
            button.pack(side=tk.LEFT, padx=(0, pad))
            self._action_buttons.append(button)
        self.lbl_reference = ttk.Label(bar, text="", foreground="#555")
        self.lbl_reference.pack(side=tk.RIGHT)

    def _build_sidebar(self, parent) -> ttk.Frame:
        side = ttk.Frame(parent, padding=(0, 0, 6, 0), width=380)

        # --- US-02 : voies de mesure
        box = ttk.LabelFrame(side, text="Voies de mesure", padding=6)
        box.pack(fill=tk.BOTH, expand=True)
        btns = ttk.Frame(box)
        btns.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(btns, text="Tout sélectionner", command=lambda: self.select_all(True)).pack(side=tk.LEFT)
        ttk.Button(btns, text="Tout désélectionner", command=lambda: self.select_all(False)).pack(side=tk.LEFT, padx=4)

        tree_frame = ttk.Frame(box)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("info",), selectmode="none", height=14)
        self.tree.heading("#0", text="Fichier / voie", anchor=tk.W)
        self.tree.heading("info", text="Infos", anchor=tk.W)
        self.tree.column("#0", width=215, stretch=True)
        self.tree.column("info", width=150, stretch=False)
        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Button-1>", self._on_tree_click)

        # --- US-03 : nettoyage automatique
        clean = ttk.LabelFrame(side, text="Nettoyage automatique (voies cochées)", padding=6)
        clean.pack(fill=tk.X, pady=(6, 0))
        self.chk_noise = tk.BooleanVar(value=True)
        self.chk_peaks = tk.BooleanVar(value=True)
        ttk.Checkbutton(clean, text="Forcer à 0 le bruit de repos (< 10 mA, < 5 mV)",
                        variable=self.chk_noise).pack(anchor=tk.W)
        ttk.Checkbutton(clean, text="Supprimer les pics de saturation (> 98 % du max)",
                        variable=self.chk_peaks).pack(anchor=tk.W)
        row = ttk.Frame(clean)
        row.pack(fill=tk.X, pady=(4, 0))
        for text, command, pad in (
            ("Nettoyer", self.clean_selected, 0),
            ("Restaurer les données brutes", self.restore_selected, 4),
        ):
            button = ttk.Button(row, text=text, command=command)
            button.pack(side=tk.LEFT, padx=pad)
            self._action_buttons.append(button)

        # --- US-04 : décalage temporel des courbes climatiques
        shift = ttk.LabelFrame(side, text="Décalage enceinte climatique (min)", padding=6)
        shift.pack(fill=tk.X, pady=(6, 0))
        self.offset_var = tk.DoubleVar(value=0.0)
        self.offset_scale = tk.Scale(
            shift, from_=-30, to=30, resolution=0.5, orient=tk.HORIZONTAL,
            variable=self.offset_var, command=self._on_offset, showvalue=True,
        )
        self.offset_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(shift, text="0", width=3, command=lambda: self._set_offset(0.0)).pack(side=tk.LEFT, padx=(4, 0))

        # --- US-05 : correction au clic
        edit = ttk.LabelFrame(side, text="Correction manuelle", padding=6)
        edit.pack(fill=tk.X, pady=(6, 0))
        self.chk_click_edit = tk.BooleanVar(value=True)
        ttk.Checkbutton(edit, text="Corriger le point cliqué (clic gauche, interpolation)",
                        variable=self.chk_click_edit).pack(anchor=tk.W)
        ttk.Label(edit, text="Désactivée pendant le zoom / déplacement de la barre d'outils.",
                  foreground="#777").pack(anchor=tk.W)
        return side

    def _build_plot(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        self.figure = Figure(figsize=(10, 6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=frame)
        toolbar = NavigationToolbar2Tk(self.canvas, frame, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.plot = PlotManager(self.figure)
        self.corrector = ClickCorrector(
            self.figure, self._on_point_clicked,
            is_enabled=lambda: self.chk_click_edit.get() and not self.busy,
        )

        # Indicateur de chargement, affiché par-dessus le graphique
        self.busy_panel = ttk.Frame(frame, padding=(28, 18), relief=tk.RIDGE, borderwidth=2)
        self.busy_text = tk.StringVar()
        ttk.Label(self.busy_panel, text="Traitement en cours…", font=("TkDefaultFont", 11, "bold")).pack()
        ttk.Label(self.busy_panel, textvariable=self.busy_text, wraplength=420, justify=tk.CENTER).pack(pady=(6, 10))
        self.busy_bar = ttk.Progressbar(self.busy_panel, mode="indeterminate", length=320)
        self.busy_bar.pack()
        return frame

    def _build_statusbar(self) -> None:
        self.status = tk.StringVar()
        bar = ttk.Frame(self.root, padding=(8, 2))
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Label(bar, textvariable=self.status).pack(side=tk.LEFT)
        ttk.Label(bar, text="v" + __version__, foreground="#999").pack(side=tk.RIGHT)

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
        if not (self.chk_noise.get() or self.chk_peaks.get()):
            messagebox.showinfo("Nettoyage", "Activez au moins un traitement.", parent=self.root)
            return
        options = CleaningOptions(remove_noise=self.chk_noise.get(), remove_peaks=self.chk_peaks.get())

        def done(report):
            self.redraw()
            self._set_status(
                "Nettoyage de {} voie(s) : {} pic(s) supprimé(s), {} point(s) de bruit forcés à 0.".format(
                    len(keys), report.peak_points, report.noise_points)
            )

        self.run_in_background(
            "Nettoyage de {} voie(s)…".format(len(keys)),
            lambda progress: self.session.apply_cleaning(keys, options), done,
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
            self.busy_panel.place(relx=0.5, rely=0.45, anchor=tk.CENTER)
            self.busy_panel.lift()
            self.busy_bar.start(12)
            self.root.config(cursor="watch")
        else:
            self.busy_bar.stop()
            self.busy_panel.place_forget()
            self.root.config(cursor="")

    # ================================================================== affichage

    def selected_keys(self) -> List[Key]:
        return [key for key in self.session.all_keys() if self._checked.get(key)]

    def redraw(self) -> None:
        keys = self.selected_keys()
        series = self.session.series(keys)
        self._gid_key = {s.gid: key for s, key in zip(series, keys)}
        self.plot.time_offset_min = self.session.time_offset_min
        self.plot.draw(series)

    def _rebuild_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._item_key.clear()
        self._file_item.clear()
        ref = self.session.reference
        for m in self.session.measurements.values():
            info = "{} · {}".format(m.source, m.period_label)
            file_id = self.tree.insert("", tk.END, text=m.name, values=(info,), open=True)
            self._file_item[m.name] = file_id
            for ch in m.channels:
                item = self.tree.insert(file_id, tk.END, text=ch.label, values=(ch.quantity,))
                self._item_key[item] = (m.name, ch.label)
        self._refresh_checkmarks()
        if ref is not None:
            self.lbl_reference.config(
                text="Référence temps : {} ({}, {})".format(ref.name, ref.source, ref.period_label))
        else:
            self.lbl_reference.config(text="")

    def _refresh_checkmarks(self) -> None:
        for item, key in self._item_key.items():
            mark = CHECKED if self._checked.get(key) else UNCHECKED
            self.tree.item(item, text="{}  {}".format(mark, key[1]))
        for name, file_id in self._file_item.items():
            states = [self._checked.get(self._item_key[c]) for c in self.tree.get_children(file_id)]
            mark = CHECKED if all(states) else UNCHECKED if not any(states) else PARTIAL
            self.tree.item(file_id, text="{}  {}".format(mark, name))

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
        self.session.time_offset_min = float(self.offset_var.get())
        self.plot.set_time_offset(self.session.time_offset_min)

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
