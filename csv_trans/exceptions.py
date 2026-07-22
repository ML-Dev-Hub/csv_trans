"""Public exception types shared by translation providers.

Provider adapters normalize transport-, HTTP-, and response-level failures into
this hierarchy so callers can make retry decisions without depending on a
provider SDK or HTTP library.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCategory(StrEnum):
    """Stable, provider-independent error categories."""

    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    CONTEXT_LIMIT = "context_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE = "invalid_response"
    SERVER = "server"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ProviderError(RuntimeError):
    """Base class for errors that cross the provider boundary.

    Parameters are deliberately small and safe to expose in logs. Provider
    response bodies are not retained because they can echo source text or
    contain credentials.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.category = category
        self.retryable = retryable
        self.status_code = status_code


class _CategorizedProviderError(ProviderError):
    """Internal helper for fixed-category public exception classes."""

    error_category = ErrorCategory.UNKNOWN
    default_retryable = False
    default_status_code: int | None = None

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            category=self.error_category,
            retryable=self.default_retryable,
            status_code=(
                self.default_status_code if status_code is None else status_code
            ),
        )


class ProviderConfigurationError(_CategorizedProviderError):
    """The provider was configured with an invalid or missing value."""

    error_category = ErrorCategory.CONFIGURATION


class ProviderAuthenticationError(_CategorizedProviderError):
    """Authentication or authorization failed."""

    error_category = ErrorCategory.AUTHENTICATION


class ProviderRateLimitError(_CategorizedProviderError):
    """The provider rejected the request because a quota was exceeded."""

    error_category = ErrorCategory.RATE_LIMIT
    default_retryable = True
    default_status_code = 429


class ProviderContextLimitError(_CategorizedProviderError):
    """The request exceeded a provider context or payload limit."""

    error_category = ErrorCategory.CONTEXT_LIMIT


class ProviderTimeoutError(_CategorizedProviderError):
    """The provider request timed out."""

    error_category = ErrorCategory.TIMEOUT
    default_retryable = True


class ProviderConnectionError(_CategorizedProviderError):
    """A connection to the configured provider endpoint could not be made."""

    error_category = ErrorCategory.CONNECTION
    default_retryable = True


class ProviderRequestError(_CategorizedProviderError):
    """The provider rejected a semantically invalid request."""

    error_category = ErrorCategory.INVALID_REQUEST


class ProviderResponseError(_CategorizedProviderError):
    """The provider returned malformed or contract-breaking output."""

    error_category = ErrorCategory.INVALID_RESPONSE


class ProviderServerError(_CategorizedProviderError):
    """The provider reported an internal server failure."""

    error_category = ErrorCategory.SERVER
    default_retryable = True


class ProviderUnavailableError(_CategorizedProviderError):
    """The provider endpoint is temporarily unavailable."""

    error_category = ErrorCategory.UNAVAILABLE
    default_retryable = True


__all__ = [
    "ErrorCategory",
    "ProviderAuthenticationError",
    "ProviderConfigurationError",
    "ProviderConnectionError",
    "ProviderContextLimitError",
    "ProviderError",
    "ProviderRateLimitError",
    "ProviderRequestError",
    "ProviderResponseError",
    "ProviderServerError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
]
