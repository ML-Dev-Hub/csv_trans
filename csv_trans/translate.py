"""Ergonomic string-language convenience wrapper over the v2 engine.

This module also preserves the csv-trans **1.x calling interface**. All of the
following continue to work and delegate into the v2 engine:

* the v2 form ``translate(input_path, source_language, target_language, **config)``
* the 1.x positional form ``translate(file, source_lang, target_lang, sep)``
* the 1.x keyword names ``file=``, ``source_lang=``, ``target_lang=``, ``sep=``
* the 1.x programmatic ``main(file_path, source_language, target_language, file_separator)``

Only the *interface* is preserved; behaviour is v2's (conservative column
selection, dialect preservation, atomic output, structured result). Code that
ignored the v1 ``None`` return remains valid — a ``TranslationResult`` is a
strict superset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import translate_csv
from .models import TranslationConfig, TranslationResult

__all__ = ["translate", "main", "translate_csv"]


def translate(
    input_path: str | Path | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    sep: str | None = None,
    *,
    output_path: str | Path | None = None,
    **options: Any,
) -> TranslationResult:
    """Translate a CSV using string language codes and keyword options.

    Builds a :class:`~csv_trans.TranslationConfig` from ``source_language``,
    ``target_language``, and any keyword ``options`` (every configuration field
    is accepted), then delegates to :func:`csv_trans.translate_csv`. Use
    ``translate_csv`` directly when you already hold a configuration object.

    The csv-trans 1.x interface is accepted too: the positional
    ``translate(file, source_lang, target_lang, sep)`` form, the 1.x keyword
    names, and ``sep`` (forwarded as the v2 ``delimiter``). When ``sep`` is not
    supplied the v2 dialect detector runs, so passing nothing is safer than the
    1.x hard-coded comma default rather than different.
    """

    # Accept the 1.x keyword names as aliases for the v2 parameters. Passing a
    # v2 name together with its 1.x alias is ambiguous; reject it with a
    # targeted error rather than letting the stray alias reach the config.
    for v2_name, v2_value, alias in (
        ("input_path", input_path, "file"),
        ("source_language", source_language, "source_lang"),
        ("target_language", target_language, "target_lang"),
    ):
        if alias in options and v2_value is not None:
            raise TypeError(
                f"translate() got both {v2_name!r} and its 1.x alias "
                f"{alias!r}; pass only one"
            )

    if input_path is None and "file" in options:
        input_path = options.pop("file")
    if source_language is None and "source_lang" in options:
        source_language = options.pop("source_lang")
    if target_language is None and "target_lang" in options:
        target_language = options.pop("target_lang")

    # 1.x ``sep`` maps to the v2 ``delimiter`` unless an explicit v2 name wins.
    if sep is not None:
        options.setdefault("delimiter", sep)

    if input_path is None:
        raise TypeError(
            "translate() missing required argument: 'input_path' "
            "(1.x name: 'file')"
        )
    if source_language is None or target_language is None:
        raise TypeError(
            "translate() requires 'source_language' and 'target_language' "
            "(1.x names: 'source_lang' and 'target_lang')"
        )

    config = TranslationConfig(
        source_language=source_language,
        target_language=target_language,
        **options,
    )
    return translate_csv(input_path, config, output_path=output_path)


def main(
    file_path: str | Path,
    source_language: str,
    target_language: str,
    file_separator: str = ",",
    **options: Any,
) -> TranslationResult:
    """Compatibility alias for the csv-trans 1.x programmatic ``main`` helper.

    Mirrors the 1.x positional signature
    ``main(file_path, source_language, target_language, file_separator)`` and
    delegates to :func:`translate`. The 1.x helper returned ``None``; this
    returns the v2 :class:`~csv_trans.TranslationResult` (a compatible superset).
    """

    return translate(
        file_path,
        source_language,
        target_language,
        file_separator,
        **options,
    )
