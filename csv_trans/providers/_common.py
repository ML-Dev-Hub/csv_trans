"""Private validation, HTTP, and JSON helpers shared by provider adapters."""

from __future__ import annotations

import functools
import json
import math
import socket
from collections.abc import Mapping, Sequence
from typing import Any, Callable
from urllib.error import URLError

from csv_trans.exceptions import (
    ErrorCategory,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderContextLimitError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

from .base import (
    HttpClient,
    HttpResponse,
    HttpTransportConnectionError,
    HttpTransportResponseTooLarge,
    HttpTransportTimeout,
    TranslationItem,
    _strict_json_loads,
)


def validate_translation_request(
    provider: str,
    items: Sequence[TranslationItem],
    *,
    source_language: str | None,
    target_language: str,
) -> list[TranslationItem]:
    """Validate common provider inputs and materialize a safe item list."""

    if not isinstance(target_language, str) or not target_language.strip():
        raise ProviderRequestError(
            "target_language must be a non-empty string", provider=provider
        )
    if source_language is not None and (
        not isinstance(source_language, str) or not source_language.strip()
    ):
        raise ProviderRequestError(
            "source_language must be None or a non-empty string",
            provider=provider,
        )
    try:
        materialized = list(items)
    except TypeError as error:
        raise ProviderRequestError(
            "items must be a sequence of TranslationItem values", provider=provider
        ) from error

    seen: set[str] = set()
    for item in materialized:
        if not isinstance(item, TranslationItem):
            raise ProviderRequestError(
                "items must contain only TranslationItem values", provider=provider
            )
        if item.id in seen:
            raise ProviderRequestError(
                "TranslationItem IDs must be unique", provider=provider
            )
        seen.add(item.id)
    return materialized


def validate_timeout(timeout: Any, *, provider: str) -> None:
    """Reject a non-finite or non-positive HTTP timeout (shared by adapters)."""

    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ProviderConfigurationError(
            "timeout must be a finite number greater than zero", provider=provider
        )


def validate_temperature(temperature: Any, *, provider: str) -> None:
    """Reject a non-finite or negative sampling temperature (shared by adapters)."""

    if temperature is not None and (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or (isinstance(temperature, float) and not math.isfinite(temperature))
        or temperature < 0
    ):
        raise ProviderConfigurationError(
            "temperature must be a finite non-negative number or None",
            provider=provider,
        )


def scrubbed_provider_call(method: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a public adapter translate method with the leak-proof error boundary.

    Any ``ProviderError`` leaving the wrapped method is scrubbed (traceback /
    cause / context severed) and re-raised ``from None`` with every
    request-bearing local (self, items, source/target language) cleared from
    this frame, so no credential or source text survives in the propagating
    traceback's frame locals.
    """

    @functools.wraps(method)
    def wrapper(self, items, *, source_language, target_language):  # type: ignore[no-untyped-def]
        try:
            return method(
                self,
                items,
                source_language=source_language,
                target_language=target_language,
            )
        except ProviderError as error:
            safe_error = scrub_provider_error(error)
        self = None  # type: ignore[assignment]
        items = ()
        source_language = None
        target_language = ""
        raise safe_error from None

    return wrapper


def validate_extra_headers(
    extra_headers: Mapping[str, str] | None, *, provider: str
) -> None:
    """Reject non-string header names/values before they reach request building.

    A non-string key would raise ``AttributeError`` from ``name.casefold()`` deep
    in the adapter, escaping the ``except ProviderError`` scrub boundary with the
    API key still live in a traceback frame's locals. Validate eagerly instead.
    """

    if extra_headers is None:
        return
    if not isinstance(extra_headers, Mapping):
        raise ProviderConfigurationError(
            "extra_headers must be a mapping of str to str", provider=provider
        )
    for name, value in extra_headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ProviderConfigurationError(
                "extra_headers names and values must be strings", provider=provider
            )


def json_request_body(value: Any, *, provider: str) -> bytes:
    """Serialize a request as compact UTF-8 JSON with normalized failures."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ProviderRequestError(
            "Provider request could not be serialized as JSON", provider=provider
        ) from error


def send_request(
    client: HttpClient,
    method: str,
    url: str,
    *,
    provider: str,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout: float | None = None,
) -> HttpResponse:
    """Send an HTTP request and normalize pre-response transport failures."""

    failure: ProviderError | None = None
    try:
        return client.request(
            method,
            url,
            headers=headers,
            body=body,
            timeout=timeout,
        )
    except HttpTransportTimeout:
        failure = ProviderTimeoutError(
            "Provider request timed out", provider=provider
        )
    except HttpTransportConnectionError:
        failure = ProviderConnectionError(
            "Could not connect to the provider endpoint", provider=provider
        )
    except HttpTransportResponseTooLarge:
        failure = ProviderResponseError(
            "Provider response exceeded the configured byte limit",
            provider=provider,
        )
    except (TimeoutError, socket.timeout):
        failure = ProviderTimeoutError(
            "Provider request timed out", provider=provider
        )
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            failure = ProviderTimeoutError(
                "Provider request timed out", provider=provider
            )
        else:
            failure = ProviderConnectionError(
                "Could not connect to the provider endpoint", provider=provider
            )
    except OSError:
        failure = ProviderConnectionError(
            "Could not connect to the provider endpoint", provider=provider
        )
    except Exception as unexpected:  # noqa: BLE001 - normalize any client failure
        # A custom or buggy HttpClient can raise an unforeseen exception whose
        # live traceback still holds the request headers (Authorization /
        # x-api-key), body, and URL in its frame locals. Error reporters such as
        # Sentry capture frame locals by default, so an unnormalized escape here
        # would leak the credential. Force every such failure across the boundary
        # as a scrubbed ProviderError so no request-bearing frame survives.
        if isinstance(unexpected, ProviderError):
            failure = scrub_provider_error(unexpected)
        else:
            # A deterministic client bug (e.g. a wrapper that raises
            # UnicodeEncodeError on every call) is not a transport failure and
            # cannot succeed on retry: normalize it to a NON-retryable unknown
            # ProviderError rather than a retryable connection error, keeping it
            # scrubbed so no request-bearing frame survives. Genuine transport
            # failures keep their retryable mapping via the clauses above.
            failure = ProviderError(
                "provider HTTP client raised an unexpected error",
                provider=provider,
                category=ErrorCategory.UNKNOWN,
                retryable=False,
            )
        unexpected = None  # type: ignore[assignment]

    # Raise outside the transport exception handler and clear request-bearing
    # locals. This prevents a normalized error's cause/context from retaining a
    # URL query, request JSON, header secret, or injected client response.
    client = None  # type: ignore[assignment]
    url = ""
    headers = None
    body = None
    raise failure from None


def _looks_like_context_limit(response: HttpResponse) -> bool:
    try:
        body = response.text.casefold()
    except (LookupError, UnicodeError):
        # An undecodable error body is not trusted as classification input.
        return False
    markers = (
        "context_length_exceeded",
        "context length",
        "context window",
        "maximum context",
        "too many tokens",
        "token limit",
        "request too large",
        "payload too large",
        "prompt is too long",  # Anthropic Messages API token-overflow phrasing
        "maximum allowed number of tokens",
    )
    return any(marker in body for marker in markers)


def raise_for_status(response: HttpResponse, *, provider: str) -> None:
    """Map a non-success HTTP response to the public error hierarchy."""

    status = response.status_code
    if 200 <= status < 300:
        return
    if status in {413, 414} or (
        status in {400, 422} and _looks_like_context_limit(response)
    ):
        raise ProviderContextLimitError(
            "Provider context or payload limit was exceeded",
            provider=provider,
            status_code=status,
        )
    if status in {401, 403}:
        raise ProviderAuthenticationError(
            "Provider authentication failed",
            provider=provider,
            status_code=status,
        )
    if status == 408:
        raise ProviderTimeoutError(
            "Provider request timed out", provider=provider, status_code=status
        )
    if status == 429:
        raise ProviderRateLimitError(
            "Provider rate limit was exceeded",
            provider=provider,
            status_code=status,
        )
    if status in {502, 503, 504}:
        raise ProviderUnavailableError(
            "Provider is temporarily unavailable",
            provider=provider,
            status_code=status,
        )
    if 500 <= status < 600:
        raise ProviderServerError(
            "Provider reported a server error",
            provider=provider,
            status_code=status,
        )
    if 300 <= status < 400:
        raise ProviderResponseError(
            "Provider returned an unexpected redirect",
            provider=provider,
            status_code=status,
        )
    raise ProviderRequestError(
        "Provider rejected the request",
        provider=provider,
        status_code=status,
    )


def decode_json_response(response: HttpResponse, *, provider: str) -> Any:
    """Decode a successful response as JSON with a normalized error."""

    raise_for_status(response, provider=provider)
    try:
        document = response.json()
    except (
        LookupError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        # RecursionError is not a ValueError: deeply nested JSON must still be
        # normalized here rather than escaping as a raw error that carries the
        # response body in its traceback frame locals. Drop the response first
        # so the raised error's frame retains no body.
        response = None  # type: ignore[assignment]
        raise ProviderResponseError(
            "Provider returned invalid JSON", provider=provider
        ) from None
    response = None  # type: ignore[assignment]
    return document


def strict_translation_document(
    document: Any,
    expected_items: Sequence[TranslationItem],
    *,
    provider: str,
) -> list[TranslationItem]:
    """Validate an exact ``{"translations": [...]}`` ID-to-text mapping."""

    if not isinstance(document, dict) or set(document) != {"translations"}:
        raise ProviderResponseError(
            "Provider JSON must contain only a translations array",
            provider=provider,
        )
    translations = document["translations"]
    if not isinstance(translations, list):
        raise ProviderResponseError(
            "Provider translations value must be an array", provider=provider
        )

    by_id: dict[str, str] = {}
    for translated in translations:
        if not isinstance(translated, dict) or set(translated) != {"id", "text"}:
            raise ProviderResponseError(
                "Each provider translation must contain only id and text",
                provider=provider,
            )
        item_id = translated["id"]
        text = translated["text"]
        if not isinstance(item_id, str) or not isinstance(text, str):
            raise ProviderResponseError(
                "Provider translation IDs and text must be strings",
                provider=provider,
            )
        if item_id in by_id:
            raise ProviderResponseError(
                "Provider returned a duplicate translation ID", provider=provider
            )
        by_id[item_id] = text

    expected_ids = {item.id for item in expected_items}
    actual_ids = set(by_id)
    if actual_ids != expected_ids:
        raise ProviderResponseError(
            "Provider translation IDs did not exactly match the request",
            provider=provider,
        )
    return [TranslationItem(item.id, by_id[item.id]) for item in expected_items]


def decode_strict_translation_text(
    content: str,
    expected_items: Sequence[TranslationItem],
    *,
    provider: str,
) -> list[TranslationItem]:
    """Decode model text as strict JSON, rejecting prose and code fences."""

    if not isinstance(content, str) or not content.strip():
        raise ProviderResponseError(
            "Provider response did not contain translation JSON", provider=provider
        )
    try:
        document = _strict_json_loads(content)
    except (json.JSONDecodeError, ValueError, RecursionError):
        # RecursionError (deeply nested provider text) is not a ValueError; catch
        # it too so the untrusted content is cleared before raising and never
        # survives in a propagating traceback's frame locals.
        content = ""
        expected_items = ()
        raise ProviderResponseError(
            "Provider response was not strict translation JSON", provider=provider
        ) from None
    try:
        translated = strict_translation_document(
            document, expected_items, provider=provider
        )
    except ProviderResponseError as error:
        safe_error = scrub_provider_error(error)
    else:
        return translated
    content = ""
    document = None
    expected_items = ()
    raise safe_error from None


def scrub_provider_error(error: ProviderError) -> ProviderError:
    """Remove nested trace state before an adapter exposes a normalized error."""

    error.__traceback__ = None
    error.__cause__ = None
    error.__context__ = None
    return error


def model_translation_prompt(
    items: Sequence[TranslationItem],
    *,
    source_language: str | None,
    target_language: str,
) -> str:
    """Build the structured user message shared by chat-model providers."""

    request = {
        "task": "translate",
        "source_language": source_language or "auto",
        "target_language": target_language,
        "items": [{"id": item.id, "text": item.text} for item in items],
        "output_contract": {
            "type": "object",
            "only_key": "translations",
            "item_keys": ["id", "text"],
            "ids_must_match_exactly": True,
        },
    }
    return json.dumps(request, ensure_ascii=False, separators=(",", ":"))


MODEL_SYSTEM_PROMPT = (
    "You are a translation engine. Preserve meaning, tone, punctuation, and "
    "formatting. Return only one valid JSON object with exactly this shape: "
    '{"translations":[{"id":"same input id","text":"translated text"}]}. '
    "Return every input ID exactly once, add no IDs, and include no prose or "
    "Markdown fences."
)

MODEL_CORRECTIVE_PROMPT = (
    "Corrective retry: the previous response violated the required JSON output "
    "contract. Translate the same items again. "
    + MODEL_SYSTEM_PROMPT
)
