"""Reusable, dependency-free test doubles for the csv_trans v2 test bed.

The production provider protocol deliberately remains small.  These fakes accept
both mappings and item objects so the tests care about the public guarantees
(stable IDs and exact text mapping), not an incidental internal container type.
"""

from __future__ import annotations

import csv
import socket
import tempfile
import urllib.request
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from csv_trans.models import RunStatus
from csv_trans.exceptions import (
    ProviderAuthenticationError,
    ProviderContextLimitError,
    ProviderTimeoutError,
)
from csv_trans.providers import TranslationItem


def item_pairs(items):
    """Return ``[(stable_id, text), ...]`` for any reasonable protocol shape."""

    if isinstance(items, Mapping):
        return list(items.items())

    pairs = []
    for item in items:
        if isinstance(item, Mapping):
            item_id = item.get("id", item.get("item_id", item.get("stable_id")))
            text = item.get("text")
        elif isinstance(item, tuple) and len(item) == 2:
            item_id, text = item
        else:
            item_id = getattr(
                item,
                "id",
                getattr(item, "item_id", getattr(item, "stable_id", None)),
            )
            text = getattr(item, "text", None)
        if item_id is None or text is None:
            raise AssertionError(f"Provider received an item without an ID/text: {item!r}")
        pairs.append((item_id, text))
    return pairs


class RecordingProvider:
    """Deterministic provider that records every disclosure and prefixes output."""

    name = "recording"
    is_remote = False
    endpoint = "http://127.0.0.1:11434/v1"

    def __init__(self, prefix="translated:", *, name=None, remote=None, endpoint=None):
        self.prefix = prefix
        self.calls = []
        if name is not None:
            self.name = name
        if remote is not None:
            self.is_remote = remote
        if endpoint is not None:
            self.endpoint = endpoint

    def translate_batch(self, items, source_lang=None, target_lang=None, **kwargs):
        pairs = item_pairs(items)
        self.calls.append(
            {
                "items": pairs,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "options": kwargs,
            }
        )
        return {item_id: f"{self.prefix}{text}" for item_id, text in pairs}

    def translate(self, items, *, source_language, target_language):
        """Implement the v2 ordered-TranslationItem provider protocol."""

        response = self.translate_batch(
            items,
            source_lang=source_language,
            target_lang=target_language,
        )
        return [TranslationItem(id=item_id, text=text) for item_id, text in response.items()]

    @property
    def received_texts(self):
        return [text for call in self.calls for _, text in call["items"]]


class IdentityProvider(RecordingProvider):
    """Provider useful for proving chunk/reassembly losslessness."""

    name = "identity"

    def __init__(self):
        super().__init__(prefix="")


class AlwaysFailProvider(RecordingProvider):
    """Provider that fails every call with a configurable exception."""

    name = "always-fail"

    def __init__(self, error=None, **kwargs):
        super().__init__(**kwargs)
        self.error = error or ProviderTimeoutError(
            "temporary provider outage", provider=self.name
        )

    def translate_batch(self, items, source_lang=None, target_lang=None, **kwargs):
        pairs = item_pairs(items)
        self.calls.append(
            {
                "items": pairs,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "options": kwargs,
            }
        )
        raise self.error


class FailOnceProvider(RecordingProvider):
    """Raise a transient error once, then behave normally."""

    name = "fail-once"

    def __init__(self, prefix="retried:"):
        super().__init__(prefix=prefix)
        self._failed = False

    def translate_batch(self, items, source_lang=None, target_lang=None, **kwargs):
        if not self._failed:
            self._failed = True
            pairs = item_pairs(items)
            self.calls.append(
                {
                    "items": pairs,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "options": kwargs,
                }
            )
            raise ProviderTimeoutError("temporary provider outage", provider=self.name)
        return super().translate_batch(items, source_lang, target_lang, **kwargs)


class AuthenticationFailProvider(AlwaysFailProvider):
    """Permanent authentication failure used to prove retry suppression."""

    name = "authentication-fail"

    def __init__(self):
        super().__init__(
            error=ProviderAuthenticationError("invalid API key", provider=self.name)
        )


class ContextLimitUntilSingleProvider(RecordingProvider):
    """Reject multi-item requests with the normalized context-limit error."""

    name = "context-limit"

    def translate_batch(self, items, source_lang=None, target_lang=None, **kwargs):
        pairs = item_pairs(items)
        self.calls.append(
            {
                "items": pairs,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "options": kwargs,
            }
        )
        if len(pairs) > 1:
            raise ProviderContextLimitError("batch is too large", provider=self.name)
        return {item_id: f"small:{text}" for item_id, text in pairs}


class SplitUntilSingleProvider(RecordingProvider):
    """Return malformed ID sets for batches and succeed for single items."""

    name = "split-until-single"

    def translate_batch(self, items, source_lang=None, target_lang=None, **kwargs):
        pairs = item_pairs(items)
        self.calls.append(
            {
                "items": pairs,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "options": kwargs,
            }
        )
        if len(pairs) > 1:
            return {}
        return {item_id: f"single:{text}" for item_id, text in pairs}


class RejectTextProvider(RecordingProvider):
    """Translate normal values but never produce a result for one exact value."""

    name = "reject-text"

    def __init__(self, rejected, prefix="ok:", **kwargs):
        super().__init__(prefix=prefix, **kwargs)
        self.rejected = rejected

    def translate_batch(self, items, source_lang=None, target_lang=None, **kwargs):
        pairs = item_pairs(items)
        self.calls.append(
            {
                "items": pairs,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "options": kwargs,
            }
        )
        return {
            item_id: f"{self.prefix}{text}"
            for item_id, text in pairs
            if text != self.rejected
        }


class ReverseResponseProvider(RecordingProvider):
    """Return a correctly keyed mapping in reverse insertion order."""

    name = "reverse-response"

    def translate_batch(self, items, source_lang=None, target_lang=None, **kwargs):
        pairs = item_pairs(items)
        self.calls.append(
            {
                "items": pairs,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "options": kwargs,
            }
        )
        return {
            item_id: f"ordered:{text}"
            for item_id, text in reversed(pairs)
        }


class CorrectableMalformedProvider(RecordingProvider):
    """Return an invalid ID set once, then a valid response."""

    name = "correctable-malformed"

    def __init__(self):
        super().__init__(prefix="corrected:")
        self._malformed = True

    def translate_batch(self, items, source_lang=None, target_lang=None, **kwargs):
        pairs = item_pairs(items)
        self.calls.append(
            {
                "items": pairs,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "options": kwargs,
            }
        )
        if self._malformed:
            self._malformed = False
            return {"unexpected-id": "wrong"}
        return {item_id: f"corrected:{text}" for item_id, text in pairs}


class CliResult(SimpleNamespace):
    """Small result object accepted by CLI tests without coupling to constructors."""

    def __init__(self, status="success"):
        status = RunStatus(status)
        super().__init__(
            status=status,
            input_path="input.csv",
            output_path="output.csv",
            total_cells=1,
            selected_cells=1,
            translated_cells=1 if status is RunStatus.SUCCESS else 0,
            cached_cells=0,
            skipped_cells=0,
            failed_cells=1 if status is not RunStatus.SUCCESS else 0,
            selected_columns=["text"],
            failures=[],
            retries=0,
            fallbacks=0,
        )

    def to_dict(self):
        payload = dict(vars(self))
        payload["status"] = self.status.value
        return payload


class FakeHttpClient:
    """Queue-backed injectable HTTP client; it can never touch the network."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def request(self, method, url, *, headers=None, body=None, timeout=None):
        request = {
            "method": method,
            "url": url,
            "headers": dict(headers or {}),
            "body": body,
            "timeout": timeout,
        }
        self.requests.append(request)
        if not self.outcomes:
            raise AssertionError(f"unexpected HTTP request: {method} {url}")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return outcome(request)
        return outcome


def status_value(result):
    """Normalize a string/enum result status for assertions."""

    status = result.status
    return getattr(status, "value", status)


def result_payload(result):
    """Return the public JSON-compatible representation of a result."""

    payload = result.to_dict()
    if not isinstance(payload, dict):
        raise AssertionError("TranslationResult.to_dict() must return a dictionary")
    return payload


def selected_column_names(result):
    """Return selected header names from the structured selection report."""

    names = []
    for item in result.selected_columns:
        if isinstance(item, str):
            names.append(item)
        elif getattr(item, "selected", True):
            names.append(item.name)
    return names


@contextmanager
def no_network():
    """Fail a test immediately if code tries to open any real network connection."""

    message = "offline test attempted a real network connection"
    with ExitStack() as stack:
        stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError(message)))
        stack.enter_context(patch.object(urllib.request, "urlopen", side_effect=AssertionError(message)))
        yield


class CsvTestCase(TestCase):
    """Temporary filesystem and CSV helpers shared by integration-style unit tests."""

    def setUp(self):
        super().setUp()
        message = "offline test attempted a real network connection"
        self._network_patches = ExitStack()
        self._network_patches.enter_context(
            patch.object(socket, "create_connection", side_effect=AssertionError(message))
        )
        self._network_patches.enter_context(
            patch.object(urllib.request, "urlopen", side_effect=AssertionError(message))
        )
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self._temporary_directory.name)

    def tearDown(self):
        self._temporary_directory.cleanup()
        self._network_patches.close()
        super().tearDown()

    def path(self, name):
        return self.directory / name

    def write_text(self, name, text, encoding="utf-8"):
        path = self.path(name)
        path.write_text(text, encoding=encoding, newline="")
        return path

    def write_rows(self, name, rows, *, delimiter=",", encoding="utf-8"):
        path = self.path(name)
        with path.open("w", encoding=encoding, newline="") as stream:
            csv.writer(stream, delimiter=delimiter).writerows(rows)
        return path

    def read_rows(self, path, *, delimiter=",", encoding="utf-8"):
        with Path(path).open("r", encoding=encoding, newline="") as stream:
            return list(csv.reader(stream, delimiter=delimiter))
