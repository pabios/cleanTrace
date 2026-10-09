"""État de travail de l'application : fichiers chargés, données brutes et nettoyées.

Cette classe ne dépend pas de Tkinter : toute la logique métier est testable sans IHM.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .cleaning import CleaningOptions, CleaningReport, clean_signal
from .export import Key, merge_selection, write_csv
from .loader import TIME_COL, LoadError, Measurement, align_time_axes, load_measurement
from .plotting import PlotSeries


class Session:
    def __init__(self) -> None:
        self.measurements: "OrderedDict[str, Measurement]" = OrderedDict()
        self._raw: Dict[str, pd.DataFrame] = {}  # copie des données brutes, pour restaurer
        self.reference: Optional[Measurement] = None
        self.time_offset_min = 0.0  # décalage des courbes climatiques (minutes)

    # ----------------------------------------------------------------- fichiers

    def load_files(self, paths: Iterable) -> Tuple[List[Measurement], List[str]]:
        """Charge plusieurs fichiers. Renvoie (fichiers chargés, messages d'erreur)."""
        loaded, errors = [], []
        for path in paths:
            name = self._unique_name(Path(path).name)
            try:
                m = load_measurement(path, name=name)
            except LoadError as exc:
                errors.append(str(exc))
                continue
            self.measurements[m.name] = m
            self._raw[m.name] = m.data.copy()
            loaded.append(m)
        self._realign()
        return loaded, errors

    def remove_file(self, name: str) -> None:
        self.measurements.pop(name, None)
        self._raw.pop(name, None)
        self._realign()

    def clear(self) -> None:
        """Réinitialisation complète : décharge tous les fichiers."""
        self.measurements.clear()
        self._raw.clear()
        self.reference = None
        self.time_offset_min = 0.0

    def all_keys(self) -> List[Key]:
        return [(m.name, ch.label) for m in self.measurements.values() for ch in m.channels]

    @property
    def total_duration_min(self) -> float:
        if not self.measurements:
            return 0.0
        return max(float(np.nanmax(m.data[TIME_COL])) for m in self.measurements.values()) - min(
            float(np.nanmin(m.data[TIME_COL])) for m in self.measurements.values()
        )

    # ---------------------------------------------------------------- traitements

    def apply_cleaning(self, keys: Sequence[Key], options: CleaningOptions) -> CleaningReport:
        total = CleaningReport()
        for name, label in keys:
            m = self.measurements[name]
            ch = m.channel(label)
            cleaned, report = clean_signal(m.data[label].to_numpy(dtype=float), ch.unit, options)
            m.data[label] = cleaned
            total.noise_points += report.noise_points
            total.peak_points += report.peak_points
        return total

    def restore_raw(self, keys: Sequence[Key]) -> None:
        """Annule nettoyages et corrections des voies données."""
        for name, label in keys:
            self.measurements[name].data[label] = self._raw[name][label].to_numpy(copy=True)

    def set_value(self, key: Key, index: int, value: float) -> None:
        """Correction manuelle d'un point (US-05)."""
        name, label = key
        df = self.measurements[name].data
        df.iloc[index, df.columns.get_loc(label)] = value

    # ---------------------------------------------------------------- affichage

    def series(self, keys: Sequence[Key]) -> List[PlotSeries]:
        several_files = len({name for name, _ in keys}) > 1
        out = []
        for i, (name, label) in enumerate(keys):
            m = self.measurements[name]
            ch = m.channel(label)
            out.append(
                PlotSeries(
                    gid=str(i),
                    label="{} — {}".format(label, name) if several_files else label,
                    x=m.data[TIME_COL].to_numpy(dtype=float),
                    y=m.data[label].to_numpy(dtype=float),
                    unit=ch.unit,
                    quantity=ch.quantity,
                    shiftable=m.is_thermal,
                )
            )
        return out

    # ------------------------------------------------------------------- export

    def export_csv(self, path, keys: Sequence[Key]) -> pd.DataFrame:
        if self.reference is None:
            raise ValueError("Aucun fichier chargé.")
        df = merge_selection(
            list(self.measurements.values()), self.reference, keys, self.time_offset_min
        )
        write_csv(df, path)
        return df

    # --------------------------------------------------------------- interne

    def _realign(self) -> None:
        self.reference = align_time_axes(list(self.measurements.values()))
        for name, m in self.measurements.items():
            self._raw[name][TIME_COL] = m.data[TIME_COL].to_numpy(copy=True)

    def _unique_name(self, name: str) -> str:
        if name not in self.measurements:
            return name
        i = 2
        while "{} ({})".format(name, i) in self.measurements:
            i += 1
        return "{} ({})".format(name, i)
