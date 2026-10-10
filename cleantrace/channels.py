"""US-02 — Voies de mesure : nettoyage des libellés, unités et grandeurs physiques.

Exemples de conversions :
    "CH1"                 -> "Channel 1"   (unité mV par défaut sur un Graphtec, gardée à part)
    "CH3 [V]"             -> "Channel 3"   (unité V)
    "Courant (A)"         -> "Courant (A)"
    "Température"         -> "Température (°C)"
    "HR (%)"              -> "HR (%HR)"
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

# Unité entre parenthèses ou crochets en fin de libellé : "Tension (V)", "CH1[mV]"
_UNIT_RE = re.compile(r"[\(\[]\s*([^\)\]]*?)\s*[\)\]]\s*$")
# Voies génériques des centrales : "CH1", "Ch 2", "CH-03", "Voie 4", "Channel5"
_CHANNEL_RE = re.compile(r"^(?:ch|ch\.|channel|voie|cv)\s*[-_ ]?\s*0*(\d+)$", re.IGNORECASE)

_UNIT_ALIASES = {
    "mv": "mV",
    "v": "V",
    "kv": "kV",
    "a": "A",
    "ma": "mA",
    "ua": "µA",
    "µa": "µA",
    "°c": "°C",
    "ºc": "°C",
    "degc": "°C",
    "deg c": "°C",
    "c": "°C",
    "%hr": "%HR",
    "%rh": "%HR",
    "hr": "%HR",
    "rh": "%HR",
    "%": "%",
    "w": "W",
    "ohm": "Ω",
    "ω": "Ω",
}

_TEMP_RE = re.compile(r"temp|°c", re.IGNORECASE)
_HUM_RE = re.compile(r"hum|(^|[^a-z])(hr|rh)([^a-z]|$)", re.IGNORECASE)

# Grandeurs physiques reconnues
VOLTAGE = "tension"
CURRENT = "courant"
TEMPERATURE = "température"
HUMIDITY = "humidité"
OTHER = "autre"

_QUANTITY_BY_UNIT = {
    "mV": VOLTAGE,
    "V": VOLTAGE,
    "kV": VOLTAGE,
    "mA": CURRENT,
    "A": CURRENT,
    "µA": CURRENT,
    "°C": TEMPERATURE,
    "%HR": HUMIDITY,
}

# Unité par défaut des voies "CHx" sans unité d'un Graphtec (jamais supposée ailleurs :
# une voie "Channel 2" de nanodac peut très bien être une température)
DEFAULT_CHANNEL_UNIT = "mV"


@dataclass(frozen=True)
class Channel:
    """Une voie de mesure d'un fichier."""

    raw_name: str  # libellé d'origine dans le fichier
    label: str  # libellé affiché (légende, liste, export) : « Channel 4 » pour une voie CHx
    unit: str  # unité normalisée ("" si inconnue)
    quantity: str  # grandeur physique (tension, courant, ...)
    alias: str = ""  # nom donné à la voie dans la centrale (ex. « I_s1 »), repris dans le rapport

    @property
    def is_climatic(self) -> bool:
        """Voie issue de l'enceinte climatique (température / humidité)."""
        return self.quantity in (TEMPERATURE, HUMIDITY)


def normalize_unit(unit: str) -> str:
    """Normalise une unité ("mv" -> "mV", "deg C" -> "°C"). Renvoie l'unité telle quelle si inconnue."""
    cleaned = unit.strip()
    return _UNIT_ALIASES.get(cleaned.lower(), cleaned)


def split_name_unit(raw: str) -> Tuple[str, str]:
    """Sépare "Tension (V)" en ("Tension", "V")."""
    text = raw.strip().strip('"').strip("'").strip()
    match = _UNIT_RE.search(text)
    if not match:
        return " ".join(text.split()), ""
    name = text[: match.start()].strip()
    return " ".join(name.split()), normalize_unit(match.group(1))


def quantity_of(unit: str) -> str:
    return _QUANTITY_BY_UNIT.get(unit, OTHER)


def make_channel(
    raw: str, unit: Optional[str] = None, alias: str = "", default_unit: str = ""
) -> Channel:
    """Construit une voie avec un libellé lisible à partir du nom brut de la colonne.

    ``alias`` : nom donné à la voie dans la centrale (ex. « Signal name » Graphtec).
    ``default_unit`` : unité des voies « CHx » sans unité connue (mV pour un Graphtec).
    """
    name, found_unit = split_name_unit(raw)
    unit = normalize_unit(unit) if unit else found_unit

    alias = " ".join(alias.split())
    match = _CHANNEL_RE.match(name)
    if match:
        # Voie d'une centrale : libellé « Channel N » (comme sur l'appareil) ; le nom du
        # signal et l'unité restent connus (rapport, axes) mais ne surchargent pas la légende.
        unit = unit or default_unit
        if alias.lower() == raw.strip().lower():
            alias = ""
        label = "Channel {}".format(int(match.group(1)))
        return Channel(raw_name=raw, label=label, unit=unit, quantity=quantity_of(unit), alias=alias)
    if not unit:
        if _TEMP_RE.search(name):
            unit = "°C"
        elif _HUM_RE.search(name):
            unit = "%HR"

    # "HR (%)" est une humidité relative, pas un pourcentage quelconque
    if unit == "%" and _HUM_RE.search(name):
        unit = "%HR"

    name = name or raw.strip() or "Voie"
    if alias and alias.lower() not in (raw.strip().lower(), name.lower()):
        name = "{} - {}".format(name, alias)
    label = "{} ({})".format(name, unit) if unit else name
    return Channel(raw_name=raw, label=label, unit=unit, quantity=quantity_of(unit), alias=alias)
