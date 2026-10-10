"""Fenêtre « Nettoyer… » : réglages par voie et aperçu avant d'appliquer (US-03).

La fenêtre s'ouvre immédiatement ; les suggestions et l'aperçu (qui parcourent toutes
les mesures) sont calculés en arrière-plan, avec une barre de progression : la fenêtre
ne se fige jamais, même sur des fichiers de plusieurs millions de points.
"""
from __future__ import annotations

import queue
import threading
import traceback
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List, Optional

from .cleaning import CleaningOptions
from .export import Key
from .help import HelpWindow
from .theme import C, card
from .i18n import _

PEAK_MODES = {
    "all": "Tous les pics étroits (recommandé)",
    "saturation": "Seulement la saturation, au-delà de",
}
NOISE_MODES = {
    "smooth": "Lisser (garde le niveau mesuré, recommandé)",
    "zero": "Forcer à 0 sous le seuil (phases de repos)",
}


def _fmt(value: Optional[float]) -> str:
    return "" if value is None else _("{:g}").format(value).replace(".", ",")


def _parse(text: str, allow_negative: bool = False) -> Optional[float]:
    """« 0,02 » / « 0.02 » -> 0.02 ; vide -> None. ValueError sinon."""
    text = text.strip().replace(",", ".")
    if not text:
        return None
    value = float(text)
    if value < 0 and not allow_negative:
        raise ValueError(text)
    return value or None


class CleaningDialog(tk.Toplevel):
    """Une ligne par voie cochée : décalage de zéro, seuil de bruit, suggestions, aperçu."""

    def __init__(self, app, keys: List[Key]):
        super().__init__(app.root)
        self.app = app
        self.session = app.session
        self.keys = keys
        self._job = 0  # numéro du calcul en cours (les résultats périmés sont ignorés)
        self.title(_("Nettoyage de {} voie(s)").format(len(keys)))
        self.transient(app.root)
        self.resizable(True, True)
        self.configure(background=C["background"])

        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=_("Nettoyage"), font=app.fonts.brand).pack(anchor=tk.W)
        ttk.Label(body, text=_("Réglez les traitements, vérifiez l'aperçu, puis appliquez. Tout est noté "
                             "dans le journal des traitements."), style="Muted.TLabel").pack(anchor=tk.W, pady=(0, 12))

        # --- traitements et réglages communs
        outer, box = card(body, _("Traitements"), _("Appliqués dans cet ordre aux voies ci-dessous. Tout est réversible."))
        outer.pack(fill=tk.X)
        top = ttk.Frame(box, style="Card.TFrame")  # grille (card() place son titre avec pack)
        top.pack(fill=tk.X)
        ttk.Checkbutton(top, text=_("Supprimer les pics parasites"), variable=app.chk_peaks,
                        style="Card.TCheckbutton", command=self._changed).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(top, text=_("larges de"), style="Card.TLabel").grid(row=0, column=1, padx=(12, 4))
        self.width = tk.StringVar(value="5")
        ttk.Spinbox(top, from_=1, to=50, increment=1, width=4, textvariable=self.width).grid(row=0, column=2)
        ttk.Label(top, text=_("points au plus"), style="Card.TLabel").grid(row=0, column=3, padx=4, sticky=tk.W)
        self.peak_mode = tk.StringVar(value=_(PEAK_MODES["all"]))
        mode = ttk.Combobox(top, textvariable=self.peak_mode, values=[_(v) for v in PEAK_MODES.values()],
                            state="readonly", width=44)
        mode.grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=(26, 0), pady=(4, 0))
        mode.bind("<<ComboboxSelected>>", lambda _e: self._changed())
        self.saturation = tk.StringVar(value="98")
        self.saturation_box = ttk.Spinbox(top, from_=50, to=100, increment=1, width=4,
                                          textvariable=self.saturation)
        self.saturation_box.grid(row=1, column=2, pady=(4, 0))
        ttk.Label(top, text=_("% du max"), style="Card.TLabel").grid(row=1, column=3, padx=4, pady=(4, 0), sticky=tk.W)

        ttk.Checkbutton(top, text=_("Réduire le bruit"), variable=app.chk_noise, style="Card.TCheckbutton",
                        command=self._changed).grid(row=2, column=0, sticky=tk.W, pady=(10, 0))
        self.noise_mode = tk.StringVar(value=_(NOISE_MODES[app.noise_mode.get()]))
        noise = ttk.Combobox(top, textvariable=self.noise_mode, values=[_(v) for v in NOISE_MODES.values()],
                             state="readonly", width=44)
        noise.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=(26, 0), pady=(4, 0))
        noise.bind("<<ComboboxSelected>>", lambda _e: self._changed())
        ttk.Label(top, text=_("lissage sur"), style="Card.TLabel").grid(row=2, column=1, padx=(12, 4), pady=(10, 0))
        self.smooth_window = tk.StringVar(value="11")
        self.smooth_box = ttk.Spinbox(top, from_=3, to=201, increment=2, width=4, textvariable=self.smooth_window)
        self.smooth_box.grid(row=2, column=2, pady=(10, 0))
        ttk.Label(top, text=_("points"), style="Card.TLabel").grid(row=2, column=3, padx=4, pady=(10, 0), sticky=tk.W)

        ttk.Checkbutton(top, text=_("Corriger le décalage de zéro (option : soustrait le niveau de repos ≠ 0)"),
                        variable=app.chk_offset, style="Card.TCheckbutton", command=self._changed).grid(
            row=4, column=0, columnspan=6, sticky=tk.W, pady=(10, 0))

        # --- tableau des voies
        outer, table_box = card(body, _("Voies cochées"),
                                _("Décalage et seuil : utilisés seulement si l'option correspondante est choisie. "
                                  "Champ vide = pas de correction."))
        outer.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        canvas = tk.Canvas(table_box, highlightthickness=0, height=min(40 + 30 * len(keys), 400),
                           background=C["card"])
        scroll = ttk.Scrollbar(table_box, orient=tk.VERTICAL, command=canvas.yview)
        table = ttk.Frame(canvas, style="Card.TFrame")
        table.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=table, anchor=tk.NW)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        headers = [_("VOIE"), _("MIN … MAX"), _("DÉCALAGE 0"), _("SEUIL (MISE À 0)"), _("SUGGESTION"),
                   _("PICS"), _("BRUIT")]
        for col, text in enumerate(headers):
            ttk.Label(table, text=text, style="Muted.Card.TLabel").grid(
                row=0, column=col, sticky=tk.E if col >= 5 else tk.W, padx=6, pady=(0, 6))

        several = len({k[0] for k in keys}) > 1
        self.offset_entries, self.threshold_entries = [], []
        self.offset_vars: Dict[Key, tk.StringVar] = {}
        self.threshold_vars: Dict[Key, tk.StringVar] = {}
        self.suggestions: Dict[Key, Optional[float]] = {}
        self.suggestion_labels: Dict[Key, ttk.Label] = {}
        self.result_labels: Dict[Key, tuple] = {}
        for row, key in enumerate(keys, start=1):
            m = self.session.measurements[key[0]]
            ch = m.channel(key[1])
            y = m.data[key[1]]
            name = "{} — {}".format(key[1], key[0]) if several else key[1]
            ttk.Label(table, text=name, style="Card.TLabel").grid(row=row, column=0, sticky=tk.W, padx=6, pady=2)
            ttk.Label(table, text=_("{:.4g} … {:.4g}").format(y.min(), y.max()), style="Muted.Card.TLabel").grid(
                row=row, column=1, sticky=tk.W, padx=6)
            for col, store, saved in ((2, self.offset_vars, self.session.offsets),
                                      (3, self.threshold_vars, self.session.noise_thresholds)):
                cell = ttk.Frame(table, style="Card.TFrame")
                cell.grid(row=row, column=col, sticky=tk.W, padx=6)
                var = tk.StringVar(value=_fmt(saved[key]) if key in saved else "…")  # « … » : en calcul
                entry = ttk.Entry(cell, textvariable=var, width=8)
                entry.pack(side=tk.LEFT)
                (self.offset_entries if col == 2 else self.threshold_entries).append(entry)
                ttk.Label(cell, text=ch.unit, style="Muted.Card.TLabel").pack(side=tk.LEFT, padx=(4, 0))
                store[key] = var
            hint = ttk.Label(table, text=_("calcul…"), style="Card.TLabel", foreground=C["ring"])
            hint.grid(row=row, column=4, sticky=tk.W, padx=6)
            self.suggestion_labels[key] = hint
            peaks = ttk.Label(table, text="…", width=7, anchor=tk.E, style="Card.TLabel")
            zeros = ttk.Label(table, text="…", width=14, anchor=tk.E, style="Card.TLabel")
            peaks.grid(row=row, column=5, sticky=tk.E, padx=6)
            zeros.grid(row=row, column=6, sticky=tk.E, padx=6)
            self.result_labels[key] = (peaks, zeros)

        # --- progression du calcul (dans la fenêtre)
        self.progress_text = tk.StringVar(value=_("Analyse des voies…"))
        status = ttk.Frame(body)
        status.pack(fill=tk.X, pady=(10, 0))
        self.progress = ttk.Progressbar(status, mode="determinate", length=200, maximum=100)
        self.progress.pack(side=tk.LEFT)
        ttk.Label(status, textvariable=self.progress_text, style="Muted.TLabel").pack(side=tk.LEFT, padx=(10, 0))

        # --- boutons
        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="?", style="Icon.TButton", width=2,
                   command=lambda: HelpWindow.open(self, _("Nettoyage"))).pack(side=tk.LEFT)
        self.btn_suggest = ttk.Button(buttons, text=_("Utiliser les suggestions"), command=self.use_suggestions)
        self.btn_suggest.pack(side=tk.LEFT, padx=6)
        self.btn_preview = ttk.Button(buttons, text=_("Aperçu"), command=self.preview)
        self.btn_preview.pack(side=tk.LEFT)
        self.btn_apply = ttk.Button(buttons, text=_("Appliquer"), style="Primary.TButton", command=self.apply)
        self.btn_apply.pack(side=tk.RIGHT)
        ttk.Button(buttons, text=_("Annuler"), command=self.destroy).pack(side=tk.RIGHT, padx=6)

        self.update_idletasks()
        canvas.configure(width=table.winfo_reqwidth())
        self._update_states()
        self._analyse()

    # ------------------------------------------------------------- calculs de fond

    @property
    def busy(self) -> bool:
        return self._running

    def _run(self, work, on_done) -> None:
        """Exécute ``work(progress)`` en arrière-plan ; la fenêtre reste utilisable."""
        self._job += 1
        job = self._job
        messages: "queue.Queue" = queue.Queue()
        self._set_running(True)

        def target():
            try:
                messages.put(("done", work(lambda text, fraction=None: messages.put(("progress", text, fraction)))))
            except Exception as exc:
                messages.put(("error", exc, traceback.format_exc()))

        def poll():
            if not self.winfo_exists() or job != self._job:
                return  # fenêtre fermée ou calcul remplacé par un plus récent
            try:
                while True:
                    item = messages.get_nowait()
                    if item[0] == "progress":
                        self.progress_text.set(item[1])
                        self.progress.configure(value=100 * (item[2] or 0))
                        continue
                    self._set_running(False)
                    if item[0] == "done":
                        on_done(item[1])
                    else:
                        self.app._report_error(_("Nettoyage"), item[1], item[2])
                    return
            except queue.Empty:
                self.after(80, poll)

        threading.Thread(target=target, daemon=True).start()
        self.after(80, poll)

    _running = False

    def _set_running(self, running: bool) -> None:
        self._running = running
        for button in (self.btn_suggest, self.btn_preview, self.btn_apply):
            button.state(["disabled"] if running else ["!disabled"])
        if not running:
            self.progress.configure(value=100)

    def _analyse(self) -> None:
        """Décalages et seuils proposés pour chaque voie, puis aperçu."""
        keys, session = self.keys, self.session

        def work(progress):
            out = {}
            for i, key in enumerate(keys):
                progress(_("Analyse — voie {}/{} : {}").format(i + 1, len(keys), key[1]), i / len(keys))
                out[key] = (session.zero_offset(key), session.noise_threshold(key),
                            session.suggest_noise_threshold(key), session.has_rest_phase(key))
            return out

        def done(result):
            for key, (offset, threshold, suggestion, rest) in result.items():
                if self.offset_vars[key].get() == "…":
                    self.offset_vars[key].set(_fmt(offset))
                if self.threshold_vars[key].get() == "…":
                    self.threshold_vars[key].set(_fmt(threshold))
                self.suggestions[key] = suggestion
                unit = self.session.measurements[key[0]].channel(key[1]).unit
                if suggestion:
                    text, color = "{} {}".format(_fmt(suggestion), unit), C["success"]
                else:
                    text, color = (_("non calculable") if rest else _("pas de repos à 0")), C["ring"]
                self.suggestion_labels[key].configure(text=text, foreground=color)
            self.preview()

        self._run(work, done)

    # ------------------------------------------------------------------- actions

    def _changed(self) -> None:
        self._update_states()
        self.preview()

    def _update_states(self) -> None:
        """Seuls les réglages utiles au traitement choisi sont modifiables."""
        def enable(widgets, on):
            for widget in widgets:
                widget.state(["!disabled"] if on else ["disabled"])

        enable([self.saturation_box], self.app.chk_peaks.get() and self.peak_mode.get() == _(PEAK_MODES["saturation"]))
        zero = self._noise_mode() == "zero"
        enable([self.smooth_box], self.app.chk_noise.get() and not zero)
        enable(self.threshold_entries, self.app.chk_noise.get() and zero)
        enable(self.offset_entries, self.app.chk_offset.get())

    def _noise_mode(self) -> str:
        return next((k for k, v in NOISE_MODES.items() if _(v) == self.noise_mode.get()), "smooth")

    def options(self) -> CleaningOptions:
        return CleaningOptions(
            zero_offset=self.app.chk_offset.get(),
            remove_noise=self.app.chk_noise.get(),
            remove_peaks=self.app.chk_peaks.get(),
            peak_mode="saturation" if self.peak_mode.get() == _(PEAK_MODES["saturation"]) else "all",
            saturation_ratio=float(self.saturation.get().replace(",", ".")) / 100.0,
            max_peak_width=int(self.width.get()),
            noise_mode=self._noise_mode(),
            smooth_window=int(self.smooth_window.get()),
        )

    def _values(self, store, allow_negative) -> Dict[Key, Optional[float]]:
        out = {}
        for key, var in store.items():
            if var.get() == "…":
                continue  # pas encore calculé : valeur par défaut de la session
            try:
                out[key] = _parse(var.get(), allow_negative)
            except ValueError:
                raise ValueError(_("Valeur invalide pour « {} » : {}").format(key[1], var.get()))
        return out

    def thresholds(self) -> Dict[Key, Optional[float]]:
        return self._values(self.threshold_vars, allow_negative=False)

    def offsets(self) -> Dict[Key, Optional[float]]:
        return self._values(self.offset_vars, allow_negative=True)

    def use_suggestions(self) -> None:
        for key, var in self.threshold_vars.items():
            if key in self.suggestions:
                var.set(_fmt(self.suggestions[key]))
        self.preview()

    def preview(self) -> None:
        if not hasattr(self, "btn_apply"):
            return  # fenêtre en cours de construction
        try:
            options, thresholds, offsets = self.options(), self.thresholds(), self.offsets()
        except ValueError as exc:
            messagebox.showerror(_("Réglage invalide"), str(exc), parent=self)
            return
        keys, session = self.keys, self.session

        def done(reports):
            for key, report in reports.items():
                peaks, zeros = self.result_labels[key]
                n = len(self.session.measurements[key[0]].data)
                peaks.config(text=str(report.peak_points) if options.remove_peaks else "–")
                share = report.noise_points / n if n else 0
                if not options.remove_noise:
                    text = "–"
                elif options.noise_mode == "smooth":
                    text = _("lissé") if report.smoothed_points else _("pas de bruit")
                else:
                    text = _("{} mis à 0 ({:.0%})").format(report.noise_points, share)
                zeros.config(text=text, foreground=C["destructive"] if share > 0.9 else C["fg"])
            self.progress_text.set(_("Aperçu à jour — rien n'est encore modifié. Cliquez sur « Appliquer »."))

        self._run(lambda progress: session.preview_cleaning(keys, options, thresholds, offsets, progress), done)

    def apply(self) -> None:
        try:
            options, thresholds, offsets = self.options(), self.thresholds(), self.offsets()
        except ValueError as exc:
            messagebox.showerror(_("Réglage invalide"), str(exc), parent=self)
            return
        self.app.noise_mode.set(options.noise_mode)
        if not (options.remove_noise or options.remove_peaks or options.zero_offset):
            messagebox.showinfo(_("Nettoyage"), _("Activez au moins un traitement."), parent=self)
            return
        self._job += 1  # un éventuel calcul en cours est abandonné
        self.destroy()
        self.app.apply_cleaning(self.keys, options, thresholds, offsets)
