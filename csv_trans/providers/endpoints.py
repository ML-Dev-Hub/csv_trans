"""Endpoint validation helpers used by providers and privacy preflight code."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import SplitResult, urlsplit, urlunsplit

from csv_trans.exceptions import ProviderConfigurationError


def _normalized_host(host: str) -> str:
    return host.strip().casefold().rstrip(".")


def _is_loopback_host(host: str) -> bool:
    normalized = _normalized_host(host)
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_endpoint(
    url: str,
    *,
    provider: str = "endpoint",
    allow_insecure_http: bool = False,
) -> str:
    """Validate and normalize an HTTP(S) provider base URL.

    Remote HTTPS endpoints are valid here. Plain HTTP is accepted automatically
    only for loopback; trusted LAN HTTP requires an explicit insecure opt-in.
    Privacy policy is intentionally separate; use
    :func:`validate_local_endpoint` when a local-only mode is required.
    Query strings, fragments, and embedded credentials are rejected because a
    base URL must identify only an endpoint hierarchy.
    """

    if not isinstance(url, str) or not url.strip():
        raise ProviderConfigurationError(
            "A non-empty provider endpoint is required", provider=provider
        )

    try:
        parsed = urlsplit(url.strip())
    except ValueError as error:
        raise ProviderConfigurationError(
            "Provider endpoint is not a valid URL", provider=provider
        ) from error
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ProviderConfigurationError(
            "Provider endpoints must use http or https", provider=provider
        )
    try:
        host = parsed.hostname
    except ValueError as error:
        raise ProviderConfigurationError(
            "Provider endpoint contains an invalid host", provider=provider
        ) from error
    if host is None:
        raise ProviderConfigurationError(
            "Provider endpoint must include a host", provider=provider
        )
    if any(character.isspace() for character in host):
        raise ProviderConfigurationError(
            "Provider endpoint host must not contain whitespace", provider=provider
        )
    if (
        parsed.scheme.casefold() == "http"
        and not _is_loopback_host(host)
        and not allow_insecure_http
    ):
        raise ProviderConfigurationError(
            "Non-loopback provider endpoints require https; explicitly opt in "
            "only for a trusted local network",
            provider=provider,
        )
    if parsed.username is not None or parsed.password is not None:
        raise ProviderConfigurationError(
            "Provider endpoint must not contain credentials", provider=provider
        )
    if parsed.query or parsed.fragment:
        raise ProviderConfigurationError(
            "Provider endpoint must not contain a query or fragment",
            provider=provider,
        )
    try:
        parsed.port
    except ValueError as error:
        raise ProviderConfigurationError(
            "Provider endpoint contains an invalid port", provider=provider
        ) from error

    normalized = SplitResult(
        scheme=parsed.scheme.casefold(),
        netloc=parsed.netloc,
        path=parsed.path.rstrip("/"),
        query="",
        fragment="",
    )
    return urlunsplit(normalized)


def is_remote_endpoint(url: str) -> bool:
    """Return whether *url* targets a non-loopback host."""

    normalized = validate_endpoint(url, allow_insecure_http=True)
    host = urlsplit(normalized).hostname
    assert host is not None
    return not _is_loopback_host(host)


def validate_local_endpoint(
    url: str,
    *,
    approved_local_hosts: Iterable[str] = (),
    provider: str = "endpoint",
) -> str:
    """Require a loopback endpoint or an explicitly approved local hostname.

    Hostnames are compared exactly after case folding and removing a trailing
    dot. This helper performs no DNS lookup and never substitutes or falls back
    to a remote endpoint.
    """

    normalized = validate_endpoint(
        url, provider=provider, allow_insecure_http=True
    )
    host = urlsplit(normalized).hostname
    assert host is not None
    normalized_host = _normalized_host(host)
    approved = {
        _normalized_host(candidate)
        for candidate in approved_local_hosts
        if isinstance(candidate, str) and candidate.strip()
    }
    if not _is_loopback_host(normalized_host) and normalized_host not in approved:
        raise ProviderConfigurationError(
            "Local-only mode requires a loopback or explicitly approved host",
            provider=provider,
        )
    return normalized


__all__ = [
    "is_remote_endpoint",
    "validate_endpoint",
    "validate_local_endpoint",
]
