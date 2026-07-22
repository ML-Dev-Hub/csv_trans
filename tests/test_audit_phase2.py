"""Phase-2 exhaustive-audit regression + coverage tests.

Locks in the HIGH/MEDIUM fixes from the second (staircase) audit and closes the
coverage gaps it surfaced (utils.py, the context-limit classifier, the endpoint
loopback bypass corpus, google-free fallback chaining, property round-trips).
All offline and deterministic.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests._support import FakeHttpClient

from csv_trans.providers.base import HttpResponse, TranslationItem


def _anthropic_envelope(mapping: dict[str, str]) -> HttpResponse:
    content = json.dumps({"translations": [{"id": k, "text": v} for k, v in mapping.items()]})
    body = json.dumps({"content": [{"type": "text", "text": content}]}).encode("utf-8")
    return HttpResponse(200, body, {"Content-Type": "application/json"})


def _openai_envelope(mapping: dict[str, str]) -> HttpResponse:
    content = json.dumps({"translations": [{"id": k, "text": v} for k, v in mapping.items()]})
    body = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
    return HttpResponse(200, body, {"Content-Type": "application/json"})


# --------------------------------------------------------------------------- #
# HIGH fixes
# --------------------------------------------------------------------------- #
class NulByteEncodingRegressionTests(unittest.TestCase):
    """csvio.py HIGH: BOM-less UTF-16/32 (NUL bytes) must not decode as utf-8."""

    def test_bom_less_utf16_is_rejected_not_decoded_as_utf8(self) -> None:
        from csv_trans.csvio import CsvInputError, detect_encoding

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "u16.csv"
            path.write_bytes("id,name\n1,abc\n".encode("utf-16-le"))
            with self.assertRaises(CsvInputError) as ctx:
                detect_encoding(path)
            self.assertIn("NUL", str(ctx.exception))

    def test_plain_utf8_still_detected(self) -> None:
        from csv_trans.csvio import detect_encoding

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "u8.csv"
            path.write_text("id,name\n1,café\n", encoding="utf-8")
            self.assertEqual(detect_encoding(path), "utf-8")


class GoogleParserUnclosedRegressionTests(unittest.TestCase):
    """google_free.py HIGH: an unclosed container must not publish as complete."""

    def _translation(self, html: str) -> str | None:
        from csv_trans.providers.google_free import _MobileTranslationParser

        parser = _MobileTranslationParser()
        parser.feed(html)
        parser.close()
        return parser.translation

    def test_unclosed_container_returns_none(self) -> None:
        self.assertIsNone(self._translation('<div class="result-container">partial trans'))

    def test_closed_container_returns_text(self) -> None:
        self.assertEqual(self._translation('<div class="result-container">done</div>'), "done")


class ExtraHeadersValidationRegressionTests(unittest.TestCase):
    """openai/anthropic HIGH: non-string extra_headers must be rejected at init."""

    def test_openai_rejects_non_string_header_key(self) -> None:
        from csv_trans.exceptions import ProviderConfigurationError
        from csv_trans.providers.openai_compatible import OpenAICompatibleProvider

        with self.assertRaises(ProviderConfigurationError):
            OpenAICompatibleProvider(
                model="m", base_url="https://api.example/v1", api_key="K",
                extra_headers={123: "x"},
            )

    def test_anthropic_rejects_non_string_header_value(self) -> None:
        from csv_trans.exceptions import ProviderConfigurationError
        from csv_trans.providers.anthropic import AnthropicProvider

        with self.assertRaises(ProviderConfigurationError):
            AnthropicProvider(
                model="m", api_key="K", base_url="https://api.example",
                extra_headers={"x-trace": 5},
            )


# --------------------------------------------------------------------------- #
# MEDIUM fixes
# --------------------------------------------------------------------------- #
class CompositeSecretHeaderRegressionTests(unittest.TestCase):
    """selection.py MEDIUM: composite secret/identifier headers must be skipped."""

    def test_composite_credential_and_identifier_columns_not_selected(self) -> None:
        from csv_trans.selection import resolve_columns

        headers = ["client_secret", "user_id", "session_token", "access_token", "comment"]
        sample = [["aB+xyz==longsecretval", "1001", "tok_abc123456", "at_xyz789012", "please translate this"]]
        selected, _ = resolve_columns(headers, sample, None)
        for index in range(4):
            self.assertNotIn(index, selected, headers[index])
        self.assertIn(4, selected)


class ControlCharHostRegressionTests(unittest.TestCase):
    """endpoints.py MEDIUM: C0 controls / DEL in host must be rejected."""

    def test_control_characters_in_host_rejected(self) -> None:
        from csv_trans.exceptions import ProviderConfigurationError
        from csv_trans.providers.endpoints import validate_endpoint

        for bad in ("http://12\x007.0.0.1/v1", "http://ho\x01st/v1", "http://ho\x7fst/v1"):
            with self.assertRaises(ProviderConfigurationError):
                validate_endpoint(bad)

    def test_plain_host_still_valid(self) -> None:
        from csv_trans.providers.endpoints import validate_endpoint

        self.assertEqual(
            validate_endpoint("https://api.example.com/v1"), "https://api.example.com/v1"
        )


class EncodingValidationRegressionTests(unittest.TestCase):
    """models.py MEDIUM: input encoding is validated eagerly (with sentinels)."""

    def test_bogus_encoding_rejected_at_construction(self) -> None:
        from csv_trans.models import TranslationConfig

        for bad in ("bogus-enc", 123):
            with self.assertRaises(ValueError):
                TranslationConfig(source_language="en", target_language="fr", encoding=bad)

    def test_detect_sentinels_and_real_codecs_accepted(self) -> None:
        from csv_trans.models import TranslationConfig

        for good in ("utf-8", "auto", "detect", "latin-1", None):
            TranslationConfig(source_language="en", target_language="fr", encoding=good)


class WhitespacePaddedHeaderRegressionTests(unittest.TestCase):
    """openai/anthropic MEDIUM: a padded protected header must not reach the wire."""

    def test_anthropic_strips_before_comparing_protected_headers(self) -> None:
        from csv_trans.providers.anthropic import AnthropicProvider

        client = FakeHttpClient(_anthropic_envelope({"r0c0s0": "bonjour"}))
        provider = AnthropicProvider(
            model="m", api_key="REAL-KEY", base_url="https://api.anthropic.com",
            http_client=client, extra_headers={"x-api-key ": "EVIL", "anthropic-version ": "9"},
        )
        provider.translate(
            [TranslationItem("r0c0s0", "hello")], source_language="en", target_language="fr"
        )
        sent = client.requests[0]["headers"]
        self.assertEqual(sent["x-api-key"], "REAL-KEY")
        self.assertNotIn("x-api-key ", sent)
        self.assertNotIn("anthropic-version ", sent)


# --------------------------------------------------------------------------- #
# Coverage: context-limit classifier
# --------------------------------------------------------------------------- #
class ContextLimitClassifierTests(unittest.TestCase):
    """_common.py: the marker-based 400/422 context-limit classifier."""

    def _raise(self, status: int, body: bytes):
        from csv_trans.providers._common import raise_for_status

        raise_for_status(HttpResponse(status, body, {"Content-Type": "application/json"}), provider="p")

    def test_marker_bodies_map_to_context_limit(self) -> None:
        from csv_trans.exceptions import ProviderContextLimitError

        markers = [
            b'{"error":"context_length_exceeded"}',
            b'{"error":"prompt is too long"}',
            b'{"error":"this model has a maximum context of 8k"}',
            b'{"error":"too many tokens in request"}',
        ]
        for status in (400, 422):
            for body in markers:
                with self.assertRaises(ProviderContextLimitError, msg=f"{status} {body!r}"):
                    self._raise(status, body)

    def test_generic_400_without_marker_is_request_error(self) -> None:
        from csv_trans.exceptions import ProviderRequestError

        with self.assertRaises(ProviderRequestError):
            self._raise(400, b'{"error":"bad field"}')

    def test_413_and_414_always_context_limit(self) -> None:
        from csv_trans.exceptions import ProviderContextLimitError

        for status in (413, 414):
            with self.assertRaises(ProviderContextLimitError):
                self._raise(status, b"too big")

    def test_undecodable_body_is_not_trusted_as_context_limit(self) -> None:
        from csv_trans.exceptions import ProviderRequestError

        # An undecodable body must fall through to the generic 400 handling.
        with self.assertRaises(ProviderRequestError):
            from csv_trans.providers._common import raise_for_status

            raise_for_status(
                HttpResponse(400, b"\xff\xfe\x00", {"Content-Type": "application/json; charset=utf-8"}),
                provider="p",
            )


# --------------------------------------------------------------------------- #
# Coverage: endpoint loopback bypass corpus
# --------------------------------------------------------------------------- #
class LoopbackBypassCorpusTests(unittest.TestCase):
    """endpoints.py: lock the accept/reject verdict for the bypass corpus."""

    LOOPBACK = ["127.0.0.1", "localhost", "[::1]"]
    NON_LOOPBACK = [
        "2130706433", "0x7f000001", "127.1", "0177.0.0.1", "0.0.0.0",
        "127.000.000.001", "evil.localhost", "127.0.0.1.evil.com",
        "8.8.8.8", "example.com",
    ]

    def test_loopback_forms_accepted(self) -> None:
        from csv_trans.providers.endpoints import validate_local_endpoint

        for host in self.LOOPBACK:
            validate_local_endpoint(f"http://{host}/v1")  # must not raise

    def test_non_loopback_forms_rejected(self) -> None:
        from csv_trans.exceptions import ProviderConfigurationError
        from csv_trans.providers.endpoints import validate_local_endpoint

        for host in self.NON_LOOPBACK:
            with self.assertRaises(ProviderConfigurationError, msg=host):
                validate_local_endpoint(f"http://{host}/v1")

    def test_credential_and_query_forms_rejected(self) -> None:
        from csv_trans.exceptions import ProviderConfigurationError
        from csv_trans.providers.endpoints import validate_endpoint

        for url in ("http://127.0.0.1@evil.com/v1", "https://h/v1?x=1", "https://h/v1#f"):
            with self.assertRaises(ProviderConfigurationError):
                validate_endpoint(url)


# --------------------------------------------------------------------------- #
# Coverage: google-free fallback chaining
# --------------------------------------------------------------------------- #
class GoogleFallbackChainingTests(unittest.TestCase):
    """google_free.py: 403 falls back, 401 does not, disabled fallback re-raises."""

    def _provider(self, *outcomes, allow_html_fallback=True):
        from csv_trans.providers.google_free import GoogleFreeProvider

        return GoogleFreeProvider(
            http_client=FakeHttpClient(*outcomes), timeout=5, allow_html_fallback=allow_html_fallback,
        ), None

    def _one(self, provider):
        return provider.translate(
            [TranslationItem("r0c0s0", "hello")], source_language="en", target_language="fr"
        )

    def test_403_primary_falls_back_to_mobile_html(self) -> None:
        provider, _ = self._provider(
            HttpResponse(403, b"forbidden"),
            HttpResponse(200, b'<div class="result-container">bonjour</div>'),
        )
        out = self._one(provider)
        self.assertEqual(out[0].text, "bonjour")
        self.assertEqual(len(provider._http_client.requests), 2)

    def test_401_primary_does_not_fall_back(self) -> None:
        from csv_trans.exceptions import ProviderAuthenticationError

        provider, _ = self._provider(HttpResponse(401, b"unauthorized"))
        with self.assertRaises(ProviderAuthenticationError):
            self._one(provider)
        self.assertEqual(len(provider._http_client.requests), 1)

    def test_disabled_fallback_reraises_on_403(self) -> None:
        from csv_trans.exceptions import ProviderAuthenticationError

        provider, _ = self._provider(HttpResponse(403, b"forbidden"), allow_html_fallback=False)
        with self.assertRaises(ProviderAuthenticationError):
            self._one(provider)
        self.assertEqual(len(provider._http_client.requests), 1)

    def test_fallback_also_failing_propagates_fallback_error(self) -> None:
        from csv_trans.exceptions import ProviderServerError

        provider, _ = self._provider(HttpResponse(403, b"forbidden"), HttpResponse(500, b"boom"))
        with self.assertRaises(ProviderServerError):
            self._one(provider)
        self.assertEqual(len(provider._http_client.requests), 2)


class ProtectedTokenCouplingTests(unittest.TestCase):
    """chunking.py: every _PROTECTED construct must survive the fast-path prefilter.

    The has_protected_marker prefilter in segment_text short-circuits before the
    _PROTECTED regex runs. If a future edit adds a regex alternative whose trigger
    character is not in the prefilter, that token would silently reach a provider.
    This asserts each documented construct actually yields a protected segment.
    """

    def test_every_protected_construct_is_protected(self) -> None:
        from csv_trans.chunking import segment_text

        samples = {
            "http": "go http://x.io/a end",
            "https": "go https://x.io/a end",
            "www": "go www.example.com end",
            "email": "mail a@b.co end",
            "double_brace": "hi {{name}} end",
            "dollar_brace": "hi ${VAR} end",
            "single_brace": "hi {0} end",
            "percent_named": "hi %(name)s end",
            "percent_simple": "count %d items",
            "angle_tag": "press <b> now",
        }
        for label, text in samples.items():
            segments = segment_text(text, 100)
            protected = [s.text for s in segments if not s.translatable and s.text.strip()]
            self.assertTrue(protected, f"{label!r}: no protected token for {text!r}")


# --------------------------------------------------------------------------- #
# Property-based invariants (Hypothesis)
# --------------------------------------------------------------------------- #
try:
    from hypothesis import given, settings
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover - stdlib-only CI
    _HAS_HYPOTHESIS = False

    def settings(*_args, **_kwargs):  # noqa: D103 - inert decorator stand-in
        return lambda fn: fn

    given = settings

    class _StrategyStub:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    st = _StrategyStub()  # type: ignore[assignment]


@unittest.skipUnless(_HAS_HYPOTHESIS, "hypothesis not installed")
class PropertyInvariantTests(unittest.TestCase):
    @settings(max_examples=400, deadline=None)
    @given(st.text(), st.integers(min_value=1, max_value=40))
    def test_chunking_identity_round_trip_is_lossless(self, text, max_chars) -> None:
        from csv_trans.chunking import reconstruct_segments, segment_text

        for preserve in (True, False):
            segments = segment_text(text, max_chars, preserve_placeholders=preserve)
            identity = {
                index: seg.text for index, seg in enumerate(segments) if seg.translatable
            }
            self.assertEqual(reconstruct_segments(segments, identity), text)

    @settings(max_examples=300, deadline=None)
    @given(st.text())
    def test_selection_classifiers_never_raise(self, value) -> None:
        from csv_trans.selection import is_machine_value, is_numeric, should_translate_cell

        is_numeric(value)
        is_machine_value(value)
        should_translate_cell(value)


# --------------------------------------------------------------------------- #
# Coverage: LLM adapter config validation, corrective retry, malformed extract
# --------------------------------------------------------------------------- #
class OpenAIAdapterCoverageTests(unittest.TestCase):
    def _provider(self, response, **kwargs):
        from csv_trans.providers.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            model="m", base_url="https://api.example/v1", api_key="K",
            http_client=FakeHttpClient(response), **kwargs,
        )

    def test_invalid_config_values_rejected(self) -> None:
        from csv_trans.exceptions import ProviderConfigurationError
        from csv_trans.providers.openai_compatible import OpenAICompatibleProvider

        base = dict(base_url="https://api.example/v1", api_key="K")
        bad = [
            dict(model="  "),
            dict(model="m", timeout=0),
            dict(model="m", timeout=float("nan")),
            dict(model="m", temperature=-1),
            dict(model="m", max_tokens=0),
            dict(model="m", max_tokens=True),
            dict(model="m", instruction_role="root"),
            dict(model="m", response_format="no"),
            dict(model="m", api_key=5),
        ]
        for overrides in bad:
            kwargs = {**base, **overrides}
            kwargs.setdefault("model", "m")
            with self.assertRaises(ProviderConfigurationError, msg=str(overrides)):
                OpenAICompatibleProvider(**kwargs)

    def test_corrective_retry_returns_translation(self) -> None:
        provider = self._provider(_openai_envelope({"r0c0s0": "hola"}))
        out = provider.translate_corrective(
            [TranslationItem("r0c0s0", "hi")], source_language="en", target_language="es"
        )
        self.assertEqual(out[0].text, "hola")

    def test_malformed_envelope_raises_response_error(self) -> None:
        from csv_trans.exceptions import ProviderResponseError

        provider = self._provider(
            HttpResponse(200, json.dumps({"choices": []}).encode(), {"Content-Type": "application/json"})
        )
        with self.assertRaises(ProviderResponseError):
            provider.translate(
                [TranslationItem("r0c0s0", "hi")], source_language="en", target_language="es"
            )

    def test_instruction_role_host_detection(self) -> None:
        from csv_trans.providers.openai_compatible import OpenAICompatibleProvider

        official = OpenAICompatibleProvider(model="m", base_url="https://api.openai.com/v1", api_key="K")
        custom = OpenAICompatibleProvider(model="m", base_url="https://api.example/v1", api_key="K")
        self.assertEqual(official.instruction_role, "developer")
        self.assertEqual(custom.instruction_role, "system")


class AnthropicAdapterCoverageTests(unittest.TestCase):
    def _provider(self, response, **kwargs):
        from csv_trans.providers.anthropic import AnthropicProvider

        return AnthropicProvider(
            model="m", api_key="K", base_url="https://api.anthropic.com",
            http_client=FakeHttpClient(response), **kwargs,
        )

    def test_invalid_config_values_rejected(self) -> None:
        from csv_trans.exceptions import ProviderConfigurationError
        from csv_trans.providers.anthropic import AnthropicProvider

        base = dict(base_url="https://api.anthropic.com")
        bad = [
            dict(model="  ", api_key="K"),
            dict(model="m", api_key="  "),
            dict(model="m", api_key="K", api_version="  "),
            dict(model="m", api_key="K", max_tokens=0),
            dict(model="m", api_key="K", max_tokens=True),
            dict(model="m", api_key="K", timeout=-1),
            dict(model="m", api_key="K", temperature=float("inf")),
        ]
        for overrides in bad:
            with self.assertRaises(ProviderConfigurationError, msg=str(overrides)):
                AnthropicProvider(**{**base, **overrides})

    def test_corrective_retry_returns_translation(self) -> None:
        provider = self._provider(_anthropic_envelope({"r0c0s0": "hola"}))
        out = provider.translate_corrective(
            [TranslationItem("r0c0s0", "hi")], source_language="en", target_language="es"
        )
        self.assertEqual(out[0].text, "hola")

    def test_endpoint_resolution(self) -> None:
        from csv_trans.providers.anthropic import AnthropicProvider

        for base_url, expected in (
            ("https://api.anthropic.com", "https://api.anthropic.com/v1/messages"),
            ("https://api.anthropic.com/v1", "https://api.anthropic.com/v1/messages"),
            ("https://api.anthropic.com/v1/messages", "https://api.anthropic.com/v1/messages"),
        ):
            provider = AnthropicProvider(model="m", api_key="K", base_url=base_url)
            self.assertEqual(provider.endpoint, expected)

    def test_multi_block_content_rejected(self) -> None:
        from csv_trans.exceptions import ProviderResponseError

        envelope = json.dumps(
            {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
        ).encode()
        provider = self._provider(HttpResponse(200, envelope, {"Content-Type": "application/json"}))
        with self.assertRaises(ProviderResponseError):
            provider.translate(
                [TranslationItem("r0c0s0", "hi")], source_language="en", target_language="es"
            )


# --------------------------------------------------------------------------- #
# Phase-4 verification follow-ups
# --------------------------------------------------------------------------- #
class Phase4FollowupRegressionTests(unittest.TestCase):
    def test_empty_encoding_is_auto_not_rejected(self) -> None:
        from csv_trans.models import TranslationConfig

        # An empty string historically meant auto-detect downstream; keep that.
        TranslationConfig(source_language="en", target_language="fr", encoding="")

    def test_whitespace_mapping_key_is_protected(self) -> None:
        from csv_trans.chunking import segment_text

        segments = segment_text("Hello %(user id)s and %(count)d done", 100)
        protected = {seg.text for seg in segments if not seg.translatable}
        self.assertIn("%(user id)s", protected)
        self.assertIn("%(count)d", protected)


if __name__ == "__main__":
    unittest.main()
