"""Fenêtre « Nettoyer… » : réglages par voie et aperçu avant d'appliquer (US-03)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List, Optional

from .cleaning import CleaningOptions
from .export import Key
from .help import HelpWindow
from .theme import C, card

PEAK_MODES = {
    "all": "Tous les pics étroits (recommandé)",
    "saturation": "Seulement la saturation, au-delà de",
}


def _fmt(value: Optional[float]) -> str:
    return "" if value is None else "{:g}".format(value).replace(".", ",")


def _parse(text: str) -> Optional[float]:
    """« 0,02 » / « 0.02 » -> 0.02 ; vide -> None (pas de mise à 0). ValueError sinon."""
    text = text.strip().replace(",", ".")
    if not text:
        return None
    value = float(text)
    if value < 0:
        raise ValueError(text)
    return value or None


class CleaningDialog(tk.Toplevel):
    """Une ligne par voie cochée : seuil de bruit (modifiable), suggestion, aperçu."""

    def __init__(self, app, keys: List[Key]):
        super().__init__(app.root)
        self.app = app
        self.session = app.session
        self.keys = keys
        self.title("Nettoyage de {} voie(s)".format(len(keys)))
        self.transient(app.root)
        self.resizable(True, True)
        self.configure(background=C["background"])

        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Nettoyage", font=app.fonts.brand).pack(anchor=tk.W)
        ttk.Label(body, text="Réglez les traitements, vérifiez l'aperçu, puis appliquez.",
                  style="Muted.TLabel").pack(anchor=tk.W, pady=(0, 12))

        # --- traitements et réglages communs
        outer, box = card(body, "Traitements")
        outer.pack(fill=tk.X)
        top = ttk.Frame(box, style="Card.TFrame")  # grille (card() place son titre avec pack)
        top.pack(fill=tk.X)
        ttk.Checkbutton(top, text="Supprimer les pics parasites", variable=app.chk_peaks,
                        style="Card.TCheckbutton").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(top, text="larges de", style="Card.TLabel").grid(row=0, column=1, padx=(12, 4))
        self.width = tk.StringVar(value="5")
        ttk.Spinbox(top, from_=1, to=50, increment=1, width=4, textvariable=self.width).grid(row=0, column=2)
        ttk.Label(top, text="points au plus", style="Card.TLabel").grid(row=0, column=3, padx=4, sticky=tk.W)
        self.peak_mode = tk.StringVar(value=PEAK_MODES["all"])
        mode = ttk.Combobox(top, textvariable=self.peak_mode, values=list(PEAK_MODES.values()),
                            state="readonly", width=34)
        mode.grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=(26, 0), pady=(4, 0))
        mode.bind("<<ComboboxSelected>>", lambda _e: self._on_peak_mode())
        self.saturation = tk.StringVar(value="98")
        self.saturation_box = ttk.Spinbox(top, from_=50, to=100, increment=1, width=4,
                                          textvariable=self.saturation)
        self.saturation_box.grid(row=1, column=2, pady=(4, 0))
        ttk.Label(top, text="% du max", style="Card.TLabel").grid(row=1, column=3, padx=4, pady=(4, 0), sticky=tk.W)
        self._on_peak_mode()
        ttk.Checkbutton(top, text="Forcer à 0 le bruit de repos (seuil par voie ci-dessous)",
                        variable=app.chk_noise, style="Card.TCheckbutton").grid(
            row=2, column=0, columnspan=6, sticky=tk.W, pady=(8, 0))

        # --- tableau des voies
        outer, table_box = card(body, "Voies cochées",
                                "Seuil vide = pas de mise à 0. En rouge : plus de 90 % de la voie serait mise à 0.")
        outer.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        canvas = tk.Canvas(table_box, highlightthickness=0, height=min(36 + 30 * len(keys), 420),
                           background=C["card"])
        scroll = ttk.Scrollbar(table_box, orient=tk.VERTICAL, command=canvas.yview)
        table = ttk.Frame(canvas, style="Card.TFrame")
        table.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=table, anchor=tk.NW)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        headers = ["VOIE", "MIN … MAX", "SEUIL BRUIT", "SUGGESTION", "PICS", "MIS À 0"]
        for col, text in enumerate(headers):
            ttk.Label(table, text=text, style="Muted.Card.TLabel").grid(
                row=0, column=col, sticky=tk.E if col >= 4 else tk.W, padx=6, pady=(0, 6))

        self.threshold_vars: Dict[Key, tk.StringVar] = {}
        self.suggestions: Dict[Key, Optional[float]] = {}
        self.result_labels: Dict[Key, tuple] = {}
        for row, key in enumerate(keys, start=1):
            m = self.session.measurements[key[0]]
            ch = m.channel(key[1])
            y = m.data[key[1]]
            name = key[1] if len({k[0] for k in keys}) == 1 else "{} — {}".format(key[1], key[0])
            ttk.Label(table, text=name, style="Card.TLabel").grid(row=row, column=0, sticky=tk.W, padx=6, pady=2)
            ttk.Label(table, text="{:.4g} … {:.4g}".format(y.min(), y.max()), style="Muted.Card.TLabel").grid(
                row=row, column=1, sticky=tk.W, padx=6)
            cell = ttk.Frame(table, style="Card.TFrame")
            cell.grid(row=row, column=2, sticky=tk.W, padx=6)
            var = tk.StringVar(value=_fmt(self.session.noise_threshold(key)))
            ttk.Entry(cell, textvariable=var, width=9).pack(side=tk.LEFT)
            ttk.Label(cell, text=ch.unit, style="Muted.Card.TLabel").pack(side=tk.LEFT, padx=(4, 0))
            self.threshold_vars[key] = var
            suggestion = self.session.suggest_noise_threshold(key)
            self.suggestions[key] = suggestion
            if suggestion:
                hint = _fmt(suggestion) + " " + ch.unit
            elif self.session.has_rest_phase(key):
                hint = "non calculable"
            else:
                hint = "pas de repos à 0"
            ttk.Label(table, text=hint, style="Card.TLabel",
                      foreground=C["success"] if suggestion else C["ring"]).grid(row=row, column=3, sticky=tk.W, padx=6)
            peaks = ttk.Label(table, text="–", width=7, anchor=tk.E, style="Card.TLabel")
            zeros = ttk.Label(table, text="–", width=14, anchor=tk.E, style="Card.TLabel")
            peaks.grid(row=row, column=4, sticky=tk.E, padx=6)
            zeros.grid(row=row, column=5, sticky=tk.E, padx=6)
            self.result_labels[key] = (peaks, zeros)

        ttk.Label(body, wraplength=680, style="Muted.TLabel", justify=tk.LEFT, text=(
            "« Pas de repos à 0 » : la voie ne revient jamais à 0 (petit courant permanent…) ; elle "
            "n'est pas mise à 0 par défaut, cela effacerait de vraies mesures."
        )).pack(fill=tk.X, pady=(8, 0))

        # --- boutons
        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(buttons, text="?", style="Icon.TButton", width=2,
                   command=lambda: HelpWindow.open(self, "Nettoyage")).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Utiliser les suggestions", command=self.use_suggestions).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="Aperçu", command=self.preview).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Appliquer", style="Primary.TButton", command=self.apply).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Annuler", command=self.destroy).pack(side=tk.RIGHT, padx=6)
        self.preview()
        # Le tableau défile verticalement : la fenêtre doit être assez large pour toutes ses colonnes
        self.update_idletasks()
        canvas.configure(width=table.winfo_reqwidth())

    # ------------------------------------------------------------------- actions

    def _on_peak_mode(self) -> None:
        saturation = self.peak_mode.get() == PEAK_MODES["saturation"]
        self.saturation_box.state(["!disabled"] if saturation else ["disabled"])

    def options(self) -> CleaningOptions:
        return CleaningOptions(
            remove_noise=self.app.chk_noise.get(),
            remove_peaks=self.app.chk_peaks.get(),
            peak_mode="saturation" if self.peak_mode.get() == PEAK_MODES["saturation"] else "all",
            saturation_ratio=float(self.saturation.get().replace(",", ".")) / 100.0,
            max_peak_width=int(self.width.get()),
        )

    def thresholds(self) -> Dict[Key, Optional[float]]:
        out = {}
        for key, var in self.threshold_vars.items():
            try:
                out[key] = _parse(var.get())
            except ValueError:
                raise ValueError("Seuil invalide pour « {} » : {}".format(key[1], var.get()))
        return out

    def use_suggestions(self) -> None:
        for key, var in self.threshold_vars.items():
            var.set(_fmt(self.suggestions[key]))
        self.preview()

    def preview(self) -> None:
        try:
            options, thresholds = self.options(), self.thresholds()
        except ValueError as exc:
            messagebox.showerror("Réglage invalide", str(exc), parent=self)
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            reports = self.session.preview_cleaning(self.keys, options, thresholds)
        finally:
            self.config(cursor="")
        for key, report in reports.items():
            peaks, zeros = self.result_labels[key]
            n = len(self.session.measurements[key[0]].data)
            peaks.config(text=str(report.peak_points) if options.remove_peaks else "–")
            share = report.noise_points / n if n else 0
            zeros.config(
                text="{} ({:.0%})".format(report.noise_points, share) if options.remove_noise else "–",
                foreground=C["destructive"] if share > 0.9 else C["fg"],  # voie presque entièrement effacée
            )

    def apply(self) -> None:
        try:
            options, thresholds = self.options(), self.thresholds()
        except ValueError as exc:
            messagebox.showerror("Réglage invalide", str(exc), parent=self)
            return
        if not (options.remove_noise or options.remove_peaks):
            messagebox.showinfo("Nettoyage", "Activez au moins un traitement.", parent=self)
            return
        self.destroy()
        self.app.apply_cleaning(self.keys, options, thresholds)
