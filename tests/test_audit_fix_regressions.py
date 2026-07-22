"""Regression tests locking in the fixes from the 2026 adversarial audit.

Each test names the module and severity of the issue it guards. All are offline
and deterministic; no network or credential is used.
"""

from __future__ import annotations

import tempfile
import time
import traceback
import unittest
from pathlib import Path


class SelectionSecretRegressionTests(unittest.TestCase):
    """selection.py H1/M1: secret columns and non-finite numeric words."""

    def test_is_numeric_rejects_non_finite_and_underscore_forms(self) -> None:
        from csv_trans.selection import is_numeric

        for value in ("NaN", "-NaN", "Infinity", "inf", "-inf", "1_000"):
            self.assertFalse(is_numeric(value), value)
        for value in ("42", "-3.5", "1,000", "9.99", "50%"):
            self.assertTrue(is_numeric(value), value)

    def test_long_base64_token_is_machine_value_but_prose_is_not(self) -> None:
        from csv_trans.selection import is_machine_value

        # AWS-style secret key and standard base64 payloads must be preserved.
        self.assertTrue(
            is_machine_value("wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")
        )
        self.assertTrue(is_machine_value("U2VjcmV0VmFsdWVIZXJlPT0+abc="))
        # Natural-language text (including long compounds) must NOT be dropped.
        self.assertFalse(is_machine_value("Rindfleischetikettierungsueberwachung"))
        self.assertFalse(is_machine_value("the quick brown fox jumps over"))

    def test_secret_like_headers_are_not_auto_selected(self) -> None:
        from csv_trans.selection import resolve_columns

        headers = ["password", "token", "api_key", "comment"]
        sample = [["hunter2xyz", "abcdefabcdef", "keykeykeykey", "please translate me"]]
        selected, _ = resolve_columns(headers, sample, None)
        self.assertNotIn(0, selected)
        self.assertNotIn(1, selected)
        self.assertNotIn(2, selected)
        self.assertIn(3, selected)


class ChunkingRedosRegressionTests(unittest.TestCase):
    """chunking.py M1: quadratic ReDoS on ``%(`` runs."""

    def test_percent_paren_run_stays_linear(self) -> None:
        from csv_trans.chunking import segment_text

        # An absolute bound, deliberately not a doubling-ratio check: on shared
        # CI runners the base measurement is ~15ms, where scheduler noise alone
        # can push a linear implementation past any ratio that would still
        # catch a quadratic one. The absolute cap discriminates cleanly - the
        # bounded pattern finishes 80k tokens in ~0.05s, while the old
        # quadratic rescan (~1e10 char operations) needs minutes.
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            segment_text("%(" * 80_000, 4_000)
            best = min(best, time.perf_counter() - start)
        self.assertLess(best, 2.0, f"80k-token run took {best:.3f}s")

    def test_placeholder_round_trip_is_lossless(self) -> None:
        from csv_trans.chunking import reconstruct_segments, segment_text

        text = "See https://x.io/a for %(count)s items {{tag}} <b>ok</b>"
        segments = segment_text(text, 8)
        identity = {
            index: seg.text
            for index, seg in enumerate(segments)
            if seg.translatable
        }
        self.assertEqual(reconstruct_segments(segments, identity), text)


class CommonScrubRegressionTests(unittest.TestCase):
    """_common.py H1: non-ValueError decode and unexpected client errors."""

    def _items(self) -> list:
        from csv_trans.providers.base import TranslationItem

        return [TranslationItem("r0c0s0", "hello")]

    def test_deeply_nested_json_is_normalized_and_scrubbed(self) -> None:
        from csv_trans.exceptions import ProviderError, ProviderResponseError
        from csv_trans.providers._common import decode_strict_translation_text

        marker = "SECRET_CELL_MARKER"
        payload = "[" * 20_000 + marker + "]" * 20_000
        with self.assertRaises(ProviderResponseError) as ctx:
            decode_strict_translation_text(payload, self._items(), provider="p")
        error = ctx.exception
        self.assertIsInstance(error, ProviderError)
        self.assertIsNone(error.__cause__)
        rendered = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        self.assertNotIn(marker, rendered)

    def test_unexpected_client_error_becomes_scrubbed_provider_error(self) -> None:
        from csv_trans.exceptions import ProviderError
        from csv_trans.providers._common import send_request

        secret = "Bearer super-secret-token-value"

        class ExplodingClient:
            def request(self, *args, **kwargs):
                headers = kwargs.get("headers")
                assert headers  # secret lives in this frame's locals
                raise RuntimeError("unexpected client failure")

        with self.assertRaises(ProviderError) as ctx:
            send_request(
                ExplodingClient(),
                "POST",
                "https://api.example/v1/chat/completions",
                provider="p",
                headers={"Authorization": secret},
                body=b"{}",
                timeout=30.0,
            )
        error = ctx.exception
        self.assertIsNone(error.__cause__)
        rendered = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        self.assertNotIn(secret, rendered)


class CliHeaderBlocklistRegressionTests(unittest.TestCase):
    """cli.py M1: sensitive-header blocklist completeness."""

    def test_additional_secret_headers_are_rejected(self) -> None:
        from csv_trans.cli import _parse_headers

        for name in (
            "apikey",
            "api_key",
            "X-Functions-Key",
            "X-Amz-Security-Token",
            "X-Session-Token",
            "X-Custom-Secret",
        ):
            with self.assertRaises(ValueError, msg=name):
                _parse_headers([f"{name}=value"])

    def test_ordinary_header_is_accepted(self) -> None:
        from csv_trans.cli import _parse_headers

        self.assertEqual(_parse_headers(["X-Trace-Id=abc"]), {"X-Trace-Id": "abc"})


class CsvLineEndingRegressionTests(unittest.TestCase):
    """csvio.py M1: line-ending inference from the first unquoted record."""

    def test_quoted_crlf_does_not_flip_lf_file(self) -> None:
        from csv_trans.csvio import _first_record_terminator

        self.assertEqual(_first_record_terminator('id,text\n1,"a\r\nb"\n'), "\n")

    def test_genuine_crlf_file_detected(self) -> None:
        from csv_trans.csvio import _first_record_terminator

        self.assertEqual(_first_record_terminator("id,text\r\n1,x\r\n"), "\r\n")


class GoogleParserRegressionTests(unittest.TestCase):
    """google_free.py M1/M2: HTML over-capture, truncation, script leakage."""

    def _parse(self, html: str) -> str | None:
        from csv_trans.providers.google_free import _MobileTranslationParser

        parser = _MobileTranslationParser()
        parser.feed(html)
        parser.close()
        return parser.translation

    def test_unclosed_inner_tag_does_not_capture_trailing_page(self) -> None:
        self.assertEqual(
            self._parse(
                '<div class="result-container"><p>text</div>'
                "<footer>JUNK</footer>"
            ),
            "text",
        )

    def test_stray_end_tag_does_not_truncate(self) -> None:
        self.assertEqual(
            self._parse('<div class="result-container">a</span>b</div>'), "ab"
        )

    def test_script_body_is_suppressed(self) -> None:
        self.assertEqual(
            self._parse(
                '<div class="result-container">hi<script>evil()</script>x</div>'
            ),
            "hix",
        )


class ConfigColumnsValidationRegressionTests(unittest.TestCase):
    """models.py M1: columns validated eagerly at construction."""

    def test_bad_columns_raise_value_error_at_construction(self) -> None:
        from csv_trans.models import TranslationConfig

        for columns in ([1.5], [None], [True], ["  "], [b"x"]):
            with self.assertRaises(ValueError, msg=repr(columns)):
                TranslationConfig(
                    source_language="en", target_language="fr", columns=columns
                )

    def test_valid_columns_are_accepted(self) -> None:
        from csv_trans.models import TranslationConfig

        config = TranslationConfig(
            source_language="en", target_language="fr", columns=["name", 2]
        )
        self.assertEqual(config.columns, ("name", 2))


class EchoExemptionRegressionTests(unittest.TestCase):
    """echo.py / core.py L1: exemption must not survive method shadowing."""

    def test_shadowed_translate_loses_local_only_exemption(self) -> None:
        from csv_trans.core import PrivacyViolation, translate_csv
        from csv_trans.models import PrivacyMode, TranslationConfig
        from csv_trans.providers import EchoProvider

        provider = EchoProvider()
        # Shadow the offline method with arbitrary (potentially networked) code.
        provider.translate = lambda *args, **kwargs: []  # type: ignore[method-assign]

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "in.csv"
            source.write_text("id,text\n1,hello world\n", encoding="utf-8")
            config = TranslationConfig(
                source_language="en",
                target_language="fr",
                provider=provider,
                privacy=PrivacyMode.LOCAL_ONLY,
                columns=["text"],
            )
            with self.assertRaises(PrivacyViolation):
                translate_csv(
                    str(source),
                    config,
                    output_path=str(Path(directory) / "out.csv"),
                )

    def test_plain_echo_keeps_local_only_exemption(self) -> None:
        from csv_trans.core import translate_csv
        from csv_trans.models import PrivacyMode, RunStatus, TranslationConfig
        from csv_trans.providers import EchoProvider

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "in.csv"
            source.write_text("id,text\n1,hello world\n", encoding="utf-8")
            config = TranslationConfig(
                source_language="en",
                target_language="fr",
                provider=EchoProvider(),
                privacy=PrivacyMode.LOCAL_ONLY,
                columns=["text"],
            )
            result = translate_csv(
                str(source),
                config,
                output_path=str(Path(directory) / "out.csv"),
            )
            self.assertEqual(result.status, RunStatus.SUCCESS)


class HttpTimeoutFloorRegressionTests(unittest.TestCase):
    """base.py M1: timeout=None must not disable the socket timeout."""

    def test_none_timeout_uses_default_floor(self) -> None:
        from csv_trans.providers.base import (
            HttpTransportConnectionError,
            UrllibHttpClient,
        )

        captured: dict[str, object] = {}

        class FakeOpener:
            def open(self, request, timeout=None):  # noqa: A002
                captured["timeout"] = timeout
                raise OSError("stop before any real network use")

        client = UrllibHttpClient()
        client._opener = FakeOpener()  # type: ignore[assignment]
        with self.assertRaises(HttpTransportConnectionError):
            client.request("GET", "https://example.invalid/", timeout=None)
        self.assertEqual(captured["timeout"], UrllibHttpClient.DEFAULT_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
