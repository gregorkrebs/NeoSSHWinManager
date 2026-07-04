"""
i18n.py – Simple translation system for NEO SSH-Win Manager.

Supported languages: English (default) + German.
Language is stored per user in the app_settings table.
Translations loaded from src/translations/<lang>.json.

Usage:
    from src.i18n import tr, set_language
    set_language("de")
    lbl = QLabel(tr("settings.title"))
"""

import json
import os
import sys
from typing import Dict

_DEFAULT_LANG = "en"
_SUPPORTED = ("en", "de")

_current_lang: str = _DEFAULT_LANG
_cache: Dict[str, Dict[str, str]] = {}


def _normalize_lang(lang: str | None) -> str:
    """Normalize persisted/user-provided language identifiers to supported codes."""
    if not lang:
        return _DEFAULT_LANG
    value = str(lang).strip().lower().replace("_", "-")
    # Accept common variants from older settings or locale-like values.
    if value in ("de", "de-de", "deutsch", "german") or value.startswith("de-"):
        return "de"
    if value in ("en", "en-us", "en-gb", "english") or value.startswith("en-"):
        return "en"
    return _DEFAULT_LANG


def _translations_root() -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "src", "translations")
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "translations")


def _load(lang: str) -> Dict[str, str]:
    if lang in _cache:
        return _cache[lang]
    path = os.path.join(_translations_root(), f"{lang}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    _cache[lang] = data
    return data


def set_language(lang: str) -> None:
    global _current_lang
    normalized = _normalize_lang(lang)
    if normalized not in _SUPPORTED:
        normalized = _DEFAULT_LANG
    _current_lang = normalized
    _load(normalized)


def current_language() -> str:
    return _current_lang


def available_languages() -> tuple:
    return _SUPPORTED


def tr(key: str, **kwargs) -> str:
    """Translate a key. Falls back to English, then to the key itself.
    Supports str.format-style substitution via kwargs."""
    text = _load(_current_lang).get(key)
    if text is None and _current_lang != _DEFAULT_LANG:
        text = _load(_DEFAULT_LANG).get(key)
    if text is None:
        text = key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text
