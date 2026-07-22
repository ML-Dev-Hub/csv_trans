"""Core provider contracts and a dependency-free HTTP client."""

from __future__ import annotations

import json
import math
import socket
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


@dataclass(frozen=True, slots=True)
class TranslationItem:
    """One translation unit with a caller-owned stable identifier."""

    id: str
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise TypeError("TranslationItem.id must be a non-empty string")
        if not isinstance(self.text, str):
            raise TypeError("TranslationItem.text must be a string")


@runtime_checkable
class Translator(Protocol):
    """Structural contract implemented by every translation provider."""

    provider_id: str
    name: str
    base_url: str | None
    is_remote: bool

    def translate(
        self,
        items: Sequence[TranslationItem],
        *,
        source_language: str | None,
        target_language: str,
    ) -> list[TranslationItem]:
        """Translate *items* while preserving their IDs and input order."""
        ...


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Minimal HTTP response object used by injectable provider clients."""

    status_code: int
    body: bytes | str
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Strictly decode the body using its declared charset or UTF-8.

        Invalid byte sequences and unknown charset names are intentionally not
        repaired or replaced.  Provider adapters normalize those failures at
        the response boundary instead of parsing altered provider output.
        """

        if isinstance(self.body, str):
            return self.body

        charset = "utf-8"
        content_type = next(
            (
                value
                for key, value in self.headers.items()
                if key.casefold() == "content-type"
            ),
            "",
        )
        for part in content_type.split(";")[1:]:
            key, separator, value = part.strip().partition("=")
            if separator and key.casefold() == "charset" and value.strip():
                charset = value.strip().strip('"\'')
                break
        return self.body.decode(charset, errors="strict")

    def json(self) -> Any:
        """Decode strict JSON, rejecting duplicate keys and non-finite values."""

        return _strict_json_loads(self.text)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting ambiguous duplicate names."""

    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise ValueError("duplicate JSON object name")
        value[name] = item
    return value


def _reject_json_constant(value: str) -> Any:
    """Reject Python's non-standard NaN and Infinity JSON extensions."""

    raise ValueError("non-finite JSON number")


def _strict_json_float(value: str) -> float:
    """Reject valid numeric spellings that overflow to infinity locally."""

    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _strict_json_loads(value: str) -> Any:
    """Parse standards-compliant JSON without ambiguous extensions."""

    return json.loads(
        value,
        object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant,
        parse_float=_strict_json_float,
    )


@runtime_checkable
class HttpClient(Protocol):
    """Small synchronous HTTP contract that is straightforward to fake.

    Implementations must not follow redirects.  They must return every HTTP
    status, including 3xx responses, to the provider adapter unchanged.  This
    prevents an injected transport from silently sending translation content
    or credentials to a destination that was not validated by the provider.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        """Send one request without redirects and return every HTTP status."""
        ...


class HttpTransportError(RuntimeError):
    """Base class for pre-response transport failures."""


class HttpTransportTimeout(HttpTransportError):
    """The HTTP transport exceeded its timeout."""


class HttpTransportConnectionError(HttpTransportError):
    """The HTTP transport could not connect to the endpoint."""


class HttpTransportResponseTooLarge(HttpTransportError):
    """The HTTP response exceeded the client's configured safety limit."""


class _RejectRedirects(HTTPRedirectHandler):
    """Prevent implicit endpoint changes and accidental privacy-boundary leaks."""

    def redirect_request(  # type: ignore[override]
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Mapping[str, str],
        new_url: str,
    ) -> None:
        return None


class UrllibHttpClient:
    """Synchronous HTTP client honoring :class:`HttpClient`'s no-redirect rule."""

    DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
    DEFAULT_TIMEOUT = 60.0

    def __init__(
        self,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
        ):
            raise ValueError("max_response_bytes must be a positive integer")
        self.max_response_bytes = max_response_bytes
        # Implicit environment/system proxies can route even loopback traffic
        # outside a validated local-only boundary. Applications that require a
        # trusted proxy can inject an explicit HttpClient instead.
        self._opener = build_opener(ProxyHandler({}), _RejectRedirects())

    def _read_bounded(self, response: Any) -> bytes:
        response_headers = getattr(response, "headers", None)
        content_length = (
            response_headers.get("Content-Length")
            if response_headers is not None
            else None
        )
        if content_length is not None:
            try:
                if int(content_length) > self.max_response_bytes:
                    raise HttpTransportResponseTooLarge(
                        "HTTP response exceeded the configured byte limit"
                    )
            except ValueError:
                # Invalid Content-Length values are ignored; the bounded read
                # below remains authoritative.
                pass
        body = response.read(self.max_response_bytes + 1)
        if len(body) > self.max_response_bytes:
            raise HttpTransportResponseTooLarge(
                "HTTP response exceeded the configured byte limit"
            )
        return body

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        request_headers = {"User-Agent": "csv-trans/2"}
        if headers:
            request_headers.update(headers)
        request = Request(
            url=url,
            data=body,
            headers=request_headers,
            method=method.upper(),
        )

        # In urllib, timeout=None means "use the global default socket timeout,"
        # which is itself None unless set process-wide, i.e. block forever.
        # Substitute a concrete per-operation default so a caller that omits a
        # timeout cannot hang indefinitely (an explicit timeout is respected).
        effective_timeout = self.DEFAULT_TIMEOUT if timeout is None else timeout
        try:
            with self._opener.open(request, timeout=effective_timeout) as response:
                return HttpResponse(
                    status_code=response.status,
                    body=self._read_bounded(response),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as error:
            # HTTP statuses, including redirects rejected above, belong to the
            # provider adapter so it can normalize them consistently.
            response_headers = (
                dict(error.headers.items()) if error.headers is not None else {}
            )
            try:
                response_body = self._read_bounded(error)
            finally:
                error.close()
            return HttpResponse(error.code, response_body, response_headers)
        except (TimeoutError, socket.timeout) as error:
            raise HttpTransportTimeout("HTTP request timed out") from error
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise HttpTransportTimeout("HTTP request timed out") from error
            raise HttpTransportConnectionError(
                "HTTP request could not connect to the endpoint"
            ) from error
        except OSError as error:
            raise HttpTransportConnectionError(
                "HTTP request could not connect to the endpoint"
            ) from error


__all__ = [
    "HttpClient",
    "HttpResponse",
    "TranslationItem",
    "Translator",
    "UrllibHttpClient",
]
