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
from matplotlib.ticker import FuncFormatter, Locator, MaxNLocator

from .channels import HUMIDITY, TEMPERATURE
from .i18n import _

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
    index_base: int = 0  # indice, dans les données complètes, du premier point de x / y
    raw: bool = False  # données brutes affichées en gris sous la voie nettoyée (comparaison)


def format_hms(minutes: float, _pos=None) -> str:
    """Minutes -> "H:MM:SS"."""
    if minutes is None or not math.isfinite(minutes):
        return ""
    total = int(round(minutes * 60))
    sign = "-" if total < 0 else ""
    hours, rest = divmod(abs(total), 3600)
    mins, secs = divmod(rest, 60)
    return _("{}{}:{:02d}:{:02d}").format(sign, hours, mins, secs)


def format_axis_time(minutes: float, _pos=None) -> str:
    """Graduation de l'axe X : toujours « H:MM:SS », même au-delà de 24 h (ex. « 48:00:00 »)."""
    return format_hms(minutes)


class TimeLocator(Locator):
    """Graduations à des pas de temps « ronds » (10 s, 1 min, 15 min, 1 h, 6 h, 1 j...)."""

    STEPS_MIN = [1 / 60, 2 / 60, 5 / 60, 10 / 60, 15 / 60, 30 / 60, 1, 2, 5, 10, 15, 30,
                 60, 120, 180, 360, 720, 1440, 2880, 7 * 1440, 14 * 1440, 30 * 1440, 90 * 1440]

    def __init__(self, max_ticks: int = 8):
        self.max_ticks = max_ticks

    def __call__(self):
        vmin, vmax = self.axis.get_view_interval()
        return self.tick_values(vmin, vmax)

    def tick_values(self, vmin, vmax):
        if vmax < vmin:
            vmin, vmax = vmax, vmin
        span = max(vmax - vmin, 1e-9)
        step = next((s for s in self.STEPS_MIN if span / s <= self.max_ticks), self.STEPS_MIN[-1])
        start = math.ceil(vmin / step) * step
        return np.arange(start, vmax + step * 1e-6, step)


def _cmap(name: str):
    try:
        import matplotlib

        return matplotlib.colormaps[name]
    except (AttributeError, KeyError):  # Matplotlib < 3.5
        return cm.get_cmap(name)


def _colors(n: int):
    """Couleurs des courbes : palette du thème, puis dégradé au-delà."""
    from matplotlib.colors import to_hex

    from .theme import SERIES_COLORS

    if n <= len(SERIES_COLORS):
        return SERIES_COLORS[:n]
    cmap = _cmap("turbo")
    return [to_hex(cmap(v)) for v in np.linspace(0.05, 0.95, n)]


# Au-delà de ce nombre de points visibles, une courbe est réduite pour l'affichage
# (min et max de chaque tranche : aucun pic ne disparaît). Les données ne sont jamais
# modifiées ; le détail complet réapparaît en zoomant.
MAX_BUCKETS = 2000


def decimate_indices(y: np.ndarray, start: int, stop: int, buckets: int = MAX_BUCKETS) -> np.ndarray:
    """Indices à tracer entre ``start`` et ``stop`` : tous si peu nombreux, sinon min/max par tranche."""
    count = stop - start
    if count <= 2 * buckets:
        return np.arange(start, stop)
    size = count // buckets
    used = size * buckets
    seg = y[start:start + used].reshape(buckets, size)
    nan = np.isnan(seg)
    lo = np.where(nan, np.inf, seg).argmin(axis=1)
    hi = np.where(nan, -np.inf, seg).argmax(axis=1)
    base = start + np.arange(buckets) * size
    idx = np.empty(2 * buckets, dtype=np.int64)
    idx[0::2] = base + np.minimum(lo, hi)
    idx[1::2] = base + np.maximum(lo, hi)
    return np.unique(np.concatenate(([start], idx, [stop - 1])))


class _Trace:
    """Une courbe affichée : données complètes + indices actuellement tracés."""

    def __init__(self, line, x, y, shiftable, index_base=0):
        self.index_base = index_base
        self.line = line
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.shiftable = shiftable
        self.index = np.arange(0)


class PlotManager:
    """Dessine les séries sélectionnées sur une figure Matplotlib (sans pyplot)."""

    def __init__(self, figure):
        self.figure = figure
        self.time_offset_min = 0.0
        self.percent_axis = False  # axe du temps en % de la durée (mode « étiré »)
        self._traces: Dict[str, _Trace] = {}
        self._main_ax = None
        self.colors: Dict[str, str] = {}  # gid -> couleur de la courbe
        self.draw([])

    def draw(self, series: Sequence[PlotSeries], title: str = "") -> None:
        fig = self.figure
        fig.clear()
        self._traces = {}
        self.colors = {}
        ax = fig.add_subplot(111)
        self._main_ax = ax

        if not series:
            ax.set_axis_off()  # l'application affiche son propre écran d'accueil
            fig.canvas.draw_idle()
            return

        from .theme import C

        axes = {"main": ax}
        if any(s.quantity == TEMPERATURE for s in series):
            axes[TEMPERATURE] = ax.twinx()
        if any(s.quantity == HUMIDITY for s in series):
            axes[HUMIDITY] = ax.twinx()
            if TEMPERATURE in axes:
                axes[HUMIDITY].spines["right"].set_position(("axes", 1.09))

        handles = []
        main = [s for s in series if not s.raw]
        palette = dict(zip((s.gid for s in main), _colors(len(main))))
        for s in sorted(series, key=lambda s: not s.raw):  # le brut d'abord : dessous
            target = axes.get(s.quantity, ax)
            if s.raw:
                (line,) = target.plot([], [], color=C["border_strong"], linewidth=0.9, label=_("_brut"), gid=s.gid,
                                      zorder=1)
                trace = _Trace(line, s.x, s.y, s.shiftable, s.index_base)
                self._traces[s.gid] = trace
                self._refresh(trace, None)
                continue
            color = palette[s.gid]
            (line,) = target.plot([], [], color=color, linewidth=1.2, label=s.label, gid=s.gid, zorder=2)
            self.colors[s.gid] = color
            trace = _Trace(line, s.x, s.y, s.shiftable, s.index_base)
            self._traces[s.gid] = trace
            self._refresh(trace, None)
            handles.append(line)
        for a in axes.values():
            a.relim()
            a.autoscale_view()

        main_units = sorted({s.unit for s in main if s.quantity not in (TEMPERATURE, HUMIDITY) and s.unit})
        if any(s.quantity not in (TEMPERATURE, HUMIDITY) for s in main):
            ax.set_ylabel(_("Signaux électriques") + (" ({})".format(", ".join(main_units)) if main_units else ""))
        else:
            ax.set_yticks([])
        from .theme import HUMIDITY_COLOR, TEMPERATURE_COLOR

        if TEMPERATURE in axes:
            axes[TEMPERATURE].set_ylabel(_("Température (°C)"), color=TEMPERATURE_COLOR)
            axes[TEMPERATURE].tick_params(axis="y", colors=TEMPERATURE_COLOR)
        if HUMIDITY in axes:
            axes[HUMIDITY].set_ylabel(_("Humidité (%HR)"), color=HUMIDITY_COLOR)
            axes[HUMIDITY].tick_params(axis="y", colors=HUMIDITY_COLOR)
        # Style épuré : fond blanc, bordures fines, grille discrète, textes atténués
        for a in axes.values():
            a.set_facecolor(C["card"])
            for side in ("top", "left", "bottom", "right"):
                a.spines[side].set_color(C["border_strong"])
                a.spines[side].set_linewidth(0.8)
            a.spines["top"].set_visible(False)
            a.tick_params(length=3, width=0.8, labelsize=9, color=C["border_strong"])
        ax.spines["right"].set_visible(False)
        ax.tick_params(axis="both", labelcolor=C["muted_fg"])
        ax.yaxis.label.set_color(C["fg_soft"])
        ax.xaxis.label.set_color(C["fg_soft"])
        for twin in list(axes.values())[1:]:
            twin.spines["left"].set_visible(False)
            twin.spines["bottom"].set_visible(False)

        if self.percent_axis:
            ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _pos=None: _("{:g} %").format(round(v, 1))))
            ax.xaxis.set_major_locator(MaxNLocator(nbins=10, steps=[1, 2, 2.5, 5, 10]))
            ax.set_xlabel(_("Avancement (% de la durée de chaque fichier)"))
        else:
            ax.xaxis.set_major_formatter(FuncFormatter(format_axis_time))
            ax.xaxis.set_major_locator(TimeLocator())
            ax.set_xlabel(_("Temps (H:MM:SS)"))
        ax.grid(True, color=C["muted"], linewidth=1.0)
        ax.set_axisbelow(True)
        ax.format_coord = self._format_coord
        if title:
            ax.set_title(title, fontsize=10, loc="left", color="0.35")

        self._place_legend(ax, list(axes.values())[-1], handles, n_twins=len(axes) - 1)
        try:
            fig.tight_layout()
        except Exception:  # pragma: no cover - tight_layout peut échouer sur de très petites fenêtres
            pass
        # Zoom / déplacement : on recalcule les points visibles
        for a in axes.values():
            a.callbacks.connect("xlim_changed", self._on_xlim_changed)
        fig.canvas.draw_idle()

    def set_time_offset(self, minutes: float) -> None:
        """Décale les courbes climatiques sans retracer le graphique."""
        self.time_offset_min = float(minutes)
        for trace in self._traces.values():
            if trace.shiftable:
                self._refresh(trace, self._view())
        self.figure.canvas.draw_idle()

    def current_view(self):
        """Période affichée (zoom) en minutes, ou None si rien n'est tracé."""
        return tuple(self._main_ax.get_xlim()) if self._traces and self._main_ax is not None else None

    def original_index(self, gid: str, plotted_index: int) -> int:
        """Indice dans les données complètes d'un point tracé."""
        trace = self._traces[gid]
        return int(trace.index_base + trace.index[plotted_index])

    def update_data(self, gid: str, y) -> None:
        """Nouvelles valeurs d'une courbe (après correction), sans retracer le reste."""
        trace = self._traces[gid]
        y = np.asarray(y, dtype=float)
        trace.y = y[trace.index_base:trace.index_base + len(trace.x)]
        self._refresh(trace, self._view())
        self.figure.canvas.draw_idle()

    # ------------------------------------------------------------------ interne

    def _view(self):
        return self._main_ax.get_xlim() if self._main_ax is not None else None

    def _on_xlim_changed(self, _ax) -> None:
        view = self._view()
        for trace in self._traces.values():
            self._refresh(trace, view)

    def _refresh(self, trace: _Trace, view) -> None:
        offset = self.time_offset_min if trace.shiftable else 0.0
        n = len(trace.x)
        if view is None:
            start, stop = 0, n
        else:
            start = max(0, int(np.searchsorted(trace.x, view[0] - offset)) - 1)
            stop = min(n, int(np.searchsorted(trace.x, view[1] - offset)) + 1)
        trace.index = decimate_indices(trace.y, start, max(start, stop))
        trace.line.set_data(trace.x[trace.index] + offset, trace.y[trace.index])

    def _format_coord(self, x, y):
        t = _("{:.2f} %").format(x) if self.percent_axis else format_hms(x)
        return _("t = {}   y = {:.6g}").format(t, y)

    @staticmethod
    def _place_legend(ax, top_ax, handles, n_twins: int) -> None:
        labels = [h.get_label() for h in handles]
        if len(handles) <= LEGEND_MAX_ROWS:
            # Légende sur l'axe du dessus pour qu'elle ne soit pas masquée par les courbes.
            # "best" teste chaque point : trop lent quand il y a beaucoup de courbes.
            loc = "best" if len(handles) <= 4 else "upper right"
            leg = top_ax.legend(handles, labels, loc=loc, fontsize="small", framealpha=0.95)
        else:
            ncol = math.ceil(len(handles) / LEGEND_MAX_ROWS)
            anchor_x = 1.02 + 0.09 * n_twins + (0.06 if n_twins else 0)
            leg = top_ax.legend(
                handles, labels, loc="upper left", bbox_to_anchor=(anchor_x, 1.0),
                ncol=ncol, fontsize="x-small", framealpha=0.85, borderaxespad=0.0,
            )
        from .theme import C

        frame = leg.get_frame()
        frame.set_edgecolor(C["border"])
        frame.set_linewidth(0.8)
        frame.set_boxstyle("round,pad=0.4,rounding_size=0.6")
        for text in leg.get_texts():
            text.set_color(C["fg_soft"])
        leg.set_draggable(True)
