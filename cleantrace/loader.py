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
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .channels import (
    DEFAULT_CHANNEL_UNIT, OTHER, Channel, make_channel, normalize_unit, quantity_of, split_name_unit,
)

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


def load_measurement(
    path, name: Optional[str] = None, progress: Optional[Callable[[str], None]] = None
) -> Measurement:
    """Charge un fichier de mesure. Lève :class:`LoadError` si le fichier est non conforme.

    ``progress(message)`` est appelé à chaque étape (lecture, conversion...).
    """
    path = Path(path)
    try:
        return _load(path, name or path.name, progress or (lambda _msg: None))
    except LoadError:
        raise
    except Exception as exc:  # pragma: no cover - filet de sécurité
        raise LoadError(
            "Le fichier « {} » n'a pas pu être lu : {}".format(path.name, exc)
        ) from exc


def choose_reference(measurements: Sequence[Measurement]) -> Optional[Measurement]:
    """Fichier de référence : le Graphset s'il existe, sinon le fichier le plus long.

    Parmi les fichiers couvrant au moins la moitié de la durée maximale, on prend le plus finement
    échantillonné : l'export se fait sur sa grille de temps, il ne faut pas perdre le
    détail d'un enregistreur rapide (Graphtec 100 ms) au profit d'un lent (nanodac 1 min).
    """
    if not measurements:
        return None
    for m in measurements:
        if m.source == "Graphset":
            return m
    longest = max(m.duration_min for m in measurements)
    candidates = [m for m in measurements if m.duration_min >= 0.5 * longest]
    return min(candidates, key=lambda m: (m.period_s if math.isfinite(m.period_s) else math.inf, -m.duration_min))


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


HEAD_BYTES = 2 * 1024 * 1024  # début du fichier analysé (préambule + premières mesures)
TAIL_BYTES = 256 * 1024  # fin du fichier analysée (séparateur, nombre de colonnes)


def _load(path: Path, name: str, progress: Callable[[str], None]) -> Measurement:
    if not path.is_file():
        raise LoadError("Fichier introuvable : {}".format(path))
    size_mb = path.stat().st_size / 1e6
    progress("Analyse du format de {} ({:.0f} Mo)…".format(path.name, size_mb))

    encoding = _detect_encoding(path)
    head, tail = _head_tail_lines(path, encoding)
    if not any(line.strip() for line in head):
        raise LoadError("Le fichier « {} » est vide.".format(path.name))

    sample = [line for line in head[-300:] + tail[-300:] if line.strip()]
    sep = _detect_separator(sample, path.name, head)
    head_rows = list(csv.reader(head, delimiter=sep))
    n_cols = _modal_field_count(list(csv.reader(sample, delimiter=sep)))
    decimal = _detect_decimal(list(csv.reader(sample, delimiter=sep)), sep, n_cols)

    first_data = _find_first_data_row(head_rows, n_cols)
    if first_data is None:
        raise LoadError(
            "Le fichier « {} » ne contient pas de données numériques exploitables "
            "(aucune ligne de mesure reconnue).\n\n{}".format(
                path.name, _diagnostic(head, sep, n_cols, encoding))
        )
    headers, units, aliases = _find_headers(head_rows, first_data, n_cols)
    signal_names = _graphtec_amp_settings(head_rows[:first_data])
    source = _guess_source(path.name, head[:first_data])
    default_unit = DEFAULT_CHANNEL_UNIT if source == "Graphtec" else ""
    for col, (_, unit) in signal_names.items():
        units.setdefault(col, unit)

    progress("Lecture des mesures de {} ({:.0f} Mo)…".format(path.name, size_mb))
    raw = _read_table(path, encoding, sep, decimal, first_data, headers)

    progress("Conversion du temps de {}…".format(path.name))
    time_s, start, used_cols = _extract_time(raw, decimal, path.name)

    # Voies de mesure : toutes les autres colonnes numériques
    channels: List[Channel] = []
    values = {}
    over_range = 0
    for col in raw.columns:
        if col in used_cols or _INDEX_NAME_RE.match(col.strip()) or not col.strip():
            continue
        column = raw[col]
        if not pd.api.types.is_numeric_dtype(column):
            if _to_numeric(column.dropna().head(500), decimal).notna().sum() == 0:
                continue  # colonne de texte (alarmes, messages...) : inutile de tout convertir
            text = column.dropna().astype(str).str.strip()
            over_range += int(text.str.match(_OVER_RANGE_RE).sum())
            column = _to_numeric(column, decimal)
        if column.notna().sum() == 0:
            continue  # colonne de texte (alarmes, messages...)
        alias = signal_names.get(col, ("", ""))[0] or aliases.get(col, "")
        ch = make_channel(col, units.get(col), alias=alias, default_unit=default_unit)
        label = _unique(ch.label, values)
        if label != ch.label:
            ch = Channel(ch.raw_name, label, ch.unit, ch.quantity)
        channels.append(ch)
        values[label] = column.to_numpy(dtype=float)

    if not channels:
        raise LoadError(
            "Le fichier « {} » ne contient aucune voie de mesure numérique "
            "en plus de la colonne temps.\n\nColonnes lues : {}".format(path.name, ", ".join(headers))
        )

    df = pd.DataFrame(values)
    df.insert(0, "_t", time_s)
    valid = np.isfinite(df["_t"].to_numpy())
    skipped = int((~valid).sum())
    df = df[valid]
    if df.empty:
        raise LoadError("La colonne temps du fichier « {} » est illisible.".format(path.name))

    msgs = []
    if skipped:
        msgs.append("{} ligne(s) sans horodatage ignorée(s) (messages, lignes incomplètes).".format(skipped))
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
        source=source,
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


def _detect_encoding(path: Path) -> str:
    with open(path, "rb") as fh:
        head = fh.read(HEAD_BYTES)
        fh.seek(max(0, path.stat().st_size - TAIL_BYTES))
        tail = fh.read()
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if b"\x00" in head[:4096]:
        raise LoadError(
            "Le fichier « {} » semble être un fichier binaire (ex. .GBD Graphtec ou .UHH "
            "nanodac), pas un export texte. Exportez-le en CSV depuis l'appareil ou son "
            "logiciel.".format(path.name)
        )
    # On coupe aux fins de ligne pour ne pas tronquer un caractère multi-octets
    sample = head[: head.rfind(b"\n") + 1 or None] + tail[tail.find(b"\n") + 1:]
    for enc in ENCODINGS:
        try:
            sample.decode(enc)
            return "utf-8" if enc == "utf-8-sig" else enc
        except UnicodeDecodeError:
            continue
    return "latin-1"  # pragma: no cover - latin-1 décode tout


def _open_text(path: Path, encoding: str):
    enc = "utf-8-sig" if encoding == "utf-8" else encoding
    return open(path, "r", encoding=enc, errors="replace", newline=None)


def _head_tail_lines(path: Path, encoding: str) -> Tuple[List[str], List[str]]:
    """Premières lignes (≈ 2 Mo) et dernières lignes (≈ 256 Ko) du fichier."""
    with _open_text(path, encoding) as fh:
        head_text = fh.read(HEAD_BYTES)
    head = head_text.split("\n")
    if len(head_text) >= HEAD_BYTES:
        head = head[:-1]  # dernière ligne probablement tronquée
    if path.stat().st_size <= HEAD_BYTES or encoding == "utf-16":
        tail = head
    else:
        with open(path, "rb") as fh:
            fh.seek(path.stat().st_size - TAIL_BYTES)
            data = fh.read()
        text = data.decode(encoding, errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        tail = text.split("\n")[1:]  # première ligne tronquée
    while head and not head[-1].strip():
        head.pop()
    while tail and not tail[-1].strip():
        tail.pop()
    return head, tail


def _read_table(path: Path, encoding: str, sep: str, decimal: str, first_data: int, headers: List[str]):
    """Lecture rapide (moteur C de pandas) de la partie données du fichier."""
    names = list(range(len(headers)))
    text_cols = [i for i, h in enumerate(headers) if _is_time_header(h)] + [0]
    with _open_text(path, encoding) as fh:
        for _ in range(first_data):
            fh.readline()
        df = pd.read_csv(
            fh, sep=sep, header=None, names=names, index_col=False, decimal=decimal,
            dtype={i: str for i in text_cols}, skip_blank_lines=True, engine="c",
            on_bad_lines="skip", low_memory=False, quotechar='"',
        )
    df.columns = headers
    return df


def _is_time_header(header: str) -> bool:
    name = split_name_unit(header)[0]
    return bool(_TIME_NAME_RE.search(name) or _SUBSECOND_NAME_RE.match(name))


def _diagnostic(lines: List[str], sep: str, n_cols: int, encoding: str) -> str:
    """Résumé de ce qui a été lu, pour comprendre un fichier refusé."""
    def short(line):
        return line[:100] + ("…" if len(line) > 100 else "")

    useful = [line for line in lines if line.strip()]
    shown = useful[:4]
    for k, line in enumerate(useful):  # lignes qui suivent le marqueur « Data »
        if line.strip().strip('"').lower() == "data":
            shown += ["…"] + useful[k:k + 4]
            break
    return (
        "Diagnostic : encodage {}, séparateur {}, {} colonnes.\n"
        "Extrait :\n{}\n\n"
        "Envoyez un extrait de ce fichier pour une correction rapide.".format(
            encoding, SEPARATOR_NAMES.get(sep, repr(sep)), n_cols, "\n".join(short(x) for x in shown))
    )


def write_extract(path, out_path, head_lines: int = 80, tail_lines: int = 10) -> Path:
    """Copie le début et la fin d'un fichier (octets bruts) : de quoi analyser son format."""
    path, out_path = Path(path), Path(out_path)
    with open(path, "rb") as fh:
        head = fh.read(HEAD_BYTES).split(b"\n")[:head_lines]
        size = path.stat().st_size
        fh.seek(max(0, size - 64 * 1024))
        tail = fh.read().split(b"\n")[-tail_lines - 1:]
    with open(out_path, "wb") as out:
        out.write(b"\n".join(head))
        if size > HEAD_BYTES or len(head) >= head_lines:
            out.write(b"\n[...]\n" + b"\n".join(tail))
    return out_path


def _detect_separator(sample: List[str], filename: str, head: List[str]) -> str:
    # Lignes de données (début + fin du fichier) : le préambule ne doit pas compter.
    for sep in SEPARATORS:
        counts = [len(r) for r in csv.reader(sample, delimiter=sep)]
        value, freq = Counter(counts).most_common(1)[0]
        if value >= 2 and freq >= 0.6 * len(counts):
            return sep
    raise LoadError(
        "Impossible de détecter le séparateur de colonnes du fichier « {} » "
        "(attendu : « ; », « , » ou tabulation, avec au moins une colonne temps "
        "et une voie de mesure).\n\n{}".format(filename, _diagnostic(head, ",", 0, "?"))
    )


def _modal_field_count(rows: List[List[str]]) -> int:
    counts = [len(r) for r in rows if r]
    return Counter(counts).most_common(1)[0][0]


def _detect_decimal(rows: List[List[str]], sep: str, n_cols: int) -> str:
    if sep == ",":
        return "."
    for r in rows:
        if len(r) == n_cols and any(_DECIMAL_COMMA_RE.match(f.strip().strip('"')) for f in r):
            return ","
    return "."


def _is_value(field_: str) -> bool:
    f = field_.strip().strip('"').lstrip("'")
    return bool(f) and bool(_NUMBER_RE.match(f) or _DATETIME_LIKE_RE.match(f) or _OVER_RANGE_RE.match(f))


def _is_data_row(row: List[str], n_cols: int) -> bool:
    # Un horodatage + au moins une valeur suffisent : les colonnes d'alarme ("LLLL"),
    # de messages ou les voies débranchées ne doivent pas faire rejeter la ligne.
    return len(row) == n_cols and sum(_is_value(f) for f in row) >= 2


def _find_first_data_row(rows, n_cols) -> Optional[int]:
    for i in range(len(rows)):
        if _is_data_row(rows[i], n_cols) and all(
            _is_data_row(rows[j], n_cols) for j in range(i + 1, min(i + 3, len(rows)))
        ):
            return i
    return None


_UNIT_CELL_RE = re.compile(r"^[%°ºµA-Za-z/.\- ]{0,8}$")


_ALARM_LABEL_RE = re.compile(r"^[A-Za-z]\d{3,}$")  # « A1234567890 » (GL860)


def _looks_like_unit_row(row: List[str]) -> bool:
    """Ligne d'unités sous les en-têtes : « "","","","V","mV","degC" » ou « NO.,Time,ms,V,mA »."""
    cells = [c.strip().strip('"').strip("()[]") for c in row]
    return any(cells) and all(_UNIT_CELL_RE.match(c) or _ALARM_LABEL_RE.match(c) for c in cells)


def _find_headers(rows, first_data, n_cols):
    """Renvoie (noms de colonnes, unités, alias) à partir des lignes qui précèdent les données.

    Cas gérés : une ligne d'en-têtes ; en-têtes + ligne d'unités (Graphtec) ; en-tête
    suivi d'un descriptif de voie en bout de ligne (nanodac :
    « Date/Heure  Channel 2  (ENAN2);Group 1;M402-M210;°C »).
    """
    units, aliases = {}, {}
    default = ["Temps"] + ["Voie {}".format(i + 1) for i in range(1, n_cols)]
    if first_data < 1:
        return default, units, aliases
    candidate = [c.strip().strip('"') for c in rows[first_data - 1]]
    extra = []
    if len(candidate) > n_cols:  # descriptif en bout de ligne
        extra = [c for c in candidate[n_cols:] if c]
        candidate = candidate[:n_cols]
    if len(candidate) != n_cols or _is_data_row(candidate, n_cols):
        return default, units, aliases

    if _looks_like_unit_row(candidate) and first_data >= 2 and len(rows[first_data - 2]) >= n_cols:
        headers = _dedupe([h.strip().strip('"') for h in rows[first_data - 2][:n_cols]])
        for h, u in zip(headers, candidate):
            u = u.strip("()[]")
            if u and not _ALARM_LABEL_RE.match(u):
                units[h] = normalize_unit(u)
        return headers, units, aliases

    headers = _dedupe(candidate)
    value_cols = [h for h in headers if not _is_time_header(h) and not _INDEX_NAME_RE.match(h)]
    if extra and len(value_cols) == 1:
        unit, alias = _channel_descriptor(extra)
        if unit:
            units[value_cols[0]] = unit
        if alias:
            aliases[value_cols[0]] = alias
    return headers, units, aliases


def _channel_descriptor(cells: List[str]) -> Tuple[str, str]:
    """« (ENAN2);Group 1;M402-M210;°C » -> ("°C", "M402-M210")."""
    tokens = [t.strip() for t in re.split(r"[;\t]", ";".join(cells)) if t.strip()]
    for k in range(len(tokens) - 1, -1, -1):
        unit = normalize_unit(tokens[k])
        if quantity_of(unit) != OTHER or unit == "%":
            alias = tokens[k - 1] if k >= 1 else ""
            if alias.startswith("(") or re.match(r"^group\b", alias, re.IGNORECASE):
                alias = ""
            return unit, alias
    return "", ""


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
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    if decimal == ".":
        fast = pd.to_numeric(series, errors="coerce")  # conversion C, sans traitement de texte
        if fast.notna().sum() >= 0.99 * series.notna().sum():
            return fast.astype(float)
    s = series.fillna("").astype(str).str.strip().str.replace(" ", "", regex=False)
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
        if not raw[main].str.contains(":", na=False).any() and raw[other].str.contains(":", na=False).any():
            series = raw[main].fillna("") + " " + raw[other].fillna("")
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
        if c != main and _TIME_NAME_RE.search(names[c]):
            head = raw[c].dropna().head(200)
            if _to_numeric(head, decimal).notna().mean() < 0.5:
                used.add(c)
    return seconds, start, used


def _parse_time(series: pd.Series, header: str, decimal: str, filename: str):
    name, unit = split_name_unit(header)
    s = series.fillna("").astype(str)
    # Le type de la colonne est décidé sur un échantillon : les traitements de texte
    # sur des millions de lignes ne sont faits que s'ils sont vraiment nécessaires.
    raw_sample = s[s != ""].head(200)
    sample = raw_sample.str.strip().str.lstrip("'")
    if (sample != raw_sample).any():
        s = s.str.strip().str.lstrip("'")
    if sample.empty:
        raise LoadError("La colonne temps « {} » du fichier « {} » est vide.".format(header, filename))

    if _to_numeric(sample, decimal).notna().mean() > 0.9:
        numeric = _to_numeric(s, decimal)
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

    if sample.str.match(_DURATION_RE).mean() > 0.9:
        td = pd.to_timedelta(s.str.replace(",", ".", regex=False), errors="coerce")
        secs = td.dt.total_seconds().to_numpy(dtype=float)
        return secs - secs[np.isfinite(secs)][0], None

    # Date/heure absolue. "2026/10/01" -> année en tête ; "01/10/2026" -> jour en tête.
    if sample.str.contains(r":\d{2},\d+$").any():  # secondes avec virgule décimale
        s = s.str.replace(r"(:\d{2}),(\d+)$", r"\1.\2", regex=True)
    dt = _to_datetime(s)
    if dt.notna().mean() < 0.9:
        raise LoadError(
            "La colonne temps « {} » du fichier « {} » n'est pas reconnue "
            "(attendu : date/heure, H:MM:SS ou temps écoulé en ms / s / min).".format(header, filename)
        )
    start = dt[dt.notna()].iloc[0]
    secs = (dt - start).dt.total_seconds().to_numpy(dtype=float)
    return secs, start


# Formats de date/heure courants, essayés d'abord : bien plus rapide que la détection
# automatique de pandas sur des millions de lignes.
_DATETIME_FORMATS = (
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d/%m/%y %H:%M:%S",
)


def _to_datetime(s: pd.Series) -> pd.Series:
    sample = s[s != ""].head(50)
    for fmt in _DATETIME_FORMATS:
        try:
            pd.to_datetime(sample, format=fmt)
        except (ValueError, TypeError):
            continue
        return pd.to_datetime(s, format=fmt, errors="coerce")
    # Format inhabituel : détection automatique (plus lente)
    first_value = sample.iloc[0] if len(sample) else ""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(s, dayfirst=not _YEAR_FIRST_RE.match(first_value), errors="coerce")


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
