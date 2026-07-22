"""Regression tests for two LOW-severity fixes.

1. ``translate()`` rejects a v2 name given together with its 1.x alias, with a
   targeted ``TypeError`` naming both — instead of the stray alias reaching
   ``TranslationConfig`` and producing a confusing internal error.
2. ``detect_encoding`` still fails closed on an embedded NUL byte, but the
   message no longer unconditionally asserts the input is UTF-16/UTF-32.
"""

from __future__ import annotations

import unittest

from csv_trans import translate as public_translate
from csv_trans.csvio import CsvInputError, detect_encoding
from csv_trans.translate import main

from tests._support import CsvTestCase, RecordingProvider, status_value


class AliasCollisionTests(CsvTestCase):
    def test_v2_and_1x_alias_together_raise_a_targeted_type_error(self):
        for v2_name, alias, call in (
            (
                "target_language",
                "target_lang",
                lambda: public_translate(
                    "f.csv", "en", target_language="es", target_lang="es"
                ),
            ),
            (
                "source_language",
                "source_lang",
                lambda: public_translate(
                    "f.csv", source_language="en", target_language="es",
                    source_lang="en",
                ),
            ),
            (
                "input_path",
                "file",
                lambda: public_translate(
                    "f.csv", "en", "es", file="other.csv"
                ),
            ),
        ):
            with self.subTest(alias=alias):
                with self.assertRaises(TypeError) as raised:
                    call()
                message = str(raised.exception)
                self.assertIn(v2_name, message)
                self.assertIn(alias, message)

    # --- all normal v1 call forms must still work --------------------------

    def test_v1_positional_separator_still_works(self):
        source = self.write_rows("pos.csv", [["text"], ["hello"]], delimiter=";")
        output = self.path("pos.out.csv")

        result = public_translate(
            source,
            "en",
            "fr",
            ";",
            output_path=output,
            columns=[0],
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(self.read_rows(output, delimiter=";"), [["text"], ["fr:hello"]])
        self.assertEqual(status_value(result), "success")

    def test_v1_keyword_aliases_still_work(self):
        source = self.write_rows("kw.csv", [["text"], ["hello"]], delimiter=";")
        output = self.path("kw.out.csv")

        result = public_translate(
            file=source,
            source_lang="en",
            target_lang="fr",
            sep=";",
            output_path=output,
            columns=[0],
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(self.read_rows(output, delimiter=";"), [["text"], ["fr:hello"]])
        self.assertEqual(status_value(result), "success")

    def test_v1_main_alias_still_works(self):
        source = self.write_rows("main.csv", [["text"], ["hello"]], delimiter=";")
        output = self.path("main.out.csv")

        result = main(
            source,
            "en",
            "fr",
            ";",
            output_path=output,
            columns=[0],
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(self.read_rows(output, delimiter=";"), [["text"], ["fr:hello"]])
        self.assertEqual(status_value(result), "success")


class NulByteMessageTests(CsvTestCase):
    def test_embedded_nul_fails_closed_without_asserting_utf16(self):
        # Valid UTF-8 text that also carries an embedded NUL (U+0000).
        path = self.path("nul.csv")
        path.write_bytes(b"text\nhel\x00lo\n")

        with self.assertRaises(CsvInputError) as raised:
            detect_encoding(path)

        message = str(raised.exception)
        # Rejection is preserved and points at the NUL...
        self.assertIn("NUL", message)
        # ...but the message must not unconditionally assert the encoding.
        self.assertNotIn("is not valid UTF-8 text; it", message)
        lowered = message.lower()
        self.assertNotIn("looks like a bom-less utf-16/utf-32 file", lowered)


if __name__ == "__main__":
    unittest.main()
