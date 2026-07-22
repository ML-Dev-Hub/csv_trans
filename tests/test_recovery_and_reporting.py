"""Bounded recovery, stable mapping, partial results, and report tests."""

from __future__ import annotations

import json
import unittest

from csv_trans.core import translate_csv
from csv_trans.exceptions import ProviderContextLimitError
from csv_trans.models import TranslationConfig
from csv_trans.providers import TranslationItem

from tests._support import (
    AlwaysFailProvider,
    AuthenticationFailProvider,
    ContextLimitUntilSingleProvider,
    CorrectableMalformedProvider,
    CsvTestCase,
    FailOnceProvider,
    RecordingProvider,
    RejectTextProvider,
    ReverseResponseProvider,
    SplitUntilSingleProvider,
    no_network,
    result_payload,
    status_value,
)


class RetryAndFallbackTests(CsvTestCase):
    def test_transient_failure_is_retried_with_a_finite_budget(self):
        source = self.write_rows("retry.csv", [["text"], ["hello"]])
        output = self.path("retry.out.csv")
        provider = FailOnceProvider()
        config = TranslationConfig(
            "en", "fr", max_retries=2, backoff_base=0, jitter=0, batch_size=8
        )

        with no_network():
            result = translate_csv(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
                config=config,
            )

        self.assertEqual(self.read_rows(output), [["text"], ["retried:hello"]])
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(result.retries, 1)
        self.assertEqual(status_value(result), "success")

    def test_explicit_public_fallback_runs_only_after_primary_exhaustion(self):
        source = self.write_rows("fallback.csv", [["text"], ["hello"]])
        output = self.path("fallback.out.csv")
        primary = AlwaysFailProvider(name="primary")
        fallback = RecordingProvider(prefix="fallback:", name="fallback")

        with no_network():
            result = translate_csv(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=primary,
                fallback_providers=(fallback,),
                max_retries=0,
                backoff_base=0,
                privacy="public",
            )

        self.assertEqual(self.read_rows(output), [["text"], ["fallback:hello"]])
        self.assertGreaterEqual(len(primary.calls), 1)
        self.assertEqual(len(fallback.calls), 1)
        self.assertEqual(result.fallbacks, 1)
        self.assertEqual(status_value(result), "success")

    def test_no_fallback_is_invented_when_none_was_explicitly_configured(self):
        source = self.write_rows("no-fallback.csv", [["text"], ["hello"]])
        output = self.path("no-fallback.out.csv")
        primary = AlwaysFailProvider(name="only-provider")

        with no_network():
            result = translate_csv(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=primary,
                fallback_providers=(),
                max_retries=0,
                backoff_base=0,
            )

        self.assertEqual(self.read_rows(output), [["text"], ["hello"]])
        self.assertEqual(result.fallbacks, 0)
        self.assertEqual(result.failed_cells, 1)
        self.assertEqual(status_value(result), "partial")

    def test_authentication_failure_is_not_blindly_retried(self):
        source = self.write_rows("auth.csv", [["text"], ["hello"]])
        output = self.path("auth.out.csv")
        provider = AuthenticationFailProvider()

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            max_retries=5,
            backoff_base=0,
            jitter=0,
        )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result.retries, 0)
        self.assertEqual(self.read_rows(output), [["text"], ["hello"]])
        self.assertEqual(result.failures[0].category, "authentication")


class BatchValidationAndSplittingTests(CsvTestCase):
    def test_context_limit_splits_a_batch_instead_of_retrying_it_unchanged(self):
        source = self.write_rows(
            "context.csv", [["text"], ["one"], ["two"], ["three"]]
        )
        output = self.path("context.out.csv")
        provider = ContextLimitUntilSingleProvider()

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            batch_size=8,
            max_retries=5,
            backoff_base=0,
            jitter=0,
        )

        self.assertEqual(
            self.read_rows(output),
            [["text"], ["small:one"], ["small:two"], ["small:three"]],
        )
        sizes = [len(call["items"]) for call in provider.calls]
        self.assertEqual(sizes.count(1), 3)
        self.assertEqual(result.retries, 0)

    def test_malformed_batch_is_split_until_every_item_can_succeed(self):
        source = self.write_rows(
            "split.csv",
            [["text"], ["one"], ["two"], ["three"], ["four"]],
        )
        output = self.path("split.out.csv")
        provider = SplitUntilSingleProvider()

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            batch_size=8,
            max_retries=0,
            backoff_base=0,
        )

        self.assertEqual(
            self.read_rows(output),
            [["text"], ["single:one"], ["single:two"], ["single:three"], ["single:four"]],
        )
        sizes = [len(call["items"]) for call in provider.calls]
        self.assertTrue(any(size > 1 for size in sizes), sizes)
        self.assertGreaterEqual(sizes.count(1), 4)
        self.assertEqual(result.failed_cells, 0)

    def test_reordered_provider_items_are_not_applied_to_the_wrong_cells(self):
        source = self.write_rows(
            "order.csv",
            [["text"], ["first"], ["second"], ["third"]],
        )
        output = self.path("order.out.csv")

        provider = ReverseResponseProvider()
        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            batch_size=8,
            max_retries=0,
            backoff_base=0,
        )

        self.assertEqual(
            self.read_rows(output),
            [["text"], ["ordered:first"], ["ordered:second"], ["ordered:third"]],
        )
        self.assertGreater(
            len(provider.calls),
            1,
            "an out-of-order response must enter bounded recovery, not be accepted",
        )
        self.assertEqual(result.failed_cells, 0)

    def test_one_corrective_retry_can_recover_an_invalid_id_set(self):
        source = self.write_rows("correct.csv", [["text"], ["hello"]])
        output = self.path("correct.out.csv")
        provider = CorrectableMalformedProvider()

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            max_retries=0,
            backoff_base=0,
        )

        self.assertEqual(self.read_rows(output), [["text"], ["corrected:hello"]])
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(result.failed_cells, 0)


class AdaptiveAndResponseSafetyTests(CsvTestCase):
    def test_single_context_limited_cell_is_adaptively_split_per_request(self):
        class ContextBoundProvider:
            name = "context-bound"
            provider_id = name
            is_remote = False
            base_url = None

            def __init__(self):
                self.lengths = []

            def translate(self, items, *, source_language, target_language):
                self.lengths.extend(len(item.text) for item in items)
                if any(len(item.text) > 8 for item in items):
                    raise ProviderContextLimitError(
                        "synthetic context limit", provider=self.provider_id
                    )
                return [TranslationItem(item.id, item.text) for item in items]

        text = "abcdefghijklmnopqrstuvwxyz"
        source = self.write_rows("adaptive.csv", [["text"], [text]])
        output = self.path("adaptive.out.csv")
        provider = ContextBoundProvider()

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            max_chars=100,
            min_adaptive_chars=4,
            max_retries=0,
        )

        self.assertEqual(self.read_rows(output), [["text"], [text]])
        self.assertEqual(status_value(result), "success")
        self.assertTrue(any(length > 8 for length in provider.lengths))
        self.assertTrue(any(length <= 8 for length in provider.lengths))

    def test_core_dispatches_malformed_retry_to_corrective_provider_method(self):
        class CorrectiveProvider:
            name = "corrective"
            provider_id = name
            is_remote = False
            base_url = None

            def __init__(self):
                self.ordinary_calls = 0
                self.corrective_calls = 0

            def translate(self, items, *, source_language, target_language):
                self.ordinary_calls += 1
                return []

            def translate_corrective(
                self, items, *, source_language, target_language
            ):
                self.corrective_calls += 1
                return [
                    TranslationItem(item.id, "fixed:" + item.text) for item in items
                ]

        source = self.write_rows("corrective.csv", [["text"], ["hello"]])
        output = self.path("corrective.out.csv")
        provider = CorrectiveProvider()

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            max_retries=0,
            malformed_retries=1,
            backoff_base=0,
            jitter=0,
        )

        self.assertEqual(self.read_rows(output), [["text"], ["fixed:hello"]])
        self.assertEqual(provider.ordinary_calls, 1)
        self.assertEqual(provider.corrective_calls, 1)
        self.assertEqual(result.retries, 1)

    def test_empty_translation_is_rejected_and_original_cell_is_preserved(self):
        class EmptyProvider:
            name = "empty"
            provider_id = name
            is_remote = False
            base_url = None

            def translate(self, items, *, source_language, target_language):
                return [TranslationItem(item.id, "") for item in items]

        source = self.write_rows("empty-result.csv", [["text"], ["hello"]])
        output = self.path("empty-result.out.csv")

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=EmptyProvider(),
            malformed_retries=0,
        )

        self.assertEqual(self.read_rows(output), [["text"], ["hello"]])
        self.assertEqual(status_value(result), "partial")
        self.assertEqual(result.failures[0].category, "invalid_response")

    def test_unencodable_translation_preserves_an_encodable_original(self):
        source = self.write_rows("encoding-result.csv", [["text"], ["hello"]])
        output = self.path("encoding-result.out.csv")
        provider = RecordingProvider(prefix="é")

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            output_encoding="ascii",
        )

        self.assertEqual(
            self.read_rows(output, encoding="ascii"), [["text"], ["hello"]]
        )
        self.assertEqual(status_value(result), "partial")
        self.assertEqual(result.failures[0].category, "output_encoding")


class OperationalHookTests(CsvTestCase):
    def test_progress_callback_failure_cannot_invalidate_completed_output(self):
        source = self.write_rows("progress.csv", [["text"], ["hello"]])
        output = self.path("progress.out.csv")

        def broken_callback(event):
            raise RuntimeError("synthetic callback error")

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=RecordingProvider(prefix="fr:"),
            batch_size=1,
            progress_callback=broken_callback,
        )

        self.assertEqual(self.read_rows(output), [["text"], ["fr:hello"]])
        self.assertEqual(status_value(result), "success")
        self.assertIn("progress callback failed and was ignored", result.warnings)

    def test_dry_run_cancellation_returns_cancelled_without_output(self):
        source = self.write_rows("dry-cancel.csv", [["text"], ["hello"]])
        output = self.path("dry-cancel.out.csv")

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=RecordingProvider(),
            dry_run=True,
            cancellation_check=lambda: True,
        )

        self.assertEqual(status_value(result), "cancelled")
        self.assertIsNone(result.output_path)
        self.assertFalse(output.exists())


class PartialFailureAndReportTests(CsvTestCase):
    def test_one_untranslatable_cell_is_preserved_while_other_cells_continue(self):
        source = self.write_rows(
            "partial.csv",
            [["id", "text"], ["1", "good"], ["2", "bad"], ["3", "also good"]],
        )
        output = self.path("partial.out.csv")
        provider = RejectTextProvider("bad")

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=["text"],
            provider=provider,
            max_retries=0,
            backoff_base=0,
            batch_size=8,
        )

        self.assertEqual(
            self.read_rows(output),
            [
                ["id", "text"],
                ["1", "ok:good"],
                ["2", "bad"],
                ["3", "ok:also good"],
            ],
        )
        self.assertEqual(status_value(result), "partial")
        self.assertEqual(result.translated_cells, 2)
        self.assertEqual(result.failed_cells, 1)
        self.assertLess(len(provider.calls), 20, "recovery must always be bounded")

        failure = result.failures[0]
        self.assertEqual(failure.column_name, "text")
        self.assertTrue(failure.original_preserved)
        self.assertGreaterEqual(failure.attempts, 1)

    def test_json_report_is_complete_and_does_not_leak_text_or_secrets(self):
        source = self.write_rows(
            "report.csv",
            [["id", "text"], ["1", "ordinary"], ["2", "TOP SECRET CELL"]],
        )
        output = self.path("report.out.csv")
        report = self.path("report.json")
        provider = RejectTextProvider("TOP SECRET CELL", name="safe-local")
        provider.api_key = "sk-DO-NOT-SERIALIZE"

        result = translate_csv(
            source,
            "en",
            "fr",
            output_path=output,
            columns=["text"],
            provider=provider,
            max_retries=0,
            backoff_base=0,
            report_path=report,
        )

        raw_report = report.read_text(encoding="utf-8")
        payload = json.loads(raw_report)
        self.assertEqual(payload, result_payload(result))
        self.assertNotIn("TOP SECRET CELL", raw_report)
        self.assertNotIn("sk-DO-NOT-SERIALIZE", raw_report)

        for key in (
            "input_path",
            "output_path",
            "total_cells",
            "selected_cells",
            "translated_cells",
            "cached_cells",
            "skipped_cells",
            "failed_cells",
            "source_language",
            "target_language",
            "selected_columns",
            "input_encoding",
            "output_encoding",
            "dialect",
            "provider_attempts",
            "retries",
            "fallbacks",
            "failures",
            "status",
        ):
            self.assertIn(key, payload)

        self.assertEqual(payload["total_cells"], 4)
        self.assertEqual(payload["selected_cells"], 2)
        self.assertEqual(payload["translated_cells"], 1)
        self.assertEqual(payload["failed_cells"], 1)
        self.assertEqual(len(payload["failures"]), 1)
        self.assertTrue(payload["provider_attempts"])
        self.assertIn(
            "safe-local",
            {attempt["provider"] for attempt in payload["provider_attempts"]},
        )
        failure = payload["failures"][0]
        for key in (
            "row",
            "column_name",
            "category",
            "provider",
            "attempts",
            "original_preserved",
        ):
            self.assertIn(key, failure)


if __name__ == "__main__":
    unittest.main()
