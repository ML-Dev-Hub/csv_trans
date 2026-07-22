"""CSV shape, ordering, dialect, and encoding invariants for the v2 core."""

from __future__ import annotations

import unittest

from csv_trans.core import translate_csv
from csv_trans.csvio import CsvInputError, inspect_csv

from tests._support import CsvTestCase, RecordingProvider, no_network


class CsvShapeAndDialectTests(CsvTestCase):
    def test_one_column_csv_preserves_shape_and_header(self):
        source = self.write_rows(
            "one.csv",
            [["text"], ["A complete sentence."], ["Another complete sentence."]],
        )
        output = self.path("one.fr.csv")
        provider = RecordingProvider(prefix="fr:")

        with no_network():
            result = translate_csv(
                source,
                "en",
                "fr",
                output_path=output,
                columns=["text"],
                provider=provider,
            )

        self.assertEqual(
            self.read_rows(output),
            [["text"], ["fr:A complete sentence."], ["fr:Another complete sentence."]],
        )
        self.assertEqual(result.total_cells, 2)
        self.assertEqual(result.translated_cells, 2)

    def test_multicolumn_csv_preserves_column_and_row_order(self):
        source = self.write_rows(
            "many.csv",
            [
                ["id", "description", "note"],
                ["2", "second row", "keep-2"],
                ["1", "first row", "keep-1"],
            ],
        )
        output = self.path("many.fr.csv")

        translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=["description"],
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(
            self.read_rows(output),
            [
                ["id", "description", "note"],
                ["2", "fr:second row", "keep-2"],
                ["1", "fr:first row", "keep-1"],
            ],
        )

    def test_duplicate_headers_remain_duplicate_and_are_addressable_by_index(self):
        source = self.write_rows(
            "duplicates.csv",
            [["value", "value"], ["left", "right"], ["up", "down"]],
        )
        output = self.path("duplicates.fr.csv")

        translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0, 1],
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(
            self.read_rows(output),
            [["value", "value"], ["fr:left", "fr:right"], ["fr:up", "fr:down"]],
        )

    def test_ragged_rows_keep_their_original_field_counts(self):
        source = self.write_text(
            "ragged.csv",
            "first,second,third\n1,hello\n2,world,extra,tail\n3\n",
        )
        output = self.path("ragged.fr.csv")

        translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[1],
            provider=RecordingProvider(prefix="fr:"),
        )

        rows = self.read_rows(output)
        self.assertEqual([len(row) for row in rows], [3, 2, 4, 1])
        self.assertEqual(rows[1], ["1", "fr:hello"])
        self.assertEqual(rows[2], ["2", "fr:world", "extra", "tail"])
        self.assertEqual(rows[3], ["3"])

    def test_quoted_multiline_fields_and_embedded_delimiters_survive(self):
        source = self.write_rows(
            "quoted.csv",
            [["id", "text", "note"], ["1", "hello\nworld", "x;y"]],
            delimiter=";",
        )
        output = self.path("quoted.fr.csv")

        translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=["text"],
            delimiter=";",
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(
            self.read_rows(output, delimiter=";"),
            [["id", "text", "note"], ["1", "fr:hello\nworld", "x;y"]],
        )

    def test_supported_explicit_delimiters_are_used_for_input_and_output(self):
        for delimiter, label in [(";", "semicolon"), ("\t", "tab"), ("|", "pipe")]:
            with self.subTest(delimiter=label):
                source = self.write_rows(
                    f"{label}.csv",
                    [["id", "text"], ["1", f"left{delimiter}right"]],
                    delimiter=delimiter,
                )
                output = self.path(f"{label}.out.csv")
                translate_csv(
                    source,
                    "en",
                    "fr",
                    output_path=output,
                    columns=["text"],
                    delimiter=delimiter,
                    provider=RecordingProvider(prefix="fr:"),
                )
                self.assertEqual(
                    self.read_rows(output, delimiter=delimiter),
                    [["id", "text"], ["1", f"fr:left{delimiter}right"]],
                )


class CsvEncodingTests(CsvTestCase):
    def test_utf8_bom_is_detected_and_content_is_transcoded_to_default_utf8(self):
        source = self.write_rows(
            "bom.csv",
            [["text"], ["snowman ☃"]],
            encoding="utf-8-sig",
        )
        output = self.path("bom.fr.csv")

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(self.read_rows(output, encoding="utf-8"), [["text"], ["fr:snowman ☃"]])
        self.assertEqual(result.input_encoding.lower().replace("_", "-"), "utf-8-sig")
        self.assertEqual(result.output_encoding.lower().replace("_", "-"), "utf-8")

    def test_utf16_bom_is_detected_and_content_is_transcoded_to_default_utf8(self):
        source = self.write_rows(
            "utf16.csv",
            [["text"], ["hello 世界"]],
            encoding="utf-16",
        )
        output = self.path("utf16.fr.csv")

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(self.read_rows(output, encoding="utf-8"), [["text"], ["fr:hello 世界"]])
        self.assertEqual(result.input_encoding.lower().replace("_", "-"), "utf-16")
        self.assertEqual(result.output_encoding.lower().replace("_", "-"), "utf-8")

    def test_explicit_legacy_encoding_round_trips_without_guessing(self):
        source = self.write_rows(
            "legacy.csv",
            [["text"], ["café déjà vu"]],
            encoding="cp1252",
        )
        output = self.path("legacy.fr.csv")

        result = translate_csv(
            source,
            "fr",
            "en",
            output_path=output,
            columns=[0],
            encoding="cp1252",
            output_encoding="cp1252",
            provider=RecordingProvider(prefix="en:"),
        )

        self.assertIn(b"\xe9", output.read_bytes())
        self.assertEqual(self.read_rows(output, encoding="cp1252"), [["text"], ["en:café déjà vu"]])
        self.assertIn(result.input_encoding.lower(), ("cp1252", "windows-1252"))
        self.assertIn(result.output_encoding.lower(), ("cp1252", "windows-1252"))


class CsvValidationTests(CsvTestCase):
    def test_field_larger_than_python_csv_default_is_streamed_and_chunked(self):
        large_value = "a" * 200_000
        source = self.write_rows("large-field.csv", [["text"], [large_value]])
        output = self.path("large-field.out.csv")

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            max_chars=50_000,
            provider=RecordingProvider(prefix=""),
        )

        self.assertEqual(output.read_text(encoding="utf-8").splitlines(), ["text", large_value])
        self.assertEqual(result.failed_cells, 0)

    def test_header_only_file_without_line_ending_uses_portable_newline(self):
        source = self.write_text("header-only.csv", "text")
        output = self.path("header-only.out.csv")

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(output.read_bytes(), b"text\n")
        self.assertEqual(result.row_count, 0)

    def test_newline_and_nul_delimiters_are_rejected(self):
        source = self.write_rows("bad-delimiter.csv", [["text"], ["hello"]])
        for delimiter in ("\n", "\r", "\0"):
            with self.subTest(delimiter=repr(delimiter)), self.assertRaises(ValueError):
                translate_csv(
                    source,
                    "en",
                    "fr",
                    delimiter=delimiter,
                    provider=RecordingProvider(),
                )

    def test_auto_dialect_does_not_guess_when_first_record_exceeds_sample(self):
        source = self.write_text(
            "wide-header.csv",
            ("x" * 70_000) + ";text\nvalue;hello\n",
        )

        with self.assertRaisesRegex(CsvInputError, "explicit delimiter"):
            inspect_csv(source)

        inspection = inspect_csv(source, delimiter=";")
        self.assertEqual(inspection.format.delimiter, ";")

    def test_row_shape_limit_is_rejected_before_provider_disclosure(self):
        source = self.write_rows("too-wide.csv", [["a", "b"], ["one", "two"]])
        output = self.path("too-wide.out.csv")
        provider = RecordingProvider()

        with self.assertRaisesRegex(CsvInputError, "max_columns"):
            translate_csv(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
                max_columns=1,
            )

        self.assertEqual(provider.calls, [])
        self.assertFalse(output.exists())

    def test_unencodable_original_aborts_without_publishing_or_calling_provider(self):
        source = self.write_rows("original-encoding.csv", [["text"], ["안녕하세요"]])
        output = self.path("original-encoding.out.csv")
        provider = RecordingProvider()

        with self.assertRaisesRegex(CsvInputError, "output_encoding"):
            translate_csv(
                source,
                "ko",
                "en",
                output_path=output,
                columns=[0],
                provider=provider,
                output_encoding="ascii",
            )

        self.assertEqual(provider.calls, [])
        self.assertFalse(output.exists())

    def test_selection_sample_has_a_character_budget(self):
        source = self.write_rows(
            "sample-budget.csv",
            [["text"], ["first sentence"], ["second sentence"]],
        )
        output = self.path("sample-budget.out.csv")

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=RecordingProvider(prefix=""),
            max_sample_chars=1,
        )

        self.assertIn(
            "column-selection sampling stopped at max_sample_chars", result.warnings
        )
        self.assertEqual(result.row_count, 2)


if __name__ == "__main__":
    unittest.main()
