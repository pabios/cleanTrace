"""US-04 — Visualisation multi-axes : V / A à gauche, °C et %HR sur des axes secondaires.

* axes Y secondaires (``twinx``) créés automatiquement pour la température et l'humidité ;
* axe X au format ``H:MM:SS`` ;
* décalage temporel réglable des courbes climatiques (retard du banc thermique) ;
* légende multi-colonnes au-delà de 20 voies.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence

import numpy as np
from matplotlib import cm
from matplotlib.ticker import FuncFormatter, MaxNLocator

from .channels import HUMIDITY, TEMPERATURE

LEGEND_MAX_ROWS = 20


@dataclass
class PlotSeries:
    gid: str  # identifiant de la courbe (sert à la correction au clic)
    label: str  # texte de la légende
    x: np.ndarray  # Time_min
    y: np.ndarray
    unit: str
    quantity: str
    shiftable: bool = False  # courbe climatique concernée par le décalage temporel


def format_hms(minutes: float, _pos=None) -> str:
    """Minutes -> "H:MM:SS"."""
    if minutes is None or not math.isfinite(minutes):
        return ""
    total = int(round(minutes * 60))
    sign = "-" if total < 0 else ""
    hours, rest = divmod(abs(total), 3600)
    mins, secs = divmod(rest, 60)
    return "{}{}:{:02d}:{:02d}".format(sign, hours, mins, secs)


def _cmap(name: str):
    try:
        import matplotlib

        return matplotlib.colormaps[name]
    except (AttributeError, KeyError):  # Matplotlib < 3.5
        return cm.get_cmap(name)


def _colors(n: int):
    if n <= 10:
        cmap, values = _cmap("tab10"), range(n)
    elif n <= 20:
        cmap, values = _cmap("tab20"), range(n)
    else:
        cmap, values = _cmap("turbo"), np.linspace(0.05, 0.95, n)
    return [cmap(v) for v in values]


class PlotManager:
    """Dessine les séries sélectionnées sur une figure Matplotlib (sans pyplot)."""

    def __init__(self, figure):
        self.figure = figure
        self.time_offset_min = 0.0
        self._shiftable: Dict[str, tuple] = {}  # gid -> (ligne, x d'origine)
        self.draw([])

    def draw(self, series: Sequence[PlotSeries], title: str = "") -> None:
        fig = self.figure
        fig.clear()
        self._shiftable = {}
        ax = fig.add_subplot(111)

        if not series:
            ax.set_axis_off()
            ax.text(
                0.5, 0.5,
                "Ouvrez un ou plusieurs fichiers de mesure\n(bouton « Ouvrir des fichiers… »)",
                ha="center", va="center", fontsize=12, color="0.45", transform=ax.transAxes,
            )
            fig.canvas.draw_idle()
            return

        axes = {"main": ax}
        if any(s.quantity == TEMPERATURE for s in series):
            axes[TEMPERATURE] = ax.twinx()
        if any(s.quantity == HUMIDITY for s in series):
            axes[HUMIDITY] = ax.twinx()
            if TEMPERATURE in axes:
                axes[HUMIDITY].spines["right"].set_position(("axes", 1.09))

        handles = []
        for s, color in zip(series, _colors(len(series))):
            target = axes.get(s.quantity, ax)
            x = s.x + (self.time_offset_min if s.shiftable else 0.0)
            (line,) = target.plot(x, s.y, color=color, linewidth=1.0, label=s.label, gid=s.gid)
            if s.shiftable:
                self._shiftable[s.gid] = (line, np.asarray(s.x, dtype=float))
            handles.append(line)

        main_units = sorted({s.unit for s in series if s.quantity not in (TEMPERATURE, HUMIDITY) and s.unit})
        if any(s.quantity not in (TEMPERATURE, HUMIDITY) for s in series):
            ax.set_ylabel("Signaux électriques" + (" ({})".format(", ".join(main_units)) if main_units else ""))
        else:
            ax.set_yticks([])
        if TEMPERATURE in axes:
            axes[TEMPERATURE].set_ylabel("Température (°C)", color="#b2182b")
            axes[TEMPERATURE].tick_params(axis="y", colors="#b2182b")
        if HUMIDITY in axes:
            axes[HUMIDITY].set_ylabel("Humidité (%HR)", color="#2166ac")
            axes[HUMIDITY].tick_params(axis="y", colors="#2166ac")

        ax.xaxis.set_major_formatter(FuncFormatter(format_hms))
        ax.xaxis.set_major_locator(MaxNLocator(nbins=10, steps=[1, 2, 2.5, 5, 6, 10]))
        ax.set_xlabel("Temps (H:MM:SS)")
        ax.grid(True, alpha=0.3)
        ax.format_coord = self._format_coord
        if title:
            ax.set_title(title, fontsize=10, loc="left", color="0.35")

        self._place_legend(ax, list(axes.values())[-1], handles, n_twins=len(axes) - 1)
        try:
            fig.tight_layout()
        except Exception:  # pragma: no cover - tight_layout peut échouer sur de très petites fenêtres
            pass
        fig.canvas.draw_idle()

    def set_time_offset(self, minutes: float) -> None:
        """Décale les courbes climatiques sans retracer le graphique."""
        self.time_offset_min = float(minutes)
        for line, x in self._shiftable.values():
            line.set_xdata(x + self.time_offset_min)
        self.figure.canvas.draw_idle()

    @staticmethod
    def _format_coord(x, y):
        return "t = {}   y = {:.6g}".format(format_hms(x), y)

    @staticmethod
    def _place_legend(ax, top_ax, handles, n_twins: int) -> None:
        labels = [h.get_label() for h in handles]
        if len(handles) <= LEGEND_MAX_ROWS:
            # Légende sur l'axe du dessus pour qu'elle ne soit pas masquée par les courbes
            leg = top_ax.legend(handles, labels, loc="best", fontsize="small", framealpha=0.85)
        else:
            ncol = math.ceil(len(handles) / LEGEND_MAX_ROWS)
            anchor_x = 1.02 + 0.09 * n_twins + (0.06 if n_twins else 0)
            leg = top_ax.legend(
                handles, labels, loc="upper left", bbox_to_anchor=(anchor_x, 1.0),
                ncol=ncol, fontsize="x-small", framealpha=0.85, borderaxespad=0.0,
            )
        leg.set_draggable(True)
