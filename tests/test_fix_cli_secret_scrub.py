"""Regression: no credential value may reach stderr, for ANY flag spelling.

Covers the residual found in re-audit — the secret-flag trap was a denylist, so
untrapped spellings (notably the underscore ``--api_key`` that mirrors this
tool's own ``--file_path`` convention) leaked the value through argparse's
"unrecognized arguments: <flag> <VALUE>" echo. The parser now scrubs values
from every unrecognized-argument error.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from csv_trans import cli

SECRET = "sk-LIVE-DO-NOT-ECHO-42x"
_BASE = ["-f", "x.csv", "-sl", "en", "-tl", "fr"]


class SecretFlagScrubTests(unittest.TestCase):
    def _reject(self, argv):
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(argv)
        return ctx.exception.code, err.getvalue()

    def test_untrapped_credential_spellings_never_echo_the_value(self):
        forms = [
            ["--api_key", SECRET],          # underscore — matches --file_path convention
            ["--apiKey", SECRET],           # camelCase
            ["--access-token", SECRET],
            ["--auth-token", SECRET],
            ["--session-token", SECRET],
            ["--pass", SECRET],
            ["--pwd", SECRET],
            ["--credential", SECRET],
            [f"--api_key={SECRET}"],         # equals form (single token)
            [f"--bearer-token={SECRET}"],
            ["--totally-unknown-flag", SECRET],  # any unforeseen spelling
        ]
        for form in forms:
            with self.subTest(form=form[0]):
                code, err = self._reject(_BASE + form)
                self.assertEqual(code, 2)
                self.assertNotIn(SECRET, err)

    def test_registered_trap_flags_still_reject_without_value(self):
        for form in (["--api-key", SECRET], ["--token", SECRET], [f"--api-key={SECRET}"], ["-key", SECRET]):
            with self.subTest(form=form[0]):
                code, err = self._reject(_BASE + form)
                self.assertEqual(code, 2)
                self.assertNotIn(SECRET, err)

    def test_a_bare_secret_positional_is_also_scrubbed(self):
        # A value that does not start with '-' must not be echoed either.
        code, err = self._reject(_BASE + [SECRET])
        self.assertEqual(code, 2)
        self.assertNotIn(SECRET, err)

    def test_unrecognized_flag_name_is_still_shown_for_usability(self):
        # The flag NAME (no value) is still reported so the user can fix it.
        _, err = self._reject(_BASE + ["--api_key", SECRET])
        self.assertIn("--api_key", err)


if __name__ == "__main__":
    unittest.main()
