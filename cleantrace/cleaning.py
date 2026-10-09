"""US-03 — Nettoyage automatique du bruit de repos et des pics de saturation.

Règles métier :

1. **Bruit de repos** (``chk_noise``) : pendant les phases d'arrêt, tout signal sous le
   seuil physique (< 10 mA, < 5 mV...) est forcé à 0.0.
2. **Pics de saturation** (``chk_peaks``) : les groupes d'échantillons étroits proches du
   plafond de mesure (> 98 % du max) sont remplacés par l'enveloppe minimale SciPy
   (``minimum_filter1d`` suivi de ``maximum_filter1d``, c'est-à-dire une ouverture
   morphologique), puis lissés par ``gaussian_filter1d``.

Garanties (critères d'acceptation) :

* seuls les échantillons parasites sont modifiés : un créneau de courant reste un créneau
  (aucune pente, aucune droite) ;
* un plateau réel au maximum est plus large qu'un pic parasite et n'est jamais touché,
  donc la valeur maximale initiale et la valeur minimale finale de chaque cycle sont
  conservées.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from scipy.ndimage import gaussian_filter1d, maximum_filter1d, minimum_filter1d

# Seuils physiques du bruit de repos, par unité
NOISE_THRESHOLDS = {
    "A": 0.010,
    "mA": 10.0,
    "µA": 10000.0,
    "V": 0.005,
    "mV": 5.0,
}


@dataclass
class CleaningOptions:
    remove_noise: bool = True  # chk_noise
    remove_peaks: bool = True  # chk_peaks
    saturation_ratio: float = 0.98  # seuil "proche du plafond" (fraction du max)
    max_peak_width: int = 5  # largeur max d'un pic parasite (échantillons)
    min_prominence: float = 0.05  # hauteur min d'un pic au-dessus de l'enveloppe (fraction de l'amplitude)
    smoothing_sigma: float = 1.0  # lissage gaussien des points réparés (échantillons)
    min_rest_samples: int = 3  # durée min d'une phase d'arrêt (échantillons)


@dataclass
class CleaningReport:
    noise_points: int = 0
    peak_points: int = 0

    @property
    def total(self) -> int:
        return self.noise_points + self.peak_points


def clean_signal(
    y, unit: str = "", options: Optional[CleaningOptions] = None
) -> Tuple[np.ndarray, CleaningReport]:
    """Applique les traitements activés à un signal. Renvoie (signal nettoyé, rapport)."""
    options = options or CleaningOptions()
    out = np.asarray(y, dtype=float).copy()
    report = CleaningReport()
    # Les pics d'abord : un pic de saturation ne doit pas fausser la détection du repos.
    if options.remove_peaks:
        out, report.peak_points = remove_saturation_peaks(
            out,
            ratio=options.saturation_ratio,
            max_width=options.max_peak_width,
            min_prominence=options.min_prominence,
            sigma=options.smoothing_sigma,
        )
    if options.remove_noise:
        out, report.noise_points = zero_rest_noise(
            out, unit, min_samples=options.min_rest_samples
        )
    return out, report


def zero_rest_noise(
    y, unit: str, threshold: Optional[float] = None, min_samples: int = 3, max_gap: int = 2
) -> Tuple[np.ndarray, int]:
    """Force à 0.0 le bruit de repos : |y| < seuil pendant au moins ``min_samples`` points.

    Sans seuil connu pour l'unité (°C, %HR...), le signal est renvoyé inchangé.
    """
    out = np.asarray(y, dtype=float).copy()
    if threshold is None:
        threshold = NOISE_THRESHOLDS.get(unit)
    if threshold is None:
        return out, 0
    quiet = np.abs(out) < threshold  # NaN -> False
    # Une phase d'arrêt n'est pas interrompue par 1 ou 2 points de bruit à peine
    # au-dessus du seuil (< 2 × seuil), encadrés de repos des deux côtés.
    near = np.abs(out) < 2 * threshold
    for start, stop in _runs(~quiet):
        if 0 < start and stop < len(out) and stop - start <= max_gap and near[start:stop].all():
            quiet[start:stop] = True
    mask = np.zeros_like(quiet)
    for start, stop in _runs(quiet):
        if stop - start >= min_samples:
            mask[start:stop] = True
    mask &= out != 0.0
    out[mask] = 0.0
    return out, int(mask.sum())


def remove_saturation_peaks(
    y,
    ratio: float = 0.98,
    max_width: int = 5,
    min_prominence: float = 0.05,
    sigma: float = 1.0,
    max_iter: int = 5,
) -> Tuple[np.ndarray, int]:
    """Supprime les pics de saturation (positifs et négatifs) sans toucher au reste du signal."""
    out = np.asarray(y, dtype=float).copy()
    finite = np.isfinite(out)
    if finite.sum() < 3:
        return out, 0

    work = _fill_nan(out, finite)
    size = 2 * max_width + 1
    repaired = np.zeros(len(work), dtype=bool)

    for _ in range(max_iter):
        # Enveloppes SciPy : l'ouverture (min puis max) efface les pics positifs plus
        # étroits que la fenêtre ; la fermeture (max puis min) efface les pics négatifs.
        # Les plateaux plus larges que la fenêtre sont conservés tels quels.
        upper_env = maximum_filter1d(minimum_filter1d(work, size, mode="nearest"), size, mode="nearest")
        lower_env = minimum_filter1d(maximum_filter1d(work, size, mode="nearest"), size, mode="nearest")

        amplitude = float(np.max(work) - np.min(work))
        if amplitude == 0:
            break
        prominence = min_prominence * amplitude

        high, low = _saturated(work, ratio)
        pos = _narrow(high, max_width) & (work - upper_env > prominence)
        neg = _narrow(low, max_width) & (lower_env - work > prominence)
        if not (pos.any() or neg.any()):
            break
        work[pos] = upper_env[pos]
        work[neg] = lower_env[neg]
        repaired |= pos | neg

    if repaired.any() and sigma > 0:
        # Léger lissage gaussien des seuls points réparés, pour les fondre dans la courbe
        smoothed = gaussian_filter1d(work, sigma, mode="nearest")
        work[repaired] = smoothed[repaired]

    # Trous courts (valeurs hors échelle « +++++++ » de la centrale) : comblés par
    # interpolation avec les voisins. Les longues absences de mesure restent vides.
    short_gaps = _narrow(~finite, max_width)
    short_gaps[: np.argmax(finite)] = False
    short_gaps[len(finite) - np.argmax(finite[::-1]):] = False
    work[~finite & ~short_gaps] = np.nan
    return work, int(repaired.sum() + short_gaps.sum())


# ----------------------------------------------------------------------- utilitaires


def _saturated(y: np.ndarray, ratio: float) -> Tuple[np.ndarray, np.ndarray]:
    """Échantillons proches du plafond positif et du plancher négatif."""
    top, bottom = float(np.max(y)), float(np.min(y))
    high = (y > ratio * top) if top > 0 else np.zeros(len(y), dtype=bool)
    low = (y < ratio * bottom) if bottom < 0 else np.zeros(len(y), dtype=bool)
    return high, low


def _narrow(mask: np.ndarray, max_width: int) -> np.ndarray:
    """Ne garde que les groupes consécutifs de ``max_width`` points au plus."""
    out = np.zeros_like(mask)
    for start, stop in _runs(mask):
        if stop - start <= max_width:
            out[start:stop] = True
    return out


def _runs(mask: np.ndarray):
    """Intervalles [début, fin[ des suites de True."""
    padded = np.concatenate(([False], np.asarray(mask, dtype=bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return zip(edges[::2], edges[1::2])


def _fill_nan(y: np.ndarray, finite: np.ndarray) -> np.ndarray:
    if finite.all():
        return y.copy()
    idx = np.arange(len(y))
    return np.interp(idx, idx[finite], y[finite])
