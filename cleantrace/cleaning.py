"""US-03 — Nettoyage automatique du bruit de repos et des pics de saturation.

Règles métier :

1. **Bruit de repos** (``chk_noise``) : pendant les phases d'arrêt, tout signal sous le
   seuil physique (< 10 mA, < 5 mV...) est forcé à 0.0.
2. **Pics de saturation** (``chk_peaks``) : les groupes d'échantillons étroits proches du
   plafond de mesure (> 98 % du max) qui dépassent l'enveloppe minimale SciPy
   (``minimum_filter1d`` suivi de ``maximum_filter1d``, c'est-à-dire une ouverture
   morphologique) ET le niveau local de la courbe de beaucoup plus que le bruit de
   mesure, sont remplacés par ce niveau local (médiane glissante), puis lissés par
   ``gaussian_filter1d``. Le haut du bruit d'un palier réel n'est donc jamais raboté.

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
from scipy.ndimage import gaussian_filter1d, maximum_filter1d, median_filter, minimum_filter1d

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
    noise_factor: float = 8.0  # ... et au-dessus du niveau local (multiple du bruit de mesure)
    smoothing_sigma: float = 1.0  # lissage gaussien des points réparés (échantillons)
    min_rest_samples: int = 3  # durée min d'une phase d'arrêt (échantillons)


@dataclass
class CleaningReport:
    noise_points: int = 0
    peak_points: int = 0

    @property
    def total(self) -> int:
        return self.noise_points + self.peak_points


_DEFAULT = object()


def default_noise_threshold(unit: str) -> Optional[float]:
    """Seuil de bruit de repos par défaut pour une unité (None : pas de mise à 0)."""
    return NOISE_THRESHOLDS.get(unit)


def _rest_values(y, min_rest_fraction: float = 0.02) -> Optional[np.ndarray]:
    """|valeurs| des points « au repos » (à moins de 5 % de l'amplitude autour de 0),
    ou None si la voie ne revient pas (assez) à 0."""
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < 10:
        return None
    amplitude = float(np.max(np.abs(y)))
    if amplitude == 0:
        return None
    rest = np.abs(y[np.abs(y) < 0.05 * amplitude])
    return rest if len(rest) >= min_rest_fraction * len(y) else None


def has_rest_phase(y) -> bool:
    """La voie a-t-elle des phases d'arrêt autour de 0 ? (sinon : ne jamais forcer à 0)"""
    return _rest_values(y) is not None


def suggest_noise_threshold(y, min_rest_fraction: float = 0.02) -> Optional[float]:
    """Seuil proposé d'après les données : 1,5 × le bruit mesuré pendant les repos à 0.

    Les points « au repos » sont ceux à moins de 5 % de l'amplitude de la voie autour
    de 0. S'il y en a trop peu (voie qui ne revient jamais à 0, petit courant permanent),
    aucun seuil n'est proposé : mettre à 0 détruirait de vraies mesures.
    """
    rest = _rest_values(y, min_rest_fraction)
    if rest is None:
        return None
    rest = rest[rest > 0]  # repos déjà nettoyé (zéros exacts) : on mesure ce qui reste
    if len(rest) == 0:
        return None
    noise = float(np.percentile(rest, 99.5))
    if noise == 0:
        return None
    value = 1.5 * noise
    return float("{:.2g}".format(value))


def clean_signal(
    y, unit: str = "", options: Optional[CleaningOptions] = None, noise_threshold=_DEFAULT
) -> Tuple[np.ndarray, CleaningReport]:
    """Applique les traitements activés à un signal. Renvoie (signal nettoyé, rapport).

    ``noise_threshold`` : seuil de bruit de repos de cette voie (dans son unité). Par
    défaut, celui de l'unité (``NOISE_THRESHOLDS``) ; None : pas de mise à 0.
    """
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
            noise_factor=options.noise_factor,
        )
    if options.remove_noise:
        threshold = default_noise_threshold(unit) if noise_threshold is _DEFAULT else noise_threshold
        if threshold:
            out, report.noise_points = zero_rest_noise(
                out, unit, threshold=threshold, min_samples=options.min_rest_samples
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
    noise_factor: float = 8.0,
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
        # Niveau local de la courbe (médiane glissante, insensible à un pic de 5 points) et
        # écart minimal pour parler de pic : jamais moins de noise_factor × le bruit de mesure,
        # sinon le haut du bruit d'un palier réel serait raboté.
        level = median_filter(work, size=4 * max_width + 1, mode="nearest")
        margin = max(prominence, noise_factor * _noise_sigma(work))

        high, low = _saturated(work, ratio)
        pos = _narrow(high, max_width) & (work - upper_env > prominence) & (work - level > margin)
        neg = _narrow(low, max_width) & (lower_env - work > prominence) & (level - work > margin)
        if not (pos.any() or neg.any()):
            break
        work[pos | neg] = level[pos | neg]
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


def _noise_sigma(y: np.ndarray) -> float:
    """Écart-type du bruit de mesure, estimé de façon robuste sur les différences successives
    (les fronts des créneaux et les pics sont trop rares pour fausser la médiane)."""
    d = np.diff(y)
    if len(d) == 0:
        return 0.0
    mad = float(np.median(np.abs(d - np.median(d))))
    return 1.4826 * mad / np.sqrt(2.0)


def _fill_nan(y: np.ndarray, finite: np.ndarray) -> np.ndarray:
    if finite.all():
        return y.copy()
    idx = np.arange(len(y))
    return np.interp(idx, idx[finite], y[finite])
