"""Column selection, header policy, and lossless chunk/reassembly tests."""

from __future__ import annotations

import unittest

from csv_trans import translate
from csv_trans.chunking import split_text_lossless

from tests._support import (
    CsvTestCase,
    IdentityProvider,
    RecordingProvider,
    selected_column_names,
)


class AutomaticSelectionTests(CsvTestCase):
    def test_auto_selection_skips_empty_numeric_and_identifier_like_columns(self):
        source = self.write_rows(
            "selection.csv",
            [
                ["row_id", "sku", "price", "empty", "name", "description"],
                ["100001", "SKU-000001", "12.50", "", "Red chair", "A comfortable wooden chair."],
                ["100002", "SKU-000002", "14.00", "", "Blue table", "A sturdy table for the kitchen."],
                ["100003", "SKU-000003", "19.75", "", "Green lamp", "A bright lamp for a desk."],
            ],
        )
        output = self.path("selection.fr.csv")
        provider = RecordingProvider(prefix="fr:")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            provider=provider,
        )

        rows = self.read_rows(output)
        self.assertEqual(rows[1][:4], ["100001", "SKU-000001", "12.50", ""])
        self.assertEqual(rows[1][4:], ["fr:Red chair", "fr:A comfortable wooden chair."])
        self.assertEqual(selected_column_names(result), ["name", "description"])
        self.assertCountEqual(
            provider.received_texts,
            [
                "Red chair",
                "Blue table",
                "Green lamp",
                "A comfortable wooden chair.",
                "A sturdy table for the kitchen.",
                "A bright lamp for a desk.",
            ],
        )

    def test_explicit_name_selection_overrides_identifier_skipping(self):
        source = self.write_rows(
            "named.csv",
            [["sku", "description"], ["SKU-000001", "keep this"], ["SKU-000002", "keep that"]],
        )
        output = self.path("named.fr.csv")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=["sku"],
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(
            self.read_rows(output),
            [["sku", "description"], ["fr:SKU-000001", "keep this"], ["fr:SKU-000002", "keep that"]],
        )
        self.assertEqual(selected_column_names(result), ["sku"])

    def test_explicit_zero_based_index_selection_overrides_numeric_skipping(self):
        source = self.write_rows(
            "indexed.csv",
            [["id", "description"], ["1001", "leave one"], ["1002", "leave two"]],
        )
        output = self.path("indexed.fr.csv")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(
            self.read_rows(output),
            [["id", "description"], ["fr:1001", "leave one"], ["fr:1002", "leave two"]],
        )
        self.assertEqual(selected_column_names(result), ["id"])

    def test_empty_selected_cells_are_skipped_without_provider_disclosure(self):
        source = self.write_rows(
            "empty.csv",
            [["text"], [""], ["hello"], ["   "]],
        )
        output = self.path("empty.fr.csv")
        provider = RecordingProvider(prefix="fr:")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=["text"],
            provider=provider,
        )

        self.assertEqual(self.read_rows(output), [["text"], [""], ["fr:hello"], ["   "]])
        self.assertEqual(provider.received_texts, ["hello"])
        self.assertEqual(result.selected_cells, 3)
        self.assertGreaterEqual(result.skipped_cells, 2)


class HeaderPolicyTests(CsvTestCase):
    def test_headers_are_preserved_and_never_sent_by_default(self):
        source = self.write_rows(
            "headers.csv",
            [["id", "Secret heading"], ["1", "hello"]],
        )
        output = self.path("headers.fr.csv")
        provider = RecordingProvider(prefix="fr:")

        translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=["Secret heading"],
            provider=provider,
        )

        self.assertEqual(self.read_rows(output)[0], ["id", "Secret heading"])
        self.assertNotIn("Secret heading", provider.received_texts)

    def test_header_translation_is_opt_in_and_limited_to_selected_columns(self):
        source = self.write_rows(
            "translated_headers.csv",
            [["id", "Text heading"], ["1", "hello"]],
        )
        output = self.path("translated_headers.fr.csv")
        provider = RecordingProvider(prefix="fr:")

        translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=["Text heading"],
            translate_headers=True,
            provider=provider,
        )

        self.assertEqual(self.read_rows(output), [["id", "fr:Text heading"], ["1", "fr:hello"]])
        self.assertIn("Text heading", provider.received_texts)
        self.assertNotIn("id", provider.received_texts)


class ChunkReassemblyTests(CsvTestCase):
    def test_protected_placeholders_never_leave_process_and_round_trip_exactly(self):
        protected = (
            "https://example.test/account/42",
            "{{customer_name}}",
            "${LOCAL_SECRET}",
            "{item_count}",
            "%(total)04d",
            "%08s",
            "<strong>",
            "</strong>",
            "user@example.test",
        )
        text = (
            "  Translate https://example.test/account/42 for {{customer_name}} "
            "with ${LOCAL_SECRET} and {item_count} as %(total)04d or %08s "
            "inside <strong>important</strong>; contact user@example.test now.  "
        )
        source = self.write_rows("protected.csv", [["text"], [text]])
        output = self.path("protected.out.csv")
        provider = IdentityProvider()

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=("text",),
            provider=provider,
            privacy="local-only",
            max_chars=7,
        )

        self.assertEqual(self.read_rows(output), [["text"], [text]])
        self.assertEqual(result.translated_cells, 1)
        self.assertGreater(len(provider.received_texts), 1)
        for token in protected:
            with self.subTest(token=token):
                self.assertFalse(
                    any(token in disclosed for disclosed in provider.received_texts),
                    f"protected token was disclosed to the provider: {token}",
                )

    def _assert_lossless_at_limit(self, text, limit):
        source = self.write_rows("chunks.csv", [["text"], [text]])
        output = self.path("chunks.out.csv")
        provider = IdentityProvider()

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            max_chars=limit,
            batch_size=16,
            provider=provider,
        )

        self.assertEqual(self.read_rows(output), [["text"], [text]])
        chunks = provider.received_texts
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= limit for chunk in chunks), chunks)
        self.assertEqual(result.failed_cells, 0)

    def test_long_unbroken_word_is_chunked_without_character_loss(self):
        self._assert_lossless_at_limit("abcdefghijklmno", 10)

    def test_whitespace_at_a_chunk_boundary_is_not_dropped(self):
        self._assert_lossless_at_limit("abcdefghij klmnop", 10)

    def test_multiline_unicode_text_is_reassembled_exactly(self):
        self._assert_lossless_at_limit("alpha ☃\nbeta U0001f642 gamma", 8)

    def test_low_level_splitter_never_loses_boundary_characters(self):
        for source, limit in [
            ("abcdefghijklmno", 10),
            ("abcdefghij klmnop", 10),
            ("alpha ☃\nbeta U0001f642 gamma", 8),
        ]:
            with self.subTest(source=source, limit=limit):
                chunks = split_text_lossless(source, limit)
                self.assertEqual("".join(chunks), source)
                self.assertTrue(all(0 < len(chunk) <= limit for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
