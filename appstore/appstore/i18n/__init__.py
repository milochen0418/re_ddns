"""Translations for the App Store page and its container monitor page.

Both pages read the same table: the language picked on either one applies to
the other (``lang.LocaleState``).  Keys used by one page only are grouped by
page in ``en.py``.

**Adding a language** takes two steps:

1. Copy ``en.py`` to ``<code>.py`` (e.g. ``ko.py``, ``de.py``, ``pt_br.py``) and
   translate the values.  Keys and the ``{placeholders}`` inside the values must
   stay as they are; the text around them is free.  A partial translation is
   fine — anything missing falls back to English.
2. Add one entry to ``LOCALES`` below, with the language's name written in that
   language (that is what the picker shows).

Nothing else needs to change: the page reads this registry, so a new language
appears in the picker as soon as it is listed.

Codes follow BCP 47 (``zh-Hant``, ``pt-BR``); the module file name is the code
in lower case with ``-`` as ``_``.
"""

from __future__ import annotations

import importlib
from types import MappingProxyType

# The language picker, in the order it is shown.  "label" is deliberately in
# the language itself, so a reader can find their own without knowing English.
LOCALES: tuple[dict[str, str], ...] = (
    {"code": "en", "label": "English"},
    {"code": "zh-Hant", "label": "繁體中文"},
    {"code": "zh-Hans", "label": "简体中文"},
    {"code": "es", "label": "Español"},
    {"code": "ja", "label": "日本語"},
)

# New visitors get English; a choice is remembered in the browser.
DEFAULT = "en"

CODES: frozenset[str] = frozenset(loc["code"] for loc in LOCALES)

_cache: dict[str, MappingProxyType] = {}


def _module_name(code: str) -> str:
    return code.lower().replace("-", "_")


def _load(code: str) -> dict[str, str]:
    module = importlib.import_module(f".{_module_name(code)}", __package__)
    return dict(module.STRINGS)


def strings(code: str | None) -> MappingProxyType:
    """The string table for ``code``, with English filling any gaps.

    Unknown or missing codes fall back to English, so a stale locale left in a
    browser's storage cannot break the page.
    """
    if code not in CODES:
        code = DEFAULT
    if code not in _cache:
        table = _load(DEFAULT)
        if code != DEFAULT:
            table.update(_load(code))
        _cache[code] = MappingProxyType(table)
    return _cache[code]


def label(code: str | None) -> str:
    """The name of a language, in that language."""
    for loc in LOCALES:
        if loc["code"] == code:
            return loc["label"]
    return next(loc["label"] for loc in LOCALES if loc["code"] == DEFAULT)


def missing_keys() -> dict[str, list[str]]:
    """Keys each locale has yet to translate — for a quick check while editing."""
    reference = set(_load(DEFAULT))
    out: dict[str, list[str]] = {}
    for loc in LOCALES:
        code = loc["code"]
        if code == DEFAULT:
            continue
        gaps = sorted(reference - set(_load(code)))
        if gaps:
            out[code] = gaps
    return out
