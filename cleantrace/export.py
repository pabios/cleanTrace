"""US-06 — Export des données sélectionnées et nettoyées en CSV (séparateur « ; »).

Les fichiers n'ont pas la même période d'échantillonnage : les voies de chaque fichier
sont fusionnées sur la colonne commune ``Time_min`` du fichier de référence, en prenant
pour chaque instant la mesure la plus proche (``pandas.merge_asof``, tolérance d'une
période d'échantillonnage). Hors de la plage d'un fichier, les cellules restent vides.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

from .loader import TIME_COL, Measurement
from .plotting import format_hms

Key = Tuple[str, str]  # (nom du fichier, libellé de la voie)


def merge_selection(
    measurements: Sequence[Measurement],
    reference: Measurement,
    keys: Sequence[Key],
    time_offset_min: float = 0.0,
) -> pd.DataFrame:
    """Table unique : Time_min, Temps (H:MM:SS), puis une colonne par voie sélectionnée."""
    if not keys:
        raise ValueError("Aucune voie sélectionnée.")
    by_name: Dict[str, Measurement] = {m.name: m for m in measurements}
    wanted: Dict[str, List[str]] = {}
    for name, label in keys:
        wanted.setdefault(name, []).append(label)

    base = pd.DataFrame({TIME_COL: reference.data[TIME_COL].to_numpy(dtype=float)})
    out = base.copy()
    several_files = len(wanted) > 1

    for name, labels in wanted.items():
        m = by_name[name]
        # Les voies climatiques sont décalées comme à l'écran
        groups = {
            False: [lb for lb in labels if not m.channel(lb).is_climatic],
            True: [lb for lb in labels if m.channel(lb).is_climatic],
        }
        for shifted, cols in groups.items():
            if not cols:
                continue
            part = m.data[[TIME_COL] + cols].copy()
            if shifted:
                part[TIME_COL] = part[TIME_COL] + time_offset_min
            part = part.rename(columns={c: _column_name(name, c, several_files) for c in cols})
            if m is reference and not shifted:
                for c in cols:
                    out[_column_name(name, c, several_files)] = part[_column_name(name, c, several_files)].to_numpy()
                continue
            tolerance = m.period_s / 60.0 if np.isfinite(m.period_s) else None
            merged = pd.merge_asof(
                base, part.sort_values(TIME_COL), on=TIME_COL,
                direction="nearest", tolerance=tolerance,
            )
            for c in part.columns:
                if c != TIME_COL:
                    out[c] = merged[c].to_numpy()

    out.insert(1, "Temps (H:MM:SS)", [format_hms(t) for t in out[TIME_COL]])
    return out


def write_csv(df: pd.DataFrame, path, decimal: str = ",") -> Path:
    """Écrit le CSV : séparateur « ; », décimale « , » par défaut (Excel français)."""
    path = Path(path)
    df.to_csv(path, sep=";", decimal=decimal, index=False, encoding="utf-8-sig", float_format="%.10g")
    return path


def _column_name(file_name: str, label: str, prefix: bool) -> str:
    return "{} | {}".format(file_name, label) if prefix else label
