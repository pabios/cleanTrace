"""Fenêtre « Modifier les axes et les courbes » (bouton de la barre d'outils du graphique).

Équivalent de la fenêtre « Figure options » de Matplotlib (version Qt), absente de la barre
Tk : titre, limites / libellés / échelle de chaque axe, et apparence de chaque voie.
Les réglages sont gardés quand on change de voies ou qu'on nettoie ; le bouton « Maison »
remet les limites automatiques. Ils sont repris dans l'image et le rapport PDF.
"""
from __future__ import annotations

import copy
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from typing import Dict, List, Optional

from .channels import HUMIDITY, TEMPERATURE
from .export import Key
from .help import HelpWindow
from .i18n import _, get_language
from .plotting import LINE_STYLES, MAIN_AXIS, MARKERS, AxisSettings, CurveStyle, PlotSettings, format_hms, parse_hms
from .theme import C, card

AXIS_NAMES = {
    MAIN_AXIS: "Axe Y gauche — signaux électriques",
    TEMPERATURE: "Axe Y — température",
    HUMIDITY: "Axe Y — humidité",
}
SCALES = {False: "Linéaire", True: "Logarithmique"}


def _number(value: Optional[float]) -> str:
    if value is None:
        return ""
    text = "{:.6g}".format(value)
    return text.replace(".", ",") if get_language() == "fr" else text


def _parse_number(text: str) -> Optional[float]:
    text = text.strip().replace(",", ".")
    return float(text) if text else None


class AxesDialog(tk.Toplevel):
    """Onglet « Axes » (titre, X, chaque Y) et onglet « Courbes » (une ligne par voie)."""

    def __init__(self, app, keys: List[Key]):
        super().__init__(app.root)
        self.app = app
        self.keys = keys
        self.settings = copy.deepcopy(app.plot_settings)
        plot = app.plot
        self.percent = plot.percent_axis
        self.title(_("Axes et courbes"))
        self.transient(app.root)
        self.configure(background=C["background"])

        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=_("Axes et courbes"), font=app.fonts.brand).pack(anchor=tk.W)
        ttk.Label(body, text=_("Champ vide = automatique. Les réglages restent quand vous changez de voies ; "
                               "le bouton « Maison » remet les limites automatiques."),
                  style="Muted.TLabel").pack(anchor=tk.W, pady=(0, 12))

        tabs = ttk.Notebook(body)
        tabs.pack(fill=tk.BOTH, expand=True)
        self._build_axes_tab(tabs, plot)
        self._build_curves_tab(tabs, plot)

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="?", style="Icon.TButton", width=2,
                   command=lambda: HelpWindow.open(self, "Axes et courbes")).pack(side=tk.LEFT)
        ttk.Button(buttons, text=_("Tout remettre par défaut"), command=self.reset).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text=_("OK"), style="Primary.TButton", command=self.ok).pack(side=tk.RIGHT)
        ttk.Button(buttons, text=_("Appliquer"), command=self.apply).pack(side=tk.RIGHT, padx=6)
        ttk.Button(buttons, text=_("Annuler"), command=self.destroy).pack(side=tk.RIGHT)
        self.bind("<Return>", lambda _e: self.ok())
        self.bind("<Escape>", lambda _e: self.destroy())

    # ------------------------------------------------------------------ onglets

    def _field(self, grid, row, label, value, width=14, column=0, span=1):
        ttk.Label(grid, text=label, style="Card.TLabel").grid(row=row, column=column, sticky=tk.W,
                                                             padx=(16 if column else 0, 8), pady=3)
        var = tk.StringVar(value=value)
        ttk.Entry(grid, textvariable=var, width=width).grid(row=row, column=column + 1, columnspan=span,
                                                           sticky=tk.W, pady=3)
        return var

    def _build_axes_tab(self, tabs, plot) -> None:
        outer, box = card(tabs)
        tabs.add(outer, text=_("Axes"))
        grid = ttk.Frame(box, style="Card.TFrame")
        grid.pack(fill=tk.BOTH, expand=True)
        self.title_var = self._field(grid, 0, _("Titre du graphique"), self.settings.title, width=46, span=3)

        ax = plot.axes[MAIN_AXIS]
        lo, hi = ax.get_xlim()
        fmt = (lambda v: _number(round(v, 3))) if self.percent else format_hms
        ttk.Label(grid, text=_("Axe X — avancement (%)") if self.percent else _("Axe X — temps (H:MM:SS)"),
                  style="Title.Card.TLabel").grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(14, 4))
        self.x_vars = (self._field(grid, 2, _("Min"), fmt(lo)), self._field(grid, 2, _("Max"), fmt(hi), column=2))
        self.x_label = self._field(grid, 3, _("Libellé"), ax.get_xlabel(), width=46, span=3)
        self._x_initial = (fmt(lo), fmt(hi), ax.get_xlabel())

        self.y_vars: Dict[str, tuple] = {}
        row = 4
        for name, a in plot.axes.items():
            lo, hi = a.get_ylim()
            axis = self.settings.y.get(name) or AxisSettings()
            ttk.Label(grid, text=_(AXIS_NAMES[name]), style="Title.Card.TLabel").grid(
                row=row, column=0, columnspan=4, sticky=tk.W, pady=(14, 4))
            vmin = self._field(grid, row + 1, _("Min"), _number(lo))
            vmax = self._field(grid, row + 1, _("Max"), _number(hi), column=2)
            label = self._field(grid, row + 2, _("Libellé"), a.get_ylabel(), width=46, span=3)
            ttk.Label(grid, text=_("Échelle"), style="Card.TLabel").grid(row=row + 3, column=0, sticky=tk.W, pady=3)
            scale = tk.StringVar(value=_(SCALES[axis.log]))
            ttk.Combobox(grid, textvariable=scale, values=[_(v) for v in SCALES.values()], state="readonly",
                         width=16).grid(row=row + 3, column=1, sticky=tk.W, pady=3)
            self.y_vars[name] = (vmin, vmax, label, scale, (_number(lo), _number(hi), a.get_ylabel()))
            row += 4

    def _build_curves_tab(self, tabs, plot) -> None:
        outer, box = card(tabs)
        tabs.add(outer, text=_("Courbes"))
        # Défilement : jusqu'à 30 voies et plus, sur un écran de 768 px de haut
        canvas = tk.Canvas(box, highlightthickness=0, background=C["card"],
                           height=min(40 + 29 * len(self.keys), 380))
        scroll = ttk.Scrollbar(box, orient=tk.VERTICAL, command=canvas.yview)
        table = ttk.Frame(canvas, style="Card.TFrame")
        table.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"),
                                                                width=table.winfo_reqwidth()))
        canvas.create_window((0, 0), window=table, anchor=tk.NW)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        if len(self.keys) > 12:
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
        headers = [_("VOIE"), _("NOM AFFICHÉ"), _("COULEUR"), _("ÉPAISSEUR"), _("TRAIT"), _("MARQUEURS")]
        for col, text in enumerate(headers):
            ttk.Label(table, text=text, style="Muted.Card.TLabel").grid(row=0, column=col, sticky=tk.W, padx=6,
                                                                        pady=(0, 6))
        labels = {line.get_gid(): line.get_label() for a in plot.axes.values() for line in a.get_lines()}
        gid_of = {key: gid for gid, key in self.app._gid_key.items()}
        self.curve_vars: Dict[Key, tuple] = {}
        for row, key in enumerate(self.keys, start=1):
            style = self.settings.curves.get(key) or CurveStyle()
            shown = labels.get(gid_of.get(key), key[1])
            ttk.Label(table, text=key[1], style="Card.TLabel").grid(row=row, column=0, sticky=tk.W, padx=6, pady=2)
            name = tk.StringVar(value=shown)
            ttk.Entry(table, textvariable=name, width=30).grid(row=row, column=1, sticky=tk.W, padx=6)
            color = tk.StringVar(value=style.color or self.app._key_color.get(key, "#000000"))
            swatch = tk.Label(table, width=4, background=color.get(), relief=tk.FLAT, cursor="hand2",
                              highlightthickness=1, highlightbackground=C["border"])
            swatch.grid(row=row, column=2, sticky=tk.W, padx=6)
            swatch.bind("<Button-1>", lambda _e, v=color, w=swatch, k=key: self._pick_color(v, w, k))
            width = tk.StringVar(value=_number(style.width))
            ttk.Spinbox(table, from_=0.5, to=6, increment=0.5, width=5, textvariable=width).grid(
                row=row, column=3, sticky=tk.W, padx=6)
            line = tk.StringVar(value=_(LINE_STYLES.get(style.style, LINE_STYLES["-"])))
            ttk.Combobox(table, textvariable=line, values=[_(v) for v in LINE_STYLES.values()], state="readonly",
                         width=12).grid(row=row, column=4, sticky=tk.W, padx=6)
            marker = tk.StringVar(value=_(MARKERS.get(style.marker, MARKERS[""])))
            ttk.Combobox(table, textvariable=marker, values=[_(v) for v in MARKERS.values()], state="readonly",
                         width=10).grid(row=row, column=5, sticky=tk.W, padx=6)
            self.curve_vars[key] = (name, color, width, line, marker, shown, color.get())

    def _pick_color(self, var, swatch, key) -> None:
        chosen = colorchooser.askcolor(var.get(), parent=self, title=_("Couleur de {}").format(key[1]))[1]
        if chosen:
            var.set(chosen)
            swatch.configure(background=chosen)

    # ------------------------------------------------------------------ lecture

    def read_settings(self) -> PlotSettings:
        """Réglages saisis. ValueError (message lisible) si un champ est invalide."""
        out = copy.deepcopy(self.settings)
        out.title = self.title_var.get().strip()

        def changed(var, initial):
            return var.get().strip() != initial

        parse_x = _parse_number if self.percent else parse_hms
        lo_text, hi_text, label0 = self._x_initial
        for var, initial, attr in ((self.x_vars[0], lo_text, "min"), (self.x_vars[1], hi_text, "max")):
            if changed(var, initial):
                try:
                    setattr(out.x, attr, parse_x(var.get()))
                except ValueError:
                    raise ValueError(_("Temps invalide : « {} » (attendu H:MM:SS, ex. 1:30:00).").format(var.get())
                                     if not self.percent else _("Nombre invalide : « {} »").format(var.get()))
        if changed(self.x_label, label0):
            out.x.label = self.x_label.get()
        if out.x.min is not None and out.x.max is not None and out.x.min >= out.x.max:
            raise ValueError(_("Axe X : le minimum doit être inférieur au maximum."))

        for name, (vmin, vmax, label, scale, initial) in self.y_vars.items():
            axis = out.y_axis(name)
            axis.log = scale.get() == _(SCALES[True])
            for var, init, attr in ((vmin, initial[0], "min"), (vmax, initial[1], "max")):
                if changed(var, init):
                    try:
                        setattr(axis, attr, _parse_number(var.get()))
                    except ValueError:
                        raise ValueError(_("Nombre invalide : « {} »").format(var.get()))
            if changed(label, initial[2]):
                axis.label = label.get()
            title = _(AXIS_NAMES[name])
            if axis.min is not None and axis.max is not None and axis.min >= axis.max:
                raise ValueError(_("{} : le minimum doit être inférieur au maximum.").format(title))
            if axis.log and axis.min is not None and axis.min <= 0:
                raise ValueError(_("{} : en échelle logarithmique, le minimum doit être positif.").format(title))

        for key, (name, color, width, line, marker, shown, color0) in self.curve_vars.items():
            style = copy.deepcopy(out.curves.get(key) or CurveStyle())
            if name.get().strip() != shown:
                style.name = name.get().strip() or None
            if color.get() != color0:
                style.color = color.get()
            try:
                style.width = float(width.get().replace(",", "."))
            except ValueError:
                raise ValueError(_("Épaisseur invalide pour « {} » : {}").format(key[1], width.get()))
            if not 0 < style.width <= 20:
                raise ValueError(_("Épaisseur invalide pour « {} » : {}").format(key[1], width.get()))
            style.style = next(k for k, v in LINE_STYLES.items() if _(v) == line.get())
            style.marker = next(k for k, v in MARKERS.items() if _(v) == marker.get())
            out.curves[key] = style
        return out

    # ------------------------------------------------------------------ actions

    def apply(self) -> bool:
        try:
            settings = self.read_settings()
        except ValueError as exc:
            messagebox.showerror(_("Réglage invalide"), str(exc), parent=self)
            return False
        self.app.apply_plot_settings(settings)
        self.settings = copy.deepcopy(settings)
        return True

    def ok(self) -> None:
        if self.apply():
            self.destroy()

    def reset(self) -> None:
        """Titre, axes et courbes par défaut (comme à l'ouverture des fichiers)."""
        self.app.apply_plot_settings(PlotSettings())
        self.destroy()
