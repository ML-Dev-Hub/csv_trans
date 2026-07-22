"""Provider adapter for OpenAI-compatible chat-completions endpoints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from csv_trans.exceptions import (
    ProviderConfigurationError,
    ProviderResponseError,
)

from ._common import (
    MODEL_CORRECTIVE_PROMPT,
    MODEL_SYSTEM_PROMPT,
    decode_json_response,
    decode_strict_translation_text,
    json_request_body,
    model_translation_prompt,
    scrubbed_provider_call,
    send_request,
    validate_extra_headers,
    validate_temperature,
    validate_timeout,
    validate_translation_request,
)
from .base import HttpClient, TranslationItem, UrllibHttpClient
from .endpoints import is_remote_endpoint, validate_endpoint


class OpenAICompatibleProvider:
    """Translate through an OpenAI-compatible ``/chat/completions`` API."""

    provider_id = "openai-compatible"
    name = provider_id
    experimental = False
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str | None = None,
        http_client: HttpClient | None = None,
        timeout: float = 60.0,
        temperature: float | None = None,
        instruction_role: str | None = None,
        response_format: Mapping[str, Any] | None = None,
        max_tokens: int | None = None,
        extra_headers: Mapping[str, str] | None = None,
        allow_insecure_http: bool = False,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ProviderConfigurationError(
                "OpenAI-compatible provider requires an explicit model",
                provider=self.provider_id,
            )
        validate_timeout(timeout, provider=self.provider_id)
        if max_tokens is not None and (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
        ):
            raise ProviderConfigurationError(
                "max_tokens must be a positive integer or None",
                provider=self.provider_id,
            )
        validate_temperature(temperature, provider=self.provider_id)
        if response_format is not None and not isinstance(response_format, Mapping):
            raise ProviderConfigurationError(
                "response_format must be a mapping or None",
                provider=self.provider_id,
            )
        if instruction_role is not None and (
            not isinstance(instruction_role, str)
            or instruction_role.strip().casefold() not in {"system", "developer"}
        ):
            raise ProviderConfigurationError(
                "instruction_role must be system, developer, or None",
                provider=self.provider_id,
            )
        if api_key is not None and not isinstance(api_key, str):
            raise ProviderConfigurationError(
                "api_key must be a string or None", provider=self.provider_id
            )
        validate_extra_headers(extra_headers, provider=self.provider_id)

        self.model = model.strip()
        self.base_url = validate_endpoint(
            base_url,
            provider=self.provider_id,
            allow_insecure_http=allow_insecure_http,
        )
        self.is_remote = is_remote_endpoint(self.base_url)
        self.api_key = api_key.strip() if api_key is not None else None
        self.timeout = timeout
        self.temperature = temperature
        self._instruction_role_override = (
            instruction_role.strip().casefold()
            if instruction_role is not None
            else None
        )
        self.response_format = (
            dict(response_format) if response_format is not None else None
        )
        self.max_tokens = max_tokens
        self.extra_headers = dict(extra_headers or {})
        self._http_client = http_client or UrllibHttpClient()

    @property
    def endpoint(self) -> str:
        """Resolved chat-completions URL; no alternate endpoint is attempted."""

        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    @scrubbed_provider_call
    def translate(
        self,
        items: Sequence[TranslationItem],
        *,
        source_language: str | None,
        target_language: str,
    ) -> list[TranslationItem]:
        """Translate a batch and require an exact JSON ID mapping in response."""

        return self._translate_with_instruction(
            items,
            source_language=source_language,
            target_language=target_language,
            instruction=MODEL_SYSTEM_PROMPT,
        )

    @scrubbed_provider_call
    def translate_corrective(
        self,
        items: Sequence[TranslationItem],
        *,
        source_language: str | None,
        target_language: str,
    ) -> list[TranslationItem]:
        """Retry a malformed result with an explicit corrective instruction."""

        return self._translate_with_instruction(
            items,
            source_language=source_language,
            target_language=target_language,
            instruction=MODEL_CORRECTIVE_PROMPT,
        )

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

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": self.instruction_role, "content": instruction},
                {
                    "role": "user",
                    "content": model_translation_prompt(
                        validated,
                        source_language=source_language,
                        target_language=target_language,
                    ),
                },
            ],
        }
        if self.response_format is not None:
            payload["response_format"] = self.response_format
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            payload["temperature"] = self.temperature

        protected_headers = {"accept", "content-type"}
        if self.api_key:
            protected_headers.add("authorization")
        headers = {
            name: value
            for name, value in self.extra_headers.items()
            if name.strip().casefold() not in protected_headers
        }
        headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

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

    @property
    def instruction_role(self) -> str:
        """Effective instruction role, including an explicit caller override."""

        if self._instruction_role_override is not None:
            return self._instruction_role_override
        host = urlsplit(self.base_url).hostname
        if host is not None and host.casefold().rstrip(".") == "api.openai.com":
            return "developer"
        return "system"

    def _extract_content(self, envelope: Any) -> str:
        try:
            choices = envelope["choices"]
            if not isinstance(choices, list) or not choices:
                raise TypeError
            message = choices[0]["message"]
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError
            return content
        except (IndexError, KeyError, TypeError) as error:
            raise ProviderResponseError(
                "OpenAI-compatible response did not contain message content",
                provider=self.provider_id,
            ) from error


__all__ = ["OpenAICompatibleProvider"]
