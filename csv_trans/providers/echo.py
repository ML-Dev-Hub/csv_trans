"""Deterministic local provider useful for smoke tests and dry runs."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from csv_trans.exceptions import ProviderConfigurationError

from ._common import validate_translation_request
from .base import TranslationItem


class EchoProvider:
    """Return input text unchanged, or pass it through an injected transform."""

    provider_id = "echo"
    name = provider_id
    experimental = False
    base_url = None
    is_remote = False

    def __init__(
        self,
        transform: Callable[[str, str | None, str], str] | None = None,
    ) -> None:
        if transform is not None and not callable(transform):
            raise ProviderConfigurationError(
                "EchoProvider transform must be callable", provider=self.provider_id
            )
        self._transform = transform

    def translate(
        self,
        items: Sequence[TranslationItem],
        *,
        source_language: str | None,
        target_language: str,
    ) -> list[TranslationItem]:
        """Return a deterministic local translation with IDs/order preserved."""

        validated = validate_translation_request(
            self.provider_id,
            items,
            source_language=source_language,
            target_language=target_language,
        )
        if self._transform is None:
            # validate_translation_request already returned a fresh list we own.
            return validated
        transform = self._transform
        return [
            TranslationItem(
                item.id,
                transform(item.text, source_language, target_language),
            )
            for item in validated
        ]


__all__ = ["EchoProvider"]
