"""US-01 — Import et normalisation des fichiers de mesure multi-formats.

Chaque centrale d'acquisition (Graphtec, Nanodac, Graphset, enceinte climatique...)
produit des fichiers CSV/TXT/DAT différents. Ce module détecte automatiquement :

* l'encodage (utf-8, cp1252, latin-1) ;
* le séparateur (";", tabulation, ",") et le séparateur décimal ;
* la ligne d'en-tête (en ignorant le préambule éventuel de la centrale) ;
* la colonne temps (date/heure absolue, durée H:MM:SS, ou temps écoulé en ms / s / min) ;
* la période d'échantillonnage.

Tous les fichiers sont ensuite ramenés sur un axe temps commun ``Time_min`` (en minutes),
calculé par rapport au fichier de référence (Graphset, sinon le fichier le plus long).
"""
from __future__ import annotations

import csv
import math
import re
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .channels import Channel, make_channel, normalize_unit, split_name_unit

TIME_COL = "Time_min"

ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
SEPARATORS = ("\t", ";", ",")  # par ordre de priorité ("," peut être un décimal)
SEPARATOR_NAMES = {"\t": "tabulation", ";": "point-virgule", ",": "virgule"}

_TIME_NAME_RE = re.compile(
    r"(time|temps|date|heure|hour|elapsed|dur[ée]e|horodat|timestamp|^t$)", re.IGNORECASE
)
_DATE_ONLY_NAME_RE = re.compile(r"^date$", re.IGNORECASE)
_SUBSECOND_NAME_RE = re.compile(r"^(ms|msec|us|µs)$", re.IGNORECASE)
_SUBSECOND_FACTOR = {"ms": 1e-3, "msec": 1e-3, "us": 1e-6, "µs": 1e-6}
# Valeurs hors échelle écrites par les centrales à la place d'un nombre
_OVER_RANGE_RE = re.compile(r"^([+\-])\1{2,}$|^(burnout|over|under|overrange|underrange|-?ovf|err)$", re.IGNORECASE)
_INDEX_NAME_RE = re.compile(r"^(no\.?|n°|num(ber|[ée]ro)?|index|#|id|ligne)$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$")
_DECIMAL_COMMA_RE = re.compile(r"^[+-]?\d*,\d+([eE][+-]?\d+)?$")
_DATETIME_LIKE_RE = re.compile(r"^\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}|^\d{1,3}:\d{2}")
_DURATION_RE = re.compile(r"^\d+:\d{2}:\d{2}([.,]\d+)?$")
_YEAR_FIRST_RE = re.compile(r"^\d{4}[/\-.]")
_TIME_UNITS_S = {"ms": 1e-3, "msec": 1e-3, "s": 1.0, "sec": 1.0, "min": 60.0, "h": 3600.0}

_SOURCES = (
    ("graphset", "Graphset"),
    ("graphtec", "Graphtec"),
    ("nanodac", "Nanodac"),
    ("clim", "Clim"),
    ("enceinte", "Clim"),
)


class LoadError(Exception):
    """Fichier illisible ou non conforme. Le message est destiné à l'utilisateur."""


@dataclass
class Measurement:
    """Un fichier de mesure chargé et normalisé."""

    name: str  # nom affiché (nom du fichier, rendu unique)
    path: Path
    source: str  # type de centrale détecté : Graphtec, Nanodac, Graphset, Clim, Générique
    encoding: str
    separator: str
    decimal: str
    channels: List[Channel]
    data: pd.DataFrame  # colonne Time_min + une colonne par voie (libellés nettoyés)
    elapsed_min: np.ndarray  # temps écoulé depuis le début du fichier (minutes)
    period_s: float  # période d'échantillonnage détectée
    start: Optional[pd.Timestamp] = None  # horodatage absolu du 1er point, si disponible
    align_offset_min: float = 0.0  # décalage appliqué pour l'axe commun
    warnings: List[str] = field(default_factory=list)

    @property
    def duration_min(self) -> float:
        return float(self.elapsed_min[-1]) if len(self.elapsed_min) else 0.0

    @property
    def is_thermal(self) -> bool:
        """Fichier d'enceinte climatique : uniquement des voies °C / %HR (ex. nanodac).

        Ses courbes suivent le curseur de décalage temporel (retard du banc thermique).
        """
        return all(ch.is_climatic for ch in self.channels)

    @property
    def period_label(self) -> str:
        return format_period(self.period_s)

    def channel(self, label: str) -> Channel:
        for ch in self.channels:
            if ch.label == label:
                return ch
        raise KeyError(label)


# --------------------------------------------------------------------------- API


def load_measurement(path, name: Optional[str] = None) -> Measurement:
    """Charge un fichier de mesure. Lève :class:`LoadError` si le fichier est non conforme."""
    path = Path(path)
    try:
        return _load(path, name or path.name)
    except LoadError:
        raise
    except Exception as exc:  # pragma: no cover - filet de sécurité
        raise LoadError(
            "Le fichier « {} » n'a pas pu être lu : {}".format(path.name, exc)
        ) from exc


def choose_reference(measurements: Sequence[Measurement]) -> Optional[Measurement]:
    """Fichier de référence : le Graphset s'il existe, sinon le fichier le plus long."""
    if not measurements:
        return None
    for m in measurements:
        if m.source == "Graphset":
            return m
    return max(measurements, key=lambda m: m.duration_min)


def align_time_axes(measurements: Sequence[Measurement]) -> Optional[Measurement]:
    """Recalcule ``Time_min`` de chaque fichier par rapport au fichier de référence.

    Si les fichiers sont horodatés, leurs débuts sont recalés sur celui de la référence ;
    sinon chaque fichier démarre à 0.
    """
    ref = choose_reference(measurements)
    for m in measurements:
        offset = 0.0
        if ref is not None and m.start is not None and ref.start is not None:
            offset = (m.start - ref.start).total_seconds() / 60.0
        m.align_offset_min = offset
        m.data[TIME_COL] = m.elapsed_min + offset
    return ref


def format_period(seconds: float) -> str:
    """Période lisible : "500 ms", "1 s", "10 s", "1 min"."""
    if not seconds or not math.isfinite(seconds):
        return "?"
    if seconds < 1:
        return "{:g} ms".format(round(seconds * 1000, 3))
    if seconds < 60:
        return "{:g} s".format(round(seconds, 3))
    return "{:g} min".format(round(seconds / 60, 3))


# ------------------------------------------------------------------ implémentation


def _load(path: Path, name: str) -> Measurement:
    if not path.is_file():
        raise LoadError("Fichier introuvable : {}".format(path))

    text, encoding = _read_text(path)
    lines = [line for line in text.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    if not any(line.strip() for line in lines):
        raise LoadError("Le fichier « {} » est vide.".format(path.name))

    sep = _detect_separator(lines, path.name)
    rows = list(csv.reader(lines, delimiter=sep))
    n_cols = _modal_field_count(rows)
    decimal = _detect_decimal(rows, sep, n_cols)

    first_data = _find_first_data_row(rows, n_cols, decimal)
    if first_data is None:
        raise LoadError(
            "Le fichier « {} » ne contient pas de données numériques exploitables "
            "(aucune ligne de mesure reconnue).".format(path.name)
        )
    headers, units = _find_headers(rows, first_data, n_cols, decimal)
    signal_names = _graphtec_amp_settings(rows[:first_data])
    for col, (_, unit) in signal_names.items():
        units.setdefault(col, unit)

    data_rows = [r for r in rows[first_data:] if len(r) == n_cols]
    skipped = len(rows) - first_data - len(data_rows)
    raw = pd.DataFrame(data_rows, columns=headers)
    raw = raw.apply(lambda s: s.str.strip().str.strip('"'))

    time_s, start, used_cols = _extract_time(raw, decimal, path.name)

    # Voies de mesure : toutes les autres colonnes numériques
    channels: List[Channel] = []
    values = {}
    over_range = 0
    for col in raw.columns:
        if col in used_cols or _INDEX_NAME_RE.match(col.strip()) or not col.strip():
            continue
        numeric = _to_numeric(raw[col], decimal)
        if numeric.notna().sum() == 0:
            continue  # colonne de texte (alarmes, messages...)
        over_range += int(raw[col].str.match(_OVER_RANGE_RE).sum())
        alias = signal_names.get(col, ("", ""))[0]
        ch = make_channel(col, units.get(col), alias=alias)
        label = _unique(ch.label, values)
        if label != ch.label:
            ch = Channel(ch.raw_name, label, ch.unit, ch.quantity)
        channels.append(ch)
        values[label] = numeric.to_numpy(dtype=float)

    if not channels:
        raise LoadError(
            "Le fichier « {} » ne contient aucune voie de mesure numérique "
            "en plus de la colonne temps.".format(path.name)
        )

    df = pd.DataFrame(values)
    df.insert(0, "_t", time_s)
    df = df[np.isfinite(df["_t"].to_numpy())]
    if df.empty:
        raise LoadError("La colonne temps du fichier « {} » est illisible.".format(path.name))

    msgs = []
    if skipped:
        msgs.append("{} ligne(s) hors tableau ignorée(s) (messages, lignes incomplètes).".format(skipped))
    if over_range:
        msgs.append("{} valeur(s) hors échelle (+++++++, BURNOUT...) laissées vides : "
                    "« Nettoyer » répare les plus courtes.".format(over_range))
    if not df["_t"].is_monotonic_increasing:
        df = df.sort_values("_t", kind="mergesort")
        msgs.append("Points remis dans l'ordre chronologique.")
    df = df.reset_index(drop=True)

    elapsed_min = (df.pop("_t").to_numpy(dtype=float)) / 60.0
    df.insert(0, TIME_COL, elapsed_min.copy())
    period_s = _sampling_period(elapsed_min * 60.0)

    return Measurement(
        name=name,
        path=path,
        source=_guess_source(path.name, lines[:first_data]),
        encoding=encoding,
        separator=sep,
        decimal=decimal,
        channels=channels,
        data=df,
        elapsed_min=elapsed_min,
        period_s=period_s,
        start=start,
        warnings=msgs,
    )


def _read_text(path: Path) -> Tuple[str, str]:
    raw = path.read_bytes()
    if b"\x00" in raw[:4096] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise LoadError(
            "Le fichier « {} » semble être un fichier binaire, pas un export texte "
            "(CSV/TXT/DAT).".format(path.name)
        )
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), "utf-8" if enc == "utf-8-sig" else enc
        except UnicodeDecodeError:
            continue
    raise LoadError("Encodage du fichier « {} » non reconnu.".format(path.name))  # pragma: no cover


def _detect_separator(lines: List[str], filename: str) -> str:
    # Les dernières lignes sont des données : le préambule de la centrale ne compte pas.
    sample = [line for line in lines if line.strip()][-200:]
    for sep in SEPARATORS:
        counts = [len(r) for r in csv.reader(sample, delimiter=sep)]
        value, freq = Counter(counts).most_common(1)[0]
        if value >= 2 and freq >= 0.6 * len(counts):
            return sep
    raise LoadError(
        "Impossible de détecter le séparateur de colonnes du fichier « {} » "
        "(attendu : « ; », « , » ou tabulation, avec au moins une colonne temps "
        "et une voie de mesure).".format(filename)
    )


def _modal_field_count(rows: List[List[str]]) -> int:
    tail = [len(r) for r in rows[-200:] if r]
    return Counter(tail).most_common(1)[0][0]


def _detect_decimal(rows: List[List[str]], sep: str, n_cols: int) -> str:
    if sep == ",":
        return "."
    for r in rows[-200:]:
        if len(r) == n_cols and any(_DECIMAL_COMMA_RE.match(f.strip().strip('"')) for f in r):
            return ","
    return "."


def _is_value(field_: str) -> bool:
    f = field_.strip().strip('"')
    return bool(f) and bool(_NUMBER_RE.match(f) or _DATETIME_LIKE_RE.match(f))


def _is_data_row(row: List[str], n_cols: int) -> bool:
    if len(row) != n_cols:
        return False
    return sum(_is_value(f) for f in row) >= max(2, math.ceil(n_cols / 2))


def _find_first_data_row(rows, n_cols, decimal) -> Optional[int]:
    for i in range(len(rows)):
        if _is_data_row(rows[i], n_cols) and all(
            _is_data_row(rows[j], n_cols) for j in range(i + 1, min(i + 3, len(rows)))
        ):
            return i
    return None


_UNIT_CELL_RE = re.compile(r"^[%°ºµA-Za-z/.\- ]{0,8}$")


def _looks_like_unit_row(row: List[str]) -> bool:
    """Ligne d'unités sous les en-têtes : « "","","","V","mV","degC" »."""
    cells = [c.strip().strip('"').strip("()[]") for c in row]
    return any(cells) and all(_UNIT_CELL_RE.match(c) for c in cells)


def _find_headers(rows, first_data, n_cols, decimal):
    """Renvoie (noms de colonnes, unités venant d'une ligne d'unités séparée)."""
    units = {}
    header_row = None
    if first_data >= 1 and len(rows[first_data - 1]) == n_cols:
        candidate = rows[first_data - 1]
        if _looks_like_unit_row(candidate) and first_data >= 2 and len(rows[first_data - 2]) == n_cols:
            header_row = rows[first_data - 2]
            unit_row = candidate
            headers = _dedupe([h.strip().strip('"') for h in header_row])
            for h, u in zip(headers, unit_row):
                u = u.strip().strip('"').strip("()[]")
                if u:
                    units[h] = normalize_unit(u)
            return headers, units
        if not _is_data_row(candidate, n_cols):
            header_row = candidate
    if header_row is None:
        headers = ["Voie {}".format(i + 1) for i in range(n_cols)]
        headers[0] = "Temps"
        return headers, units
    return _dedupe([h.strip().strip('"') for h in header_row]), units


def _graphtec_amp_settings(preamble: List[List[str]]):
    """Tableau « Amp settings » des centrales Graphtec : {"CH1": ("nom du signal", "unité")}."""
    out = {}
    columns = None
    for row in preamble:
        cells = [c.strip().strip('"') for c in row]
        lowered = [c.lower() for c in cells]
        if lowered and lowered[0] == "ch" and "signal name" in lowered:
            columns = lowered
            continue
        if columns and cells and re.match(r"^CH\d", cells[0], re.IGNORECASE):
            info = dict(zip(columns, cells))
            if info.get("input", "").lower() == "off":
                continue
            out[cells[0]] = (info.get("signal name", ""), normalize_unit(info.get("unit", "")))
        elif columns and cells and cells[0]:
            columns = None  # fin du tableau
    return out


def _dedupe(names: List[str]) -> List[str]:
    seen = {}
    out = []
    for n in names:
        base = n or "Colonne"
        if base in seen:
            seen[base] += 1
            out.append("{} ({})".format(base, seen[base]))
        else:
            seen[base] = 1
            out.append(base)
    return out


def _unique(label: str, existing) -> str:
    if label not in existing:
        return label
    i = 2
    while "{} #{}".format(label, i) in existing:
        i += 1
    return "{} #{}".format(label, i)


def _to_numeric(series: pd.Series, decimal: str) -> pd.Series:
    s = series.astype(str).str.strip().str.replace(" ", "", regex=False)
    if decimal == ",":
        s = s.str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _extract_time(raw: pd.DataFrame, decimal: str, filename: str):
    """Renvoie (temps écoulé en secondes, horodatage de départ ou None, colonnes utilisées)."""
    cols = list(raw.columns)
    names = {c: split_name_unit(c)[0] for c in cols}
    time_cols = [c for c in cols if _TIME_NAME_RE.search(names[c]) and not _SUBSECOND_NAME_RE.match(names[c])]
    ms_cols = [c for c in cols if _SUBSECOND_NAME_RE.match(names[c])]

    if not time_cols:
        # Pas de nom explicite : la première colonne non-index est le temps
        candidates = [c for c in cols if not _INDEX_NAME_RE.match(c.strip())]
        if not candidates:
            raise LoadError("Aucune colonne temps trouvée dans « {} ».".format(filename))
        time_cols = [candidates[0]]

    used = set(time_cols[:1])
    main = time_cols[0]
    series = raw[main]

    # Date et heure dans deux colonnes séparées ("Date" ; "Heure")
    if _DATE_ONLY_NAME_RE.match(names[main]) and len(time_cols) > 1:
        other = time_cols[1]
        if not raw[main].str.contains(":").any() and raw[other].str.contains(":").any():
            series = raw[main] + " " + raw[other]
            used.add(other)

    seconds, start = _parse_time(series, main, decimal, filename)

    # Graphtec : colonne "ms" séparée qui complète l'horodatage à la seconde
    if ms_cols and start is not None:
        sub = _to_numeric(raw[ms_cols[0]], decimal)
        if sub.notna().mean() > 0.9:
            factor = _SUBSECOND_FACTOR[split_name_unit(ms_cols[0])[0].lower()]
            seconds = seconds + sub.fillna(0).to_numpy(dtype=float) * factor
            used.add(ms_cols[0])

    for c in cols:  # les autres colonnes date/heure ne sont pas des voies
        if c != main and _TIME_NAME_RE.search(names[c]) and _to_numeric(raw[c], decimal).notna().mean() < 0.5:
            used.add(c)
    return seconds, start, used


def _parse_time(series: pd.Series, header: str, decimal: str, filename: str):
    s = series.astype(str).str.strip()
    name, unit = split_name_unit(header)

    numeric = _to_numeric(s, decimal)
    if numeric.notna().mean() > 0.9:
        values = numeric.to_numpy(dtype=float)
        first = values[np.isfinite(values)][0]
        diffs = np.diff(values[np.isfinite(values)])
        step = float(np.median(diffs)) if len(diffs) else 0.0
        unit_key = unit.lower()
        if unit_key in _TIME_UNITS_S:
            factor = _TIME_UNITS_S[unit_key]
        elif re.search(r"\bms\b|_ms$", name, re.IGNORECASE):
            factor = 1e-3
        elif re.search(r"\bmin\b|_min$", name, re.IGNORECASE):
            factor = 60.0
        elif 20000 < first < 80000 and 0 < step < 1:
            # Date série Excel (jours depuis le 30/12/1899)
            start = pd.Timestamp("1899-12-30") + pd.to_timedelta(first, unit="D")
            # arrondi à la ms : les dates série n'ont que ~8 décimales
            return np.round((values - first) * 86400.0, 3), start.round("ms")
        else:
            factor = 1.0  # secondes par défaut
        return (values - first) * factor, None

    sample = s[s != ""]
    if len(sample) and sample.str.match(_DURATION_RE).mean() > 0.9:
        td = pd.to_timedelta(s.str.replace(",", ".", regex=False), errors="coerce")
        secs = td.dt.total_seconds().to_numpy(dtype=float)
        return secs - secs[np.isfinite(secs)][0], None

    # Date/heure absolue. "2026/10/01" -> année en tête ; "01/10/2026" -> jour en tête.
    cleaned = s.str.replace(r"(:\d{2}),(\d+)$", r"\1.\2", regex=True)
    first_value = cleaned[cleaned != ""].iloc[0] if (cleaned != "").any() else ""
    dayfirst = not _YEAR_FIRST_RE.match(first_value)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dt = pd.to_datetime(cleaned, dayfirst=dayfirst, errors="coerce")
    if dt.notna().mean() < 0.9:
        raise LoadError(
            "La colonne temps « {} » du fichier « {} » n'est pas reconnue "
            "(attendu : date/heure, H:MM:SS ou temps écoulé en ms / s / min).".format(header, filename)
        )
    start = dt[dt.notna()].iloc[0]
    secs = (dt - start).dt.total_seconds().to_numpy(dtype=float)
    return secs, start


def _sampling_period(seconds: np.ndarray) -> float:
    diffs = np.diff(seconds)
    diffs = diffs[diffs > 0]
    return float(np.median(diffs)) if len(diffs) else float("nan")


def _guess_source(filename: str, preamble: List[str]) -> str:
    text = (filename + " " + " ".join(preamble[:30])).lower()
    for key, label in _SOURCES:
        if key in text:
            return label
    if re.search(r"\bgl\d{3}", text):
        return "Graphtec"
    if re.search(r"(^|[_\- ])temp", filename.lower()):
        return "Clim"
    return "Générique"
