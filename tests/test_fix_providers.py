"""Regression tests for the provider transport error-classification fix.

A custom/injected ``HttpClient`` whose ``request()`` has a DETERMINISTIC,
non-transport bug (e.g. it raises ``ValueError``/``UnicodeEncodeError`` on every
call) used to be flattened into a retryable ``ProviderConnectionError`` by
``send_request``. Because ``ProviderConnectionError`` is retryable, the engine
retried the doomed call ``max_retries`` times (sleeping) and then reported a
misleading "could not connect". The fix classifies such a non-transport,
non-``ProviderError`` client exception as a NON-retryable scrubbed
``ProviderError`` so it is surfaced once and not retried, while GENUINE transport
failures (``OSError``/``URLError``/timeouts) keep their existing retryable
mapping. The privacy/credential scrub (no original value or traceback survives)
is preserved.
"""

from __future__ import annotations

import traceback
import unittest

from csv_trans import translate
from csv_trans.core import _error_category, _is_retryable
from csv_trans.exceptions import ProviderError
from csv_trans.providers import OpenAICompatibleProvider
from csv_trans.providers._common import send_request

from tests._support import CsvTestCase

_SECRET_TOKEN = "sk-live-SUPERSECRET-abc123"


class _DeterministicBugClient:
    """A custom HttpClient whose request() always raises a non-transport bug."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self.calls = 0
        # The message deliberately embeds a secret to prove it is never leaked
        # through the normalized error's message, traceback, or frame locals.
        self._exc = exc or ValueError(f"boom with {_SECRET_TOKEN}")

    def request(self, method, url, *, headers=None, body=None, timeout=None):
        self.calls += 1
        raise self._exc


class _TransportFailureClient:
    """A custom HttpClient that raises a GENUINE transport failure every call."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self.calls = 0
        self._exc = exc or OSError("connection refused")

    def request(self, method, url, *, headers=None, body=None, timeout=None):
        self.calls += 1
        raise self._exc


def _openai_provider(client) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        "gpt-test",
        base_url="https://api.example.com/v1",
        api_key=_SECRET_TOKEN,
        http_client=client,
    )


class DeterministicClientBugClassificationTests(unittest.TestCase):
    """send_request must classify a deterministic client bug as non-retryable."""

    def test_non_transport_client_bug_is_non_retryable_and_scrubbed(self):
        client = _DeterministicBugClient()

        with self.assertRaises(ProviderError) as caught:
            send_request(
                client,
                "POST",
                "https://api.example.com/v1/chat/completions",
                provider="openai",
                headers={"Authorization": f"Bearer {_SECRET_TOKEN}"},
                body=b'{"payload": "source text"}',
                timeout=5,
            )
        error = caught.exception

        # Invoked exactly once by send_request itself (no internal retry).
        self.assertEqual(client.calls, 1)

        # Classified as NON-retryable per the engine's own predicates, and NOT
        # as a retryable connection error.
        self.assertFalse(_is_retryable(error))
        self.assertNotEqual(_error_category(error), "connection")

        # No original value / cause / context survives (privacy scrub intact).
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)

        # The secret must not leak via the message, the traceback text, or any
        # frame local retained on the propagating traceback.
        self.assertNotIn(_SECRET_TOKEN, str(error))
        tb_text = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        self.assertNotIn(_SECRET_TOKEN, tb_text)
        tb = error.__traceback__
        while tb is not None:
            for value in tb.tb_frame.f_locals.values():
                self.assertNotIn(_SECRET_TOKEN, repr(value))
            tb = tb.tb_next

    def test_unicode_encode_error_client_bug_is_non_retryable(self):
        # A UnicodeEncodeError is the canonical deterministic client bug the
        # report calls out; it must be treated identically to any other.
        try:
            "\udcff".encode("ascii")
        except UnicodeEncodeError as exc:
            unicode_bug = exc
        client = _DeterministicBugClient(unicode_bug)

        with self.assertRaises(ProviderError) as caught:
            send_request(
                client,
                "POST",
                "https://api.example.com/v1/chat/completions",
                provider="openai",
                headers={"Authorization": f"Bearer {_SECRET_TOKEN}"},
                body=b"{}",
                timeout=5,
            )
        self.assertEqual(client.calls, 1)
        self.assertFalse(_is_retryable(caught.exception))


class EngineRetryBehaviorTests(CsvTestCase):
    """End-to-end: the engine must NOT retry a deterministic client bug, but
    MUST still retry a genuine transport failure exactly as before."""

    def test_deterministic_client_bug_is_not_retried_by_engine(self):
        source = self.write_rows("bug.csv", [["text"], ["hello"]])
        output = self.path("bug.out.csv")
        client = _DeterministicBugClient()
        provider = _openai_provider(client)

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            max_retries=3,
            malformed_retries=2,
            backoff_base=0,
            jitter=0,
        )

        # Invoked exactly ONCE: not retried through either the transient or the
        # malformed-corrective path.
        self.assertEqual(client.calls, 1)
        self.assertEqual(result.retries, 0)
        # Original cell preserved; failure classified as non-connection.
        self.assertEqual(self.read_rows(output), [["text"], ["hello"]])
        self.assertNotEqual(result.failures[0].category, "connection")
        # No secret leaks into the surfaced failure report.
        self.assertNotIn(_SECRET_TOKEN, result.failures[0].message)

    def test_genuine_transport_failure_is_still_retried(self):
        source = self.write_rows("transport.csv", [["text"], ["hello"]])
        output = self.path("transport.out.csv")
        client = _TransportFailureClient()
        provider = _openai_provider(client)

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            max_retries=3,
            malformed_retries=2,
            backoff_base=0,
            jitter=0,
        )

        # Retryable transport failure: 1 initial + max_retries attempts.
        self.assertEqual(client.calls, 4)
        self.assertEqual(result.retries, 3)
        self.assertEqual(result.failures[0].category, "connection")


if __name__ == "__main__":
    unittest.main()
