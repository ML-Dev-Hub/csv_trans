"""Small compatibility helpers retained from csv-trans 1.x.

The pandas/DataFrame helpers from 1.x were implementation details and are not
part of the v2 engine.  This module keeps the useful encoding and chunking
functions dependency-free so older imports fail gracefully rather than pulling
the former 19-package runtime stack back in.
"""

from __future__ import annotations

from pathlib import Path

from .chunking import split_text_lossless
from .csvio import detect_encoding


def detect_encoding_scheme(file_path: str | Path) -> str:
    """Compatibility name for strict Unicode encoding detection."""

    return detect_encoding(file_path)


def split_text_data(text: str, chunk_size: int) -> list[str]:
    """Compatibility name for the fixed, lossless v2 chunker."""

    return split_text_lossless(text, chunk_size)


def validate_dataframe(value: object) -> bool:
    """Return whether a dataframe-like value is nonempty, without importing pandas."""

    if value is None:
        return False
    empty = getattr(value, "empty", None)
    return bool(empty is False)


def _removed_dataframe_api(name: str) -> None:
    raise NotImplementedError(
        f"{name} was removed in csv-trans 2.0; use translate_csv() so CSV shape "
        "and string formatting can be preserved without pandas"
    )


def translate_text(*args: object, **kwargs: object) -> None:
    """Explain migration from the unsafe provider-coupled 1.x helper."""

    _removed_dataframe_api("translate_text")


def translate_dataframe(*args: object, **kwargs: object) -> None:
    """Explain migration from the pandas-only 1.x helper."""

    _removed_dataframe_api("translate_dataframe")


def read_csv_file(*args: object, **kwargs: object) -> None:
    """Explain migration from the pandas-only 1.x helper."""

    _removed_dataframe_api("read_csv_file")


def save_csv_file(*args: object, **kwargs: object) -> None:
    """Explain migration from the pandas-only 1.x helper."""

    _removed_dataframe_api("save_csv_file")


__all__ = [
    "detect_encoding_scheme",
    "read_csv_file",
    "save_csv_file",
    "split_text_data",
    "translate_dataframe",
    "translate_text",
    "validate_dataframe",
]
