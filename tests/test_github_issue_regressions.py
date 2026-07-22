"""End-to-end acceptance regressions for historical GitHub issues #14 and #15."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from csv_trans import translate

from tests._support import CsvTestCase, status_value


class _UnserializableInvalidPayload(Exception):
    """Emulate the third-party exception whose pickle round trip broke issue #15."""

    def __init__(self, value: str) -> None:
        self.value = value
        self.serialization_attempted = False
        # Deliberately retain no positional arguments even though construction
        # requires one, matching the historical exception's broken pickle shape.
        Exception.__init__(self)

    def __reduce__(self):
        self.serialization_attempted = True
        raise AssertionError("provider exceptions must never cross a process boundary")


class _InvalidPayloadProvider:
    name = "invalid-payload"
    is_remote = False
    base_url = "http://127.0.0.1:11434/v1"

    def __init__(self) -> None:
        self.calls = 0
        self.error: _UnserializableInvalidPayload | None = None

    def translate(self, items, *, source_language, target_language):
        self.calls += 1
        self.error = _UnserializableInvalidPayload(items[0].text)
        raise self.error


class HistoricalGitHubIssueAcceptanceTests(CsvTestCase):
    def test_module_cli_echo_subprocess_completes_without_spawn_recursion(self):
        """Issue #14: the CLI must complete without starting recursive workers."""

        source = self.write_rows(
            "issue-14.csv",
            [["id", "text"], ["101", "hello"]],
        )
        output = self.path("issue-14.out.csv")
        repository = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            part
            for part in (str(repository), environment.get("PYTHONPATH", ""))
            if part
        )

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "csv_trans",
                "-f",
                str(source),
                "-sl",
                "en",
                "-tl",
                "fr",
                "--provider",
                "echo",
                "--columns",
                "text",
                "--output",
                str(output),
                "--privacy",
                "local-only",
                "--quiet",
            ],
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}",
        )
        self.assertEqual(
            self.read_rows(output),
            [["id", "text"], ["101", "hello"]],
        )

    def test_invalid_payload_exception_stays_in_process_and_returns_partial(self):
        """Issue #15: a broken third-party exception is normalized, never pickled."""

        source = self.write_rows(
            "issue-15.csv",
            [["id", "text"], ["101", "invalid payload"]],
        )
        output = self.path("issue-15.out.csv")
        provider = _InvalidPayloadProvider()

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            provider=provider,
            columns=("text",),
            max_retries=0,
            malformed_retries=0,
        )

        self.assertEqual(status_value(result), "partial")
        self.assertEqual(result.failed_cells, 1)
        self.assertEqual(provider.calls, 1)
        self.assertIsNotNone(provider.error)
        self.assertFalse(provider.error.serialization_attempted)
        self.assertEqual(
            self.read_rows(output),
            [["id", "text"], ["101", "invalid payload"]],
        )
        self.assertEqual(result.failures[0].category, "unknown")
        self.assertTrue(result.failures[0].original_preserved)
        self.assertNotIn("invalid payload", result.failures[0].message)


if __name__ == "__main__":
    import unittest

    unittest.main()
