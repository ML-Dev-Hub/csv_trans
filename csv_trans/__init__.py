"""Dependency-free CSV translation with pluggable remote and local providers."""

from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("csv-trans")
    except PackageNotFoundError:
        __version__ = "2.0.0"
except ImportError:  # pragma: no cover - Python 3.11+ always has importlib.metadata
    __version__ = "2.0.0"

from .core import PrivacyViolation, translate_csv
from .models import (
    ColumnSelection,
    PrivacyMode,
    ProgressEvent,
    ProviderAttempt,
    RunStatus,
    TranslationConfig,
    TranslationFailure,
    TranslationResult,
)
from .translate import translate

__all__ = [
    "ColumnSelection",
    "PrivacyMode",
    "PrivacyViolation",
    "ProgressEvent",
    "ProviderAttempt",
    "RunStatus",
    "TranslationConfig",
    "TranslationFailure",
    "TranslationResult",
    "__version__",
    "translate",
    "translate_csv",
]
