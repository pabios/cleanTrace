"""Langue de l'interface (FR / EN).

Le texte français sert de clé : ``_("Ouvrir des fichiers…")`` renvoie la traduction
anglaise quand la langue est « en », sinon le texte d'origine. Le choix est mémorisé dans
``~/.cleantrace.json``. Les traductions sont dans ``i18n_en.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

LANGUAGES = {"fr": "Français", "en": "English"}
CONFIG_FILE = Path.home() / ".cleantrace.json"
_language = "fr"


def _(text: str) -> str:
    if _language == "fr":
        return text
    from .i18n_en import EN

    return EN.get(text, text)


def get_language() -> str:
    return _language


def set_language(language: str, save: bool = True) -> None:
    global _language
    if language not in LANGUAGES:
        raise ValueError(language)
    _language = language
    if save:
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
            config["language"] = language
            CONFIG_FILE.write_text(json.dumps(config), encoding="utf-8")
        except (OSError, ValueError):
            pass


def load_language() -> str:
    """Langue mémorisée (français par défaut)."""
    try:
        language = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("language", "fr")
    except (OSError, ValueError):
        language = "fr"
    set_language(language if language in LANGUAGES else "fr", save=False)
    return _language
