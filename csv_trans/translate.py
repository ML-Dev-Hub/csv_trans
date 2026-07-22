"""Backward-compatible Python entry point built on the v2 engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import translate_csv
from .models import TranslationResult


def translate(
    file: str | Path,
    source_lang: str,
    target_lang: str,
    sep: str = ",",
    **options: Any,
) -> TranslationResult:
    """Translate a CSV while retaining the historical four-argument form.

    Version 2 returns :class:`TranslationResult`, preserves headers by default,
    and auto-selects text-like columns.  Every v2 option can be supplied as a
    keyword; ``sep`` is forwarded as ``delimiter`` unless that explicit v2 name
    was supplied.
    """

    options.setdefault("delimiter", sep)
    return translate_csv(file, source_lang, target_lang, **options)


def main(
    file_path: str | Path,
    source_language: str,
    target_language: str,
    file_separator: str = ",",
    **options: Any,
) -> TranslationResult:
    """Compatibility alias for the former programmatic ``main`` helper."""

    return translate(
        file_path,
        source_language,
        target_language,
        file_separator,
        **options,
    )


__all__ = ["main", "translate", "translate_csv"]
