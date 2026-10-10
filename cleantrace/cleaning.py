"""US-03 — Nettoyage automatique du bruit de repos et des pics de saturation.

Règles métier :

1. **Bruit de repos** (``chk_noise``) : pendant les phases d'arrêt, tout signal sous le
   seuil physique (< 10 mA, < 5 mV...) est forcé à 0.0.
2. **Pics parasites** (``chk_peaks``) : les groupes d'échantillons étroits (5 points au
   plus) qui s'écartent du niveau local de la courbe (médiane glissante) de beaucoup plus
   que le bruit de mesure sont remplacés par ce niveau local, puis lissés par
   ``gaussian_filter1d``. Le haut du bruit d'un palier réel n'est donc jamais raboté.
   Mode « saturation » (règle d'origine du cahier des charges) : seulement les pics
   au-delà de 98 % du max, qui dépassent aussi l'enveloppe minimale SciPy
   (``minimum_filter1d`` puis ``maximum_filter1d``, ouverture morphologique).

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
    zero_offset: bool = True  # soustraire le décalage de zéro mesuré au repos
    remove_noise: bool = True  # chk_noise
    remove_peaks: bool = True  # chk_peaks
    peak_mode: str = "all"  # "all" : tous les pics étroits ; "saturation" : seulement > saturation_ratio × max
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
    offset: float = 0.0  # décalage de zéro soustrait

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


def estimate_rest_offset(y) -> Optional[float]:
    """Décalage de zéro du capteur : niveau des phases de repos quand il n'est pas exactement 0.

    Le repos est la valeur la plus fréquente de la voie (longues phases d'arrêt). Elle
    n'est considérée comme un décalage que si elle est proche de 0 à l'échelle de la voie
    (moins de 20 % de l'amplitude) et nettement plus grande que le bruit. Une tension
    d'alimentation (24 V permanents) ou un petit courant permanent n'ont donc pas de décalage.
    Renvoie None s'il n'y a rien à corriger.
    """
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < 100:
        return None
    lo, hi = np.percentile(y, [0.5, 99.5])
    if hi <= lo:
        return None
    counts, edges = np.histogram(y[(y >= lo) & (y <= hi)], bins=400)
    k = int(np.argmax(counts))
    mode = 0.5 * (edges[k] + edges[k + 1])
    sigma = max(_noise_sigma(y), (edges[1] - edges[0]))
    near = np.abs(y - mode) < 4 * sigma
    if near.mean() < 0.2:
        return None  # pas de longues phases de repos
    rest = float(np.median(y[near]))
    amplitude = float(max(abs(lo), abs(hi)))
    if abs(rest) >= 0.2 * amplitude or abs(rest) < 3 * sigma:
        return None
    return float("{:.3g}".format(rest))


def clean_signal(
    y, unit: str = "", options: Optional[CleaningOptions] = None, noise_threshold=_DEFAULT,
    offset: Optional[float] = None,
) -> Tuple[np.ndarray, CleaningReport]:
    """Applique les traitements activés à un signal. Renvoie (signal nettoyé, rapport).

    Ordre : décalage de zéro (``offset`` soustrait), pics parasites, bruit de repos.
    ``noise_threshold`` : seuil de bruit de repos de cette voie (dans son unité). Par
    défaut, celui de l'unité (``NOISE_THRESHOLDS``) ; None : pas de mise à 0.
    """
    options = options or CleaningOptions()
    out = np.asarray(y, dtype=float).copy()
    report = CleaningReport()
    if options.zero_offset and offset:
        out -= offset
        report.offset = float(offset)
    # Les pics d'abord : un pic de saturation ne doit pas fausser la détection du repos.
    if options.remove_peaks:
        out, report.peak_points = remove_saturation_peaks(
            out,
            ratio=options.saturation_ratio,
            max_width=options.max_peak_width,
            min_prominence=options.min_prominence,
            sigma=options.smoothing_sigma,
            noise_factor=options.noise_factor,
            saturation_only=options.peak_mode == "saturation",
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
    saturation_only: bool = False,
) -> Tuple[np.ndarray, int]:
    """Supprime les pics parasites (positifs et négatifs) sans toucher au reste du signal.

    Un pic est un groupe d'au plus ``max_width`` points consécutifs qui s'écarte du niveau
    local de la courbe (médiane glissante) de plus de ``noise_factor`` × le bruit de mesure
    ET de plus de ``min_prominence`` × l'amplitude utile de la voie (calculée sans les pics).
    Avec ``saturation_only``, seuls les pics au-delà de ``ratio`` × le maximum (ou le
    minimum) sont concernés — la règle d'origine du cahier des charges.
    """
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

        # Niveau local de la courbe (médiane glissante, insensible à un pic de max_width points)
        level = median_filter(work, size=4 * max_width + 1, mode="nearest")
        if saturation_only:
            amplitude = float(np.max(work) - np.min(work))
        else:  # amplitude utile, sans les pics (sinon un grand pic en masquerait de plus petits)
            amplitude = float(np.percentile(level, 99.9) - np.percentile(level, 0.1))
        prominence = min_prominence * amplitude
        # Écart minimal pour parler de pic : jamais moins de noise_factor × le bruit de mesure,
        # sinon le haut du bruit d'un palier réel serait raboté.
        margin = max(prominence, noise_factor * _noise_sigma(work))
        if margin <= 0:
            break
        deviation = work - level

        if saturation_only:
            high, low = _saturated(work, ratio)
            pos = _narrow(high, max_width) & (work - upper_env > prominence) & (deviation > margin)
            neg = _narrow(low, max_width) & (lower_env - work > prominence) & (-deviation > margin)
        else:
            pos = _confirm_spikes(work, _narrow(deviation > margin, max_width), max_width, margin)
            neg = _confirm_spikes(work, _narrow(-deviation > margin, max_width), max_width, margin)
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


def _confirm_spikes(y: np.ndarray, mask: np.ndarray, width: int, margin: float) -> np.ndarray:
    """Ne garde que les groupes qui s'écartent À LA FOIS des points juste avant et juste après,
    dans le même sens. Un front de créneau ne s'écarte que d'un côté : il n'est jamais touché,
    même si un pic voisin fausse la médiane locale."""
    out = np.zeros_like(mask)
    n = len(y)
    for start, stop in _runs(mask):
        left = y[max(0, start - width):start]
        right = y[stop:min(n, stop + width)]
        if not len(left) or not len(right):
            continue  # au bord du fichier : pas assez de contexte
        run = y[start:stop]
        peak = run[np.argmax(np.abs(run - np.median(np.r_[left, right])))]
        d_left, d_right = peak - np.median(left), peak - np.median(right)
        if abs(d_left) > margin and abs(d_right) > margin and np.sign(d_left) == np.sign(d_right):
            out[start:stop] = True
    return out


def _noise_sigma(y: np.ndarray) -> float:
    """Écart-type du bruit de mesure, estimé de façon robuste sur les différences successives
    (les fronts des créneaux et les pics sont trop rares pour fausser la médiane)."""
    d = np.diff(y)
    if len(d) == 0:
        return 0.0
    mad = float(np.median(np.abs(d - np.median(d))))
    if mad == 0:
        # Valeurs très quantifiées (ex. pas de 0,01, la plupart des points égaux à leur
        # voisin) : le bruit vaut un pas de mesure. Si seuls les fronts varient, le signal
        # est sans bruit (données de synthèse) : bruit nul.
        steps = np.abs(d[d != 0])
        return float(np.min(steps)) if len(steps) > 0.1 * len(d) else 0.0
    return 1.4826 * mad / np.sqrt(2.0)


def _fill_nan(y: np.ndarray, finite: np.ndarray) -> np.ndarray:
    if finite.all():
        return y.copy()
    idx = np.arange(len(y))
    return np.interp(idx, idx[finite], y[finite])
