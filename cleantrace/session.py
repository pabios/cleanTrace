"""État de travail de l'application : fichiers chargés, données brutes et nettoyées.

Cette classe ne dépend pas de Tkinter : toute la logique métier est testable sans IHM.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .cleaning import (
    CleaningOptions, CleaningReport, clean_signal, default_noise_threshold, has_rest_phase,
    suggest_noise_threshold,
)
from .editing import interpolate_at
from .export import Key, merge_selection, write_csv
from .loader import TIME_COL, LoadError, Measurement, align_time_axes, load_measurement
from .plotting import PlotSeries


# Bases de temps pour superposer plusieurs fichiers
TIME_MODES = OrderedDict([
    ("real", "Heure réelle"),  # chaque mesure à son heure (même essai, appareils à l'heure)
    ("common", "Période commune"),  # uniquement la période où tous les fichiers mesurent
    ("zero", "Débuts à 0"),  # chaque fichier démarre à 0 (horloges pas à l'heure)
    ("stretch", "Durée étirée (0-100 %)"),  # chaque fichier de 0 à 100 % de sa durée
])

# Grilles d'export proposées (None : celle du fichier de référence)
EXPORT_STEPS = OrderedDict([
    (None, "Grille du fichier de référence"),
    (0.1, "100 ms"),
    (1.0, "1 s"),
    (10.0, "10 s"),
    (60.0, "1 min"),
])


class Session:
    def __init__(self) -> None:
        self.measurements: "OrderedDict[str, Measurement]" = OrderedDict()
        self._raw: Dict[str, pd.DataFrame] = {}  # copie des données brutes, pour restaurer
        self.reference: Optional[Measurement] = None
        self.time_offset_min = 0.0  # décalage des courbes climatiques (minutes)
        self.time_mode = "real"
        self.window: Optional[Tuple[float, float]] = None  # période commune (minutes)
        self.export_step_s: Optional[float] = None
        self.noise_thresholds: Dict[Key, Optional[float]] = {}  # seuils de bruit réglés par voie

    # ----------------------------------------------------------------- fichiers

    def load_files(
        self, paths: Iterable, progress: Optional[Callable[[str], None]] = None
    ) -> Tuple[List[Measurement], List[Tuple[Path, str]]]:
        """Charge plusieurs fichiers. Renvoie (fichiers chargés, [(chemin, message d'erreur)])."""
        loaded, errors = self.read_files(paths, progress)
        self.add_measurements(loaded)
        return loaded, errors

    def read_files(
        self, paths: Iterable, progress: Optional[Callable[[str], None]] = None
    ) -> Tuple[List[Measurement], List[Tuple[Path, str]]]:
        """Lit les fichiers sans modifier la session (peut tourner en arrière-plan).

        Renvoie (fichiers chargés, [(chemin, message d'erreur)]).
        """
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
                errors.append((Path(path), str(exc)))
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
        self.window = None
        self.noise_thresholds.clear()

    def set_time_mode(self, mode: str) -> None:
        if mode not in TIME_MODES:
            raise ValueError(mode)
        self.time_mode = mode
        self._realign()

    @property
    def percent_axis(self) -> bool:
        """Axe du temps en % de la durée (mode « étiré ») au lieu de minutes."""
        return self.time_mode == "stretch"

    @property
    def window_start(self) -> Optional[pd.Timestamp]:
        """Heure réelle du début de la période commune."""
        if self.window is None or self.reference is None or self.reference.start is None:
            return None
        return self.reference.start + pd.Timedelta(minutes=self.window[0])

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

    def noise_threshold(self, key: Key) -> Optional[float]:
        """Seuil de bruit de repos de la voie : réglé par l'utilisateur, sinon celui de l'unité.

        Par défaut, une voie qui ne revient jamais à 0 (petit courant permanent, tension
        d'alimentation...) n'est pas mise à 0 : le seuil de l'unité effacerait de vraies mesures.
        """
        if key in self.noise_thresholds:
            return self.noise_thresholds[key]
        if not self.has_rest_phase(key):
            return None
        return default_noise_threshold(self.measurements[key[0]].channel(key[1]).unit)

    def has_rest_phase(self, key: Key) -> bool:
        return has_rest_phase(self.measurements[key[0]].data[key[1]].to_numpy(dtype=float))

    def suggest_noise_threshold(self, key: Key) -> Optional[float]:
        return suggest_noise_threshold(self.measurements[key[0]].data[key[1]].to_numpy(dtype=float))

    def preview_cleaning(
        self, keys: Sequence[Key], options: CleaningOptions, thresholds: Optional[Dict[Key, Optional[float]]] = None
    ) -> Dict[Key, CleaningReport]:
        """Nombre de points que le nettoyage modifierait, voie par voie (sans rien modifier)."""
        out = {}
        for key in keys:
            m = self.measurements[key[0]]
            threshold = (thresholds or {}).get(key, self.noise_threshold(key))
            _, out[key] = clean_signal(m.data[key[1]].to_numpy(dtype=float), m.channel(key[1]).unit,
                                       options, noise_threshold=threshold)
        return out

    def apply_cleaning(
        self, keys: Sequence[Key], options: CleaningOptions, thresholds: Optional[Dict[Key, Optional[float]]] = None
    ) -> CleaningReport:
        """US-03 : nettoie les voies. ``thresholds`` : seuils de bruit par voie (mémorisés)."""
        if thresholds:
            self.noise_thresholds.update(thresholds)
        total = CleaningReport()
        for key in keys:
            name, label = key
            m = self.measurements[name]
            ch = m.channel(label)
            cleaned, report = clean_signal(m.data[label].to_numpy(dtype=float), ch.unit, options,
                                           noise_threshold=self.noise_threshold(key))
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
            x = m.data[TIME_COL].to_numpy(dtype=float)
            y = m.data[label].to_numpy(dtype=float)
            first = 0
            if self.window is not None:  # période commune : on ne garde que la fenêtre
                first = int(np.searchsorted(x, self.window[0] - 1e-9))
                last = int(np.searchsorted(x, self.window[1] + 1e-9, side="right"))
                x, y = x[first:last], y[first:last]
            out.append(
                PlotSeries(
                    gid=str(i),
                    label="{} — {}".format(label, name) if several_files else label,
                    x=x,
                    y=y,
                    unit=ch.unit,
                    quantity=ch.quantity,
                    shiftable=m.is_thermal and not self.percent_axis,
                    index_base=first,
                )
            )
        return out

    # ------------------------------------------------------------------- export

    def export_csv(self, path, keys: Sequence[Key]) -> pd.DataFrame:
        if self.reference is None:
            raise ValueError("Aucun fichier chargé.")
        df = merge_selection(
            list(self.measurements.values()), self.reference, keys, self.time_offset_min,
            window=self.window, step_s=self.export_step_s, percent=self.percent_axis,
        )
        write_csv(df, path)
        return df

    # --------------------------------------------------------------- interne

    def _realign(self) -> None:
        measurements = list(self.measurements.values())
        self.reference = align_time_axes(measurements)  # heure réelle
        self.window = None
        if self.time_mode == "zero":
            for m in measurements:
                m.data[TIME_COL] = m.elapsed_min
                m.align_note = ""
        elif self.time_mode == "stretch":
            for m in measurements:
                m.data[TIME_COL] = m.elapsed_min / max(m.duration_min, 1e-9) * 100.0
                m.align_note = ""
        elif self.time_mode == "common":
            self.window = self._common_window(measurements)
        for name, m in self.measurements.items():
            self._raw[name][TIME_COL] = m.data[TIME_COL].to_numpy(copy=True)


    @staticmethod
    def _common_window(measurements) -> Optional[Tuple[float, float]]:
        """Période où tous les fichiers recalés sur l'heure réelle mesurent en même temps."""
        aligned = [m for m in measurements if not m.align_note and len(m.data)]
        if len(aligned) < 2:
            return None
        start = max(float(m.data[TIME_COL].iloc[0]) for m in aligned)
        end = min(float(m.data[TIME_COL].iloc[-1]) for m in aligned)
        return (start, end) if end > start else None


def _unique_name(name: str, taken) -> str:
    if name not in taken:
        return name
    i = 2
    while "{} ({})".format(name, i) in taken:
        i += 1
    return "{} ({})".format(name, i)
