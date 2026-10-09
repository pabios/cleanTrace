"""État de travail de l'application : fichiers chargés, données brutes et nettoyées.

Cette classe ne dépend pas de Tkinter : toute la logique métier est testable sans IHM.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .cleaning import CleaningOptions, CleaningReport, clean_signal
from .editing import interpolate_at
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

    def load_files(
        self, paths: Iterable, progress: Optional[Callable[[str], None]] = None
    ) -> Tuple[List[Measurement], List[str]]:
        """Charge plusieurs fichiers. Renvoie (fichiers chargés, messages d'erreur)."""
        loaded, errors = self.read_files(paths, progress)
        self.add_measurements(loaded)
        return loaded, errors

    def read_files(
        self, paths: Iterable, progress: Optional[Callable[[str], None]] = None
    ) -> Tuple[List[Measurement], List[str]]:
        """Lit les fichiers sans modifier la session (peut tourner en arrière-plan)."""
        paths = list(paths)
        loaded, errors = [], []
        taken = set(self.measurements)
        for i, path in enumerate(paths, start=1):
            name = _unique_name(Path(path).name, taken)
            taken.add(name)
            prefix = "Fichier {}/{} — ".format(i, len(paths)) if len(paths) > 1 else ""
            report = (lambda msg, p=prefix: progress(p + msg)) if progress else None
            try:
                loaded.append(load_measurement(path, name=name, progress=report))
            except LoadError as exc:
                errors.append(str(exc))
        return loaded, errors

    def add_measurements(self, measurements: Sequence[Measurement]) -> None:
        for m in measurements:
            self.measurements[m.name] = m
            self._raw[m.name] = m.data.copy()
        self._realign()

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

    def correct_point(self, key: Key, index: int) -> float:
        """US-05 : remplace le point ``index`` par l'interpolation de ses voisins."""
        name, label = key
        df = self.measurements[name].data
        value = interpolate_at(df[TIME_COL].to_numpy(), df[label].to_numpy(), index)
        self.set_value(key, index, value)
        return value

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



def _unique_name(name: str, taken) -> str:
    if name not in taken:
        return name
    i = 2
    while "{} ({})".format(name, i) in taken:
        i += 1
    return "{} ({})".format(name, i)
