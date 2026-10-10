"""Livrables pour le client : image du graphique et rapport PDF (Matplotlib, sans dépendance).

Le rapport PDF (A4 paysage) contient :
1. une page de synthèse : fichiers sources, base de temps, voies, statistiques par voie ;
2. le graphique, tel qu'affiché (même zoom) ;
3. le journal des traitements (traçabilité : nettoyages, décalages, corrections au clic).
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

from . import __version__
from .export import Key
from .loader import TIME_COL
from .plotting import PlotManager, format_hms
from .theme import C
from .i18n import _

A4_LANDSCAPE = (11.69, 8.27)  # pouces


def save_figure_image(session, keys: Sequence[Key], view: Optional[Tuple[float, float]], path,
                      title: str = "", dpi: int = 200, settings=None) -> Path:
    """Image du graphique (PNG, PDF ou SVG selon l'extension), au format A4 paysage."""
    path = Path(path)
    fig = _plot_figure(session, keys, view, title, settings)
    fig.savefig(path, dpi=dpi, facecolor="white")
    session.log(_("Image du graphique exportée : {}").format(path.name))
    return path


def build_report(session, keys: Sequence[Key], view: Optional[Tuple[float, float]], path,
                 title: str = "", progress: Optional[Callable] = None, settings=None) -> Path:
    """Rapport PDF : synthèse + graphique + journal des traitements."""
    path = Path(path)
    title = title or _("Rapport de traitement des mesures")
    session.log(_("Rapport PDF : {}").format(path.name))
    with PdfPages(path) as pdf:
        if progress:
            progress(_("Rapport — page de synthèse…"), 0.1)
        pdf.savefig(_summary_page(session, keys, view, title))
        if progress:
            progress(_("Rapport — graphique…"), 0.4)
        pdf.savefig(_plot_figure(session, keys, view, title, settings))
        if progress:
            progress(_("Rapport — journal des traitements…"), 0.8)
        for page in _journal_pages(session, title):
            pdf.savefig(page)
        info = pdf.infodict()
        info["Title"] = title
        info["Creator"] = _("CleanTrace v{}").format(__version__)
    return path


# --------------------------------------------------------------------- pages


def _new_page() -> Figure:
    fig = Figure(figsize=A4_LANDSCAPE, facecolor="white")
    FigureCanvasAgg(fig)
    return fig


def _header(fig: Figure, title: str, subtitle: str) -> None:
    fig.text(0.05, 0.94, title, fontsize=16, fontweight="bold", color=C["fg"])
    fig.text(0.05, 0.91, subtitle, fontsize=9, color=C["muted_fg"])
    fig.text(0.95, 0.94, _("CleanTrace v{}").format(__version__), fontsize=9, color=C["muted_fg"], ha="right")
    fig.text(0.95, 0.91, _("Édité le {}").format(pd.Timestamp.now().strftime(_("%d/%m/%Y à %H:%M"))),
             fontsize=9, color=C["muted_fg"], ha="right")
    fig.add_artist(_hline(fig, 0.895))


def _hline(fig, y):
    from matplotlib.lines import Line2D

    return Line2D([0.05, 0.95], [y, y], transform=fig.transFigure, color=C["border"], linewidth=0.8)


def _section(fig, y: float, text: str) -> float:
    fig.text(0.05, y, text, fontsize=11, fontweight="bold", color=C["fg"])
    return y - 0.03


def _table(fig, y_top: float, header: List[str], rows: List[List[str]], widths: List[float], height=0.032):
    """Tableau simple (lignes séparées par un filet), renvoie la position sous le tableau."""
    x0 = 0.05
    xs = [x0]
    for w in widths[:-1]:
        xs.append(xs[-1] + w)
    for x, text in zip(xs, header):
        fig.text(x, y_top, text, fontsize=7.5, color=C["muted_fg"], fontweight="bold")
    y = y_top - 0.012
    fig.add_artist(_hline(fig, y))
    for row in rows:
        y -= height * 0.75
        for x, text, w in zip(xs, row, widths):
            fig.text(x, y, _clip(text, w), fontsize=8, color=C["fg_soft"])
        y -= height * 0.25
        fig.add_artist(_hline(fig, y))
    return y - 0.045


def _clip(text: str, width: float) -> str:
    max_chars = max(4, int(width * 150))
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _summary_page(session, keys, view, title) -> Figure:
    fig = _new_page()
    files = list(session.measurements.values())
    _header(fig, title, _("Synthèse : fichiers sources, base de temps et statistiques des voies retenues"))

    y = _section(fig, 0.85, _("Fichiers sources"))
    rows = []
    for m in files:
        end = m.start + pd.Timedelta(minutes=m.duration_min) if m.start is not None else None
        rows.append([
            m.name + (_("  (référence)") if m is session.reference else ""), _(m.source), m.period_label,
            m.start.strftime("%d/%m/%Y %H:%M:%S") if m.start is not None else "—",
            end.strftime("%d/%m/%Y %H:%M:%S") if end is not None else "—",
            "{:,}".format(len(m.data)).replace(",", " "), str(len(m.channels)),
        ])
    y = _table(fig, y, [_("FICHIER"), _("APPAREIL"), _("PÉRIODE"), _("DÉBUT"), _("FIN"), "POINTS", _("VOIES")],
               rows, [0.30, 0.10, 0.08, 0.15, 0.15, 0.09, 0.05])

    from .session import EXPORT_STEPS, TIME_MODES

    y = _section(fig, y, _("Base de temps"))
    lines = [_("Mode : {}").format(TIME_MODES[session.time_mode])]
    if session.window is not None and session.window_start is not None:
        lines.append(_("Période commune : {} → {}").format(
            session.window_start.strftime("%d/%m/%Y %H:%M:%S"),
            (session.window_start + pd.Timedelta(minutes=session.window[1] - session.window[0]))
            .strftime("%d/%m/%Y %H:%M:%S")))
    if view is not None and not session.percent_axis:
        lines.append(_("Période représentée : {} → {}").format(format_hms(view[0]), format_hms(view[1])))
    if session.time_offset_min:
        lines.append(_("Décalage enceinte climatique : {:+.1f} min").format(session.time_offset_min))
    lines.append(_("Grille d'export : {}").format(_(EXPORT_STEPS[session.export_step_s])))
    for line in lines:
        fig.text(0.05, y, line, fontsize=8.5, color=C["fg_soft"])
        y -= 0.022
    y -= 0.01

    y = _section(fig, y, _("Voies retenues (statistiques sur la période représentée)"))
    rows = []
    for key in keys:
        m = session.measurements[key[0]]
        ch = m.channel(key[1])
        x = m.data[TIME_COL].to_numpy(dtype=float)
        v = m.data[key[1]].to_numpy(dtype=float)
        if view is not None:
            inside = (x >= view[0]) & (x <= view[1])
            v = v[inside]
        v = v[np.isfinite(v)]
        modified = session.modified_points(key)
        fmt = "{:.5g}".format
        rows.append([
            key[1], key[0], ch.unit or "—",
            fmt(v.min()) if len(v) else "—", fmt(v.max()) if len(v) else "—",
            fmt(v.mean()) if len(v) else "—", fmt(v.std()) if len(v) else "—",
            "{:,}".format(modified).replace(",", " "),
        ])
    _table(fig, y, [_("VOIE"), _("FICHIER"), _("UNITÉ"), "MIN", "MAX", _("MOYENNE"), _("ÉCART-TYPE"),
                    _("POINTS MODIFIÉS")],
           rows, [0.22, 0.22, 0.05, 0.08, 0.08, 0.08, 0.08, 0.09], height=0.028)
    return fig


def _plot_figure(session, keys, view, title, settings=None) -> Figure:
    fig = _new_page()
    plot = PlotManager(fig)
    plot.time_offset_min = session.time_offset_min
    plot.percent_axis = session.percent_axis
    plot.draw(session.series(keys), title=title, settings=settings)
    if view is not None and fig.axes:
        fig.axes[0].set_xlim(*view)
    try:
        fig.set_layout_engine("none")  # page A4 : marges fixes
    except AttributeError:  # pragma: no cover - Matplotlib < 3.6
        fig.set_tight_layout(False)
    fig.subplots_adjust(left=0.07, right=0.88 if len(fig.axes) > 1 else 0.96, top=0.92, bottom=0.10)
    return fig


def _journal_pages(session, title) -> List[Figure]:
    lines = []
    for t, text in session.journal:
        wrapped = textwrap.wrap(text, 150) or [""]
        lines.append("{}   {}".format(t.strftime("%d/%m/%Y %H:%M:%S"), wrapped[0]))
        lines += [" " * 22 + more for more in wrapped[1:]]
    per_page = 42
    pages = []
    for start in range(0, max(1, len(lines)), per_page):
        fig = _new_page()
        _header(fig, title, _("Journal des traitements (traçabilité des modifications des données brutes)"))
        y = 0.86
        for line in lines[start:start + per_page] or [_("Aucun traitement.")]:
            fig.text(0.05, y, line, fontsize=7.5, family="monospace", color=C["fg_soft"])
            y -= 0.0185
        pages.append(fig)
    return pages
