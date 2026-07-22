"""Provider adapter for Anthropic's Messages API."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

from csv_trans.exceptions import (
    ProviderConfigurationError,
    ProviderError,
    ProviderResponseError,
)

from ._common import (
    MODEL_CORRECTIVE_PROMPT,
    MODEL_SYSTEM_PROMPT,
    decode_json_response,
    decode_strict_translation_text,
    json_request_body,
    model_translation_prompt,
    scrub_provider_error,
    send_request,
    validate_translation_request,
)
from .base import HttpClient, TranslationItem, UrllibHttpClient
from .endpoints import is_remote_endpoint, validate_endpoint


class AnthropicProvider:
    """Translate a batch through Anthropic's ``/v1/messages`` endpoint."""

    provider_id = "anthropic"
    name = provider_id
    experimental = False
    DEFAULT_BASE_URL = "https://api.anthropic.com"

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_version: str = "2023-06-01",
        max_tokens: int = 4096,
        temperature: float | None = None,
        http_client: HttpClient | None = None,
        timeout: float = 60.0,
        extra_headers: Mapping[str, str] | None = None,
        allow_insecure_http: bool = False,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ProviderConfigurationError(
                "Anthropic provider requires an explicit model",
                provider=self.provider_id,
            )
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderConfigurationError(
                "Anthropic provider requires an API key",
                provider=self.provider_id,
            )
        if not isinstance(api_version, str) or not api_version.strip():
            raise ProviderConfigurationError(
                "Anthropic provider requires an API version",
                provider=self.provider_id,
            )
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
        ):
            raise ProviderConfigurationError(
                "max_tokens must be a positive integer", provider=self.provider_id
            )
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ProviderConfigurationError(
                "timeout must be a finite number greater than zero",
                provider=self.provider_id,
            )
        if temperature is not None and (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or (isinstance(temperature, float) and not math.isfinite(temperature))
            or temperature < 0
        ):
            raise ProviderConfigurationError(
                "temperature must be a finite non-negative number or None",
                provider=self.provider_id,
            )

        self.model = model.strip()
        self.api_key = api_key.strip()
        self.base_url = validate_endpoint(
            base_url,
            provider=self.provider_id,
            allow_insecure_http=allow_insecure_http,
        )
        self.is_remote = is_remote_endpoint(self.base_url)
        self.api_version = api_version.strip()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})
        self._http_client = http_client or UrllibHttpClient()

    @property
    def endpoint(self) -> str:
        """Resolved Messages API URL; no alternate endpoint is attempted."""

        if self.base_url.endswith("/v1/messages"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    def translate(
        self,
        items: Sequence[TranslationItem],
        *,
        source_language: str | None,
        target_language: str,
    ) -> list[TranslationItem]:
        """Translate a batch and require an exact JSON ID mapping in response."""

        try:
            return self._translate_with_instruction(
                items,
                source_language=source_language,
                target_language=target_language,
                instruction=MODEL_SYSTEM_PROMPT,
            )
        except ProviderError as error:
            safe_error = scrub_provider_error(error)
        self = None  # type: ignore[assignment]
        items = ()
        source_language = None
        target_language = ""
        raise safe_error from None

    def translate_corrective(
        self,
        items: Sequence[TranslationItem],
        *,
        source_language: str | None,
        target_language: str,
    ) -> list[TranslationItem]:
        """Retry a malformed result with an explicit corrective instruction."""

        try:
            return self._translate_with_instruction(
                items,
                source_language=source_language,
                target_language=target_language,
                instruction=MODEL_CORRECTIVE_PROMPT,
            )
        except ProviderError as error:
            safe_error = scrub_provider_error(error)
        self = None  # type: ignore[assignment]
        items = ()
        source_language = None
        target_language = ""
        raise safe_error from None

    def _translate_with_instruction(
        self,
        items: Sequence[TranslationItem],
        *,
        source_language: str | None,
        target_language: str,
        instruction: str,
    ) -> list[TranslationItem]:

        validated = validate_translation_request(
            self.provider_id,
            items,
            source_language=source_language,
            target_language=target_language,
        )
        if not validated:
            return []

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": instruction,
            "messages": [
                {
                    "role": "user",
                    "content": model_translation_prompt(
                        validated,
                        source_language=source_language,
                        target_language=target_language,
                    ),
                }
            ],
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        protected_headers = {
            "accept",
            "content-type",
            "anthropic-version",
            "x-api-key",
        }
        headers = {
            name: value
            for name, value in self.extra_headers.items()
            if name.casefold() not in protected_headers
        }
        headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-version": self.api_version,
            "x-api-key": self.api_key,
        })

        response = send_request(
            self._http_client,
            "POST",
            self.endpoint,
            provider=self.provider_id,
            headers=headers,
            body=json_request_body(payload, provider=self.provider_id),
            timeout=self.timeout,
        )
        envelope = decode_json_response(response, provider=self.provider_id)
        content = self._extract_content(envelope)
        return decode_strict_translation_text(
            content,
            validated,
            provider=self.provider_id,
        )

    def _extract_content(self, envelope: Any) -> str:
        try:
            blocks = envelope["content"]
            if not isinstance(blocks, list) or len(blocks) != 1:
                raise TypeError
            block = blocks[0]
            if not isinstance(block, dict) or block.get("type") != "text":
                raise TypeError
            text = block["text"]
            if not isinstance(text, str):
                raise TypeError
            return text
        except (IndexError, KeyError, TypeError) as error:
            raise ProviderResponseError(
                "Anthropic response did not contain one text content block",
                provider=self.provider_id,
            ) from error


__all__ = ["AnthropicProvider"]
