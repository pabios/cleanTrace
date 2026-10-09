"""US-06 — Export des données sélectionnées et nettoyées en CSV (séparateur « ; »).

Les fichiers n'ont pas la même période d'échantillonnage : les voies de chaque fichier
sont fusionnées sur la colonne commune ``Time_min`` du fichier de référence, en prenant
pour chaque instant la mesure la plus proche (``pandas.merge_asof``, tolérance d'une
période d'échantillonnage). Hors de la plage d'un fichier, les cellules restent vides.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .loader import TIME_COL, Measurement

Key = Tuple[str, str]  # (nom du fichier, libellé de la voie)


PERCENT_COL = "Avancement (%)"


def merge_selection(
    measurements: Sequence[Measurement],
    reference: Measurement,
    keys: Sequence[Key],
    time_offset_min: float = 0.0,
    window: Optional[Tuple[float, float]] = None,
    step_s: Optional[float] = None,
    percent: bool = False,
) -> pd.DataFrame:
    """Table unique : temps, puis une colonne par voie sélectionnée.

    * ``window`` : (début, fin) en minutes — seule cette période est exportée ;
    * ``step_s`` : grille de temps commune (ex. 1 s) au lieu de celle de la référence ;
    * ``percent`` : axe du temps en % de la durée de chaque fichier (mode « étiré »).
    """
    if not keys:
        raise ValueError("Aucune voie sélectionnée.")
    by_name: Dict[str, Measurement] = {m.name: m for m in measurements}
    wanted: Dict[str, List[str]] = {}
    for name, label in keys:
        wanted.setdefault(name, []).append(label)
    several_files = len(wanted) > 1
    shift = 0.0 if percent else time_offset_min

    if step_s and not percent:
        if window is None:
            spans = [(by_name[n].data[TIME_COL].iloc[0], by_name[n].data[TIME_COL].iloc[-1]) for n in wanted]
            window = (min(a for a, _ in spans), max(b for _, b in spans))
        step = step_s / 60.0
        grid = window[0] + np.arange(int(np.floor((window[1] - window[0]) / step + 1e-9)) + 1) * step
    else:
        grid = reference.data[TIME_COL].to_numpy(dtype=float)
        if window is not None:
            grid = grid[(grid >= window[0] - 1e-9) & (grid <= window[1] + 1e-9)]
    base = pd.DataFrame({TIME_COL: grid})
    out = base.copy()

    for name, labels in wanted.items():
        m = by_name[name]
        # Les fichiers d'enceinte climatique sont décalés comme à l'écran
        shifted = m.is_thermal and shift != 0.0
        part = m.data[[TIME_COL] + labels].copy()
        if shifted:
            part[TIME_COL] = part[TIME_COL] + shift
        part = part.rename(columns={c: _column_name(name, c, several_files) for c in labels})
        if m is reference and not shifted and step_s is None and window is None:
            for c in part.columns[1:]:
                out[c] = part[c].to_numpy()
            continue
        # Mesure la plus proche, à une période près (ou un pas de grille si plus grand)
        period = m.period_s / 60.0 if np.isfinite(m.period_s) else 0.0
        if percent:
            period = period / max(m.duration_min, 1e-9) * 100.0
        tolerance = max(period, (step_s or 0.0) / 60.0) or None
        merged = pd.merge_asof(
            base, part.sort_values(TIME_COL), on=TIME_COL,
            direction="nearest", tolerance=tolerance,
        )
        for c in part.columns[1:]:
            out[c] = merged[c].to_numpy()

    if percent:
        return out.rename(columns={TIME_COL: PERCENT_COL})
    out.insert(1, "Temps (H:MM:SS)", hms_column(out[TIME_COL].to_numpy()))
    return out


def hms_column(minutes: np.ndarray) -> pd.Series:
    """Version vectorisée de ``format_hms`` (rapide sur des millions de lignes)."""
    total = np.round(np.asarray(minutes, dtype=float) * 60).astype(np.int64)
    sign = pd.Series(np.where(total < 0, "-", ""))
    total = np.abs(total)
    hours = pd.Series(total // 3600).astype(str)
    mins = pd.Series((total % 3600) // 60).astype(str).str.zfill(2)
    secs = pd.Series(total % 60).astype(str).str.zfill(2)
    return sign + hours + ":" + mins + ":" + secs


def write_csv(df: pd.DataFrame, path, decimal: str = ",") -> Path:
    """Écrit le CSV : séparateur « ; », décimale « , » par défaut (Excel français)."""
    path = Path(path)
    df.to_csv(path, sep=";", decimal=decimal, index=False, encoding="utf-8-sig", float_format="%.10g")
    return path


def _column_name(file_name: str, label: str, prefix: bool) -> str:
    return "{} | {}".format(file_name, label) if prefix else label
