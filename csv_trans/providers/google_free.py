"""Experimental no-key Google web translation provider.

This adapter uses undocumented public web endpoints, not Google Cloud
Translation. It can change, throttle, or stop working without notice and should
not be treated as a stable or private service.
"""

from __future__ import annotations

from collections.abc import Sequence
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

from csv_trans.exceptions import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderContextLimitError,
    ProviderError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

from ._common import (
    decode_json_response,
    raise_for_status,
    scrubbed_provider_call,
    send_request,
    validate_timeout,
    validate_translation_request,
)
from .base import HttpClient, TranslationItem, UrllibHttpClient
from .endpoints import is_remote_endpoint, validate_endpoint


class _MobileTranslationParser(HTMLParser):
    """Extract Google mobile's translated result without Beautiful Soup.

    Capture is bounded by ``<div>`` nesting alone: only the matching ``</div>``
    that closes the result container ends capture. Counting divs (rather than
    every element) means an unclosed inner formatting tag cannot run capture off
    the end of the page into footer/script text, and a stray non-div end tag
    cannot prematurely truncate the translation. ``<script>``/``<style>`` bodies
    are suppressed so page code never contaminates the result.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._div_depth = 0
        self._suppress_depth = 0
        self._finished = False
        self._parts: list[str] = []

    @property
    def translation(self) -> str | None:
        # Require the result container to have closed cleanly. A truncated or
        # malformed response that leaves the container open at EOF must not be
        # published as a complete translation replacing a selected field.
        if not self._finished or not self._parts:
            return None
        return "".join(self._parts)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if self._finished:
            return
        normalized_tag = tag.casefold()
        if self._div_depth:
            if normalized_tag in {"script", "style"}:
                self._suppress_depth += 1
            elif normalized_tag == "div":
                self._div_depth += 1
            return
        if normalized_tag != "div":
            return
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if "result-container" in classes or "t0" in classes:
            self._div_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self._finished or not self._div_depth:
            return
        normalized_tag = tag.casefold()
        if self._suppress_depth:
            if normalized_tag in {"script", "style"}:
                self._suppress_depth -= 1
            return
        if normalized_tag == "div":
            self._div_depth -= 1
            if self._div_depth == 0:
                self._finished = True

    def handle_data(self, data: str) -> None:
        if self._div_depth and not self._suppress_depth:
            self._parts.append(data)


class GoogleFreeProvider:
    """Experimental, no-key adapter for undocumented Google web endpoints."""

    provider_id = "google-free"
    name = provider_id
    experimental = True
    PRIMARY_URL = "https://translate.googleapis.com/translate_a/single"
    FALLBACK_URL = "https://translate.google.com/m"

    def __init__(
        self,
        *,
        http_client: HttpClient | None = None,
        timeout: float = 10.0,
        allow_html_fallback: bool = True,
    ) -> None:
        validate_timeout(timeout, provider=self.provider_id)
        self.base_url = validate_endpoint(self.PRIMARY_URL, provider=self.provider_id)
        self.fallback_url = validate_endpoint(
            self.FALLBACK_URL, provider=self.provider_id
        )
        self.is_remote = is_remote_endpoint(self.base_url)
        self.timeout = timeout
        self.allow_html_fallback = allow_html_fallback
        self._http_client = http_client or UrllibHttpClient()

    @property
    def recipient_endpoints(self) -> tuple[str, ...]:
        """Endpoints that may receive text under the current fallback policy."""

        if self.allow_html_fallback:
            return (self.base_url, self.fallback_url)
        return (self.base_url,)

    @scrubbed_provider_call
    def translate(
        self,
        items: Sequence[TranslationItem],
        *,
        source_language: str | None,
        target_language: str,
    ) -> list[TranslationItem]:
        """Translate items in order, using mobile HTML only after primary failure."""

        return self._translate_items(
            items,
            source_language=source_language,
            target_language=target_language,
        )

    def _translate_items(
        self,
        items: Sequence[TranslationItem],
        *,
        source_language: str | None,
        target_language: str,
    ) -> list[TranslationItem]:

        validated = validate_translation_request(
            self.provider_id,
            items,
            source_language=source_language,
            target_language=target_language,
        )
        source = source_language or "auto"
        translated: list[TranslationItem] = []
        for item in validated:
            if item.text == "":
                translated.append(item)
                continue
            text = self._translate_one(
                item.text,
                source_language=source,
                target_language=target_language,
            )
            translated.append(TranslationItem(item.id, text))
        return translated

    def _translate_one(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> str:
        try:
            return self._translate_primary(
                text,
                source_language=source_language,
                target_language=target_language,
            )
        except ProviderAuthenticationError as primary_error:
            # This undocumented no-key endpoint commonly uses 403 to reject a
            # particular web surface.  A 401 is not treated as equivalent.
            if primary_error.status_code != 403:
                raise
            if not self.allow_html_fallback:
                raise
            try:
                return self._translate_mobile(
                    text,
                    source_language=source_language,
                    target_language=target_language,
                )
            except ProviderError as fallback_error:
                raise fallback_error from primary_error
        except (
            ProviderConnectionError,
            ProviderContextLimitError,
            ProviderRequestError,
            ProviderResponseError,
            ProviderServerError,
            ProviderTimeoutError,
            ProviderUnavailableError,
        ) as primary_error:
            if not self.allow_html_fallback:
                raise
            try:
                return self._translate_mobile(
                    text,
                    source_language=source_language,
                    target_language=target_language,
                )
            except ProviderError as fallback_error:
                raise fallback_error from primary_error

    def _translate_primary(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> str:
        try:
            query = urlencode(
                {
                    "client": "gtx",
                    "sl": source_language,
                    "tl": target_language,
                    "dt": "t",
                    "q": text,
                }
            )
        except UnicodeError as error:
            raise ProviderRequestError(
                "Translation text could not be encoded for the provider",
                provider=self.provider_id,
            ) from error
        response = send_request(
            self._http_client,
            "GET",
            f"{self.base_url}?{query}",
            provider=self.provider_id,
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        payload = decode_json_response(response, provider=self.provider_id)
        return self._parse_primary_payload(payload)

    def _parse_primary_payload(self, payload: Any) -> str:
        try:
            segments = payload[0]
            if not isinstance(segments, list) or not segments:
                raise TypeError
            translated_parts: list[str] = []
            for segment in segments:
                if (
                    not isinstance(segment, list)
                    or not segment
                    or not isinstance(segment[0], str)
                ):
                    raise TypeError
                translated_parts.append(segment[0])
        except (IndexError, KeyError, TypeError) as error:
            raise ProviderResponseError(
                "Google free endpoint returned an unexpected JSON shape",
                provider=self.provider_id,
            ) from error
        return "".join(translated_parts)

    def _translate_mobile(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> str:
        try:
            query = urlencode(
                {
                    "sl": source_language,
                    "tl": target_language,
                    "q": text,
                }
            )
        except UnicodeError as error:
            raise ProviderRequestError(
                "Translation text could not be encoded for the provider",
                provider=self.provider_id,
            ) from error
        response = send_request(
            self._http_client,
            "GET",
            f"{self.fallback_url}?{query}",
            provider=self.provider_id,
            headers={"Accept": "text/html"},
            timeout=self.timeout,
        )
        raise_for_status(response, provider=self.provider_id)
        parser = _MobileTranslationParser()
        try:
            parser.feed(response.text)
        except (LookupError, UnicodeError) as error:
            raise ProviderResponseError(
                "Google mobile endpoint returned undecodable text",
                provider=self.provider_id,
            ) from error
        parser.close()
        translation = parser.translation
        if translation is None:
            raise ProviderResponseError(
                "Google mobile endpoint did not contain a translation",
                provider=self.provider_id,
            )
        return translation


__all__ = ["GoogleFreeProvider"]
