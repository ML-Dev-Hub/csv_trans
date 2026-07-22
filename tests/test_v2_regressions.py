"""Adversarial regression tests for v2 safety and recovery boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import csv_trans.core as core_module
from csv_trans import translate
from csv_trans.core import PrivacyViolation
from csv_trans.csvio import (
    AtomicCsvWriter,
    CsvFormat,
    CsvInputError,
    OutputExistsError,
)
from csv_trans.exceptions import ProviderTimeoutError
from csv_trans.models import TranslationConfig
from csv_trans.providers import TranslationItem

from tests._support import (
    AlwaysFailProvider,
    CsvTestCase,
    RecordingProvider,
    status_value,
)


class _SequencedProvider:
    name = "sequenced"
    provider_id = name
    is_remote = False
    endpoint = None

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def translate(self, items, *, source_language, target_language):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if outcome == "malformed":
            return []
        if outcome == "timeout":
            raise ProviderTimeoutError("synthetic timeout", provider=self.name)
        return [TranslationItem(item.id, "ok:" + item.text) for item in items]


class _FixedProvider:
    is_remote = False
    endpoint = None

    def __init__(self, name, value):
        self.name = name
        self.provider_id = name
        self.value = value
        self.calls = 0

    def translate(self, items, *, source_language, target_language):
        self.calls += 1
        return [TranslationItem(item.id, self.value) for item in items]


class RecoveryBudgetRegressionTests(CsvTestCase):
    def test_malformed_and_transient_failures_have_independent_retry_budgets(self):
        sequences = (
            ("malformed", "timeout", "success"),
            ("timeout", "malformed", "success"),
        )
        for index, outcomes in enumerate(sequences):
            with self.subTest(outcomes=outcomes):
                source = self.write_rows(
                    f"separate-budget-{index}.csv", [["text"], ["hello"]]
                )
                output = self.path(f"separate-budget-{index}.out.csv")
                provider = _SequencedProvider(outcomes)

                result = translate(
                    source,
                    "en",
                    "fr",
                    output_path=output,
                    columns=[0],
                    provider=provider,
                    max_retries=1,
                    malformed_retries=1,
                    backoff_base=0,
                    jitter=0,
                )

                self.assertEqual(self.read_rows(output), [["text"], ["ok:hello"]])
                self.assertEqual(provider.calls, 3)
                self.assertEqual(result.retries, 2)
                self.assertEqual(result.provider_attempts[0].retries, 2)
                self.assertEqual(status_value(result), "success")

    def test_persistent_timeout_uses_only_initial_plus_configured_retries(self):
        source = self.write_rows(
            "timeout-batch.csv",
            [["text"], ["one"], ["two"], ["three"], ["four"]],
        )
        output = self.path("timeout-batch.out.csv")
        provider = AlwaysFailProvider(name="persistent-timeout")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            batch_size=8,
            max_retries=2,
            backoff_base=0,
            jitter=0,
        )

        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(
            [len(call["items"]) for call in provider.calls],
            [4, 4, 4],
            "a provider-wide timeout must not recursively split the batch",
        )
        self.assertEqual(result.retries, 2)
        self.assertEqual(result.failed_cells, 4)
        self.assertEqual(status_value(result), "partial")

    def test_output_encoding_failure_moves_the_item_to_the_fallback(self):
        source = self.write_rows("encoding-fallback.csv", [["text"], ["hello"]])
        output = self.path("encoding-fallback.out.csv")
        primary = _FixedProvider("unicode-primary", "caf\u00e9")
        fallback = _FixedProvider("ascii-fallback", "cafe")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=primary,
            fallback_providers=(fallback,),
            output_encoding="ascii",
            max_retries=0,
            malformed_retries=0,
        )

        self.assertEqual(self.read_rows(output, encoding="ascii"), [["text"], ["cafe"]])
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 1)
        self.assertEqual(result.fallbacks, 1)
        self.assertEqual(result.failed_cells, 0)
        self.assertEqual(status_value(result), "success")


class ConfigurationValidationRegressionTests(CsvTestCase):
    def test_integer_limits_reject_floats_booleans_and_negative_values(self):
        invalid = (
            {"batch_size": 1.5},
            {"sample_rows": True},
            {"max_retries": False},
            {"max_failure_details": -1},
            {"cache_size": 2.0},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                TranslationConfig("en", "fr", **values)

    def test_backoff_values_reject_non_finite_numbers_and_wrong_types(self):
        invalid = (
            {"backoff_base": float("nan")},
            {"max_backoff": float("inf")},
            {"jitter": "0.1"},
            {"jitter": True},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                TranslationConfig("en", "fr", **values)

    def test_language_privacy_delimiter_and_callbacks_are_type_checked(self):
        invalid = (
            {"source_language": None},
            {"target_language": 7},
            {"privacy": object()},
            {"delimiter": 1},
            {"progress_callback": "not-callable"},
            {"cancellation_check": 1},
        )
        for values in invalid:
            source = values.pop("source_language", "en")
            target = values.pop("target_language", "fr")
            with self.subTest(values=values), self.assertRaises(ValueError):
                TranslationConfig(source, target, **values)

    def test_one_column_name_string_is_normalized_as_one_selector(self):
        config = TranslationConfig("en", "fr", columns="text")

        self.assertEqual(config.columns, ("text",))


class CancellationAndResponseBoundRegressionTests(CsvTestCase):
    def test_cancellation_set_during_final_provider_call_prevents_publication(self):
        state = {"cancelled": False}

        class CancellingProvider:
            name = "cancelling"
            provider_id = name
            is_remote = False
            endpoint = None

            def __init__(self):
                self.calls = 0

            def translate(self, items, *, source_language, target_language):
                self.calls += 1
                state["cancelled"] = True
                return [
                    TranslationItem(item.id, "translated:" + item.text)
                    for item in items
                ]

        source = self.write_rows("cancel-final.csv", [["text"], ["hello"]])
        output = self.path("cancel-final.out.csv")
        provider = CancellingProvider()

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            cancellation_check=lambda: state["cancelled"],
        )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(status_value(result), "cancelled")
        self.assertIsNone(result.output_path)
        self.assertFalse(output.exists())

    def test_provider_generator_is_consumed_only_to_expected_length_plus_one(self):
        class OversupplyingGeneratorProvider:
            name = "oversupplying-generator"
            provider_id = name
            is_remote = False
            endpoint = None

            def __init__(self):
                self.calls = 0
                self.yielded = 0

            def translate(self, items, *, source_language, target_language):
                self.calls += 1

                def values():
                    for _ in range(1_000):
                        self.yielded += 1
                        yield TranslationItem(items[0].id, items[0].text)

                return values()

        source = self.write_rows("bounded-generator.csv", [["text"], ["hello"]])
        output = self.path("bounded-generator.out.csv")
        provider = OversupplyingGeneratorProvider()

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            malformed_retries=0,
            max_retries=0,
        )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider.yielded, 2)
        self.assertEqual(result.failed_cells, 1)
        self.assertEqual(result.failures[0].category, "invalid_response")
        self.assertEqual(self.read_rows(output), [["text"], ["hello"]])


class FailureDetailBoundRegressionTests(CsvTestCase):
    def test_zero_retained_failure_details_still_returns_partial(self):
        source = self.write_rows("failure-cap-zero.csv", [["text"], ["one"]])
        output = self.path("failure-cap-zero.out.csv")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=AlwaysFailProvider(name="failure-cap-zero"),
            max_failure_details=0,
            max_retries=0,
            backoff_base=0,
            jitter=0,
        )

        self.assertEqual(status_value(result), "partial")
        self.assertEqual(result.failed_cells, 1)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.omitted_failure_count, 1)
        self.assertIsNotNone(result.report_path)

    def test_failure_details_are_capped_without_losing_aggregate_count(self):
        source = self.write_rows(
            "failure-cap.csv",
            [["text"], ["one"], ["two"], ["three"], ["four"], ["five"]],
        )
        output = self.path("failure-cap.out.csv")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=AlwaysFailProvider(name="failure-cap"),
            batch_size=10,
            max_failure_details=2,
            max_retries=0,
            backoff_base=0,
            jitter=0,
        )

        self.assertEqual(result.failed_cells, 5)
        self.assertEqual(len(result.failures), 2)
        self.assertEqual(result.omitted_failure_count, 3)
        self.assertIsNotNone(result.report_path)
        payload = json.loads(result.report_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["failed_cells"], 5)
        self.assertEqual(len(payload["failures"]), 2)
        self.assertEqual(payload["omitted_failure_count"], 3)


class DialectFailClosedRegressionTests(CsvTestCase):
    RAGGED_SEMICOLON = "text;id\nhello;1\nworld;2;extra\n"

    def test_ragged_semicolon_never_falls_back_to_comma(self):
        source = self.write_text("ragged-auto.csv", self.RAGGED_SEMICOLON)
        output = self.path("ragged-auto.out.csv")
        provider = RecordingProvider(prefix="fr:")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
        )

        self.assertEqual(
            self.read_rows(output, delimiter=";"),
            [
                ["text", "id"],
                ["fr:hello", "1"],
                ["fr:world", "2", "extra"],
            ],
        )
        disclosed = [text for call in provider.calls for _, text in call["items"]]
        self.assertEqual(disclosed, ["hello", "world"])
        self.assertEqual(result.dialect["delimiter"], ";")

    def test_explicit_delimiter_allows_a_ragged_semicolon_file(self):
        source = self.write_text("ragged-explicit.csv", self.RAGGED_SEMICOLON)
        output = self.path("ragged-explicit.out.csv")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            delimiter=";",
            columns=["text"],
            provider=RecordingProvider(prefix="fr:"),
        )

        self.assertEqual(
            self.read_rows(output, delimiter=";"),
            [
                ["text", "id"],
                ["fr:hello", "1"],
                ["fr:world", "2", "extra"],
            ],
        )
        self.assertEqual(result.dialect["delimiter"], ";")
        self.assertEqual(status_value(result), "success")


class FilesystemBoundaryRegressionTests(CsvTestCase):
    def _make_file_symlink_or_skip(self, link, target):
        try:
            link.symlink_to(target)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"file symlinks are unavailable: {error}")
        if not link.is_symlink():
            self.skipTest("file symlink creation did not produce a symbolic link")

    def test_output_symlink_is_rejected_even_with_overwrite(self):
        source = self.write_rows("symlink-output-source.csv", [["text"], ["hello"]])
        target = self.write_text("symlink-output-target.csv", "DO NOT TOUCH\n")
        output = self.path("symlink-output.csv")
        self._make_file_symlink_or_skip(output, target)
        provider = RecordingProvider(prefix="fr:")

        with self.assertRaises(OutputExistsError):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
                overwrite=True,
            )

        self.assertEqual(target.read_text(encoding="utf-8"), "DO NOT TOUCH\n")
        self.assertEqual(provider.calls, [])

    def test_report_symlink_is_rejected_even_with_overwrite(self):
        source = self.write_rows("symlink-report-source.csv", [["text"], ["hello"]])
        output = self.path("symlink-report.out.csv")
        target = self.write_text("symlink-report-target.json", "DO NOT TOUCH\n")
        report = self.path("symlink-report.json")
        self._make_file_symlink_or_skip(report, target)
        provider = RecordingProvider(prefix="fr:")

        with self.assertRaises(OutputExistsError):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                report_path=report,
                columns=[0],
                provider=provider,
                overwrite=True,
            )

        self.assertEqual(target.read_text(encoding="utf-8"), "DO NOT TOUCH\n")
        self.assertEqual(provider.calls, [])
        self.assertFalse(output.exists())

    def test_evil_dot_localhost_is_not_treated_as_loopback(self):
        source = self.write_rows("evil-localhost.csv", [["text"], ["secret"]])
        output = self.path("evil-localhost.out.csv")
        provider = RecordingProvider(
            name="deceptive-localhost",
            remote=False,
            endpoint="http://evil.localhost:8000/v1",
        )

        with self.assertRaises(PrivacyViolation):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
                privacy="local-only",
            )

        self.assertEqual(provider.calls, [])
        self.assertFalse(output.exists())

    def test_source_append_during_provider_call_prevents_output_publication(self):
        source = self.write_rows("append-source.csv", [["text"], ["secret"]])
        output = self.path("append-source.out.csv")

        def append_source():
            with source.open("a", encoding="utf-8", newline="") as stream:
                stream.write("appended\n")

        provider = self._mutating_provider("append-source", append_source)

        with self.assertRaises(CsvInputError):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
            )

        self.assertEqual(provider.calls, 1)
        self.assertFalse(output.exists())

    def test_source_replacement_during_provider_call_prevents_output_publication(self):
        source = self.write_rows("replace-source.csv", [["text"], ["secret"]])
        replacement = self.write_rows(
            "replace-source.new.csv", [["text"], ["replacement"]]
        )
        output = self.path("replace-source.out.csv")

        def replace_source():
            os.replace(replacement, source)

        provider = self._mutating_provider("replace-source", replace_source)

        with self.assertRaises(CsvInputError):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
            )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.read_rows(source), [["text"], ["replacement"]])
        self.assertFalse(output.exists())

    def test_source_change_during_output_fsync_is_checked_before_commit(self):
        source = self.write_rows("fsync-source.csv", [["text"], ["hello"]])
        output = self.path("fsync-source.out.csv")
        real_fsync = os.fsync
        changed = False

        def fsync_then_change_source(descriptor):
            nonlocal changed
            real_fsync(descriptor)
            if not changed:
                changed = True
                self.write_rows("fsync-source.csv", [["text"], ["world"]])

        with (
            patch("csv_trans.csvio.os.fsync", side_effect=fsync_then_change_source),
            self.assertRaises(CsvInputError),
        ):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=RecordingProvider(prefix="fr:"),
            )

        self.assertTrue(changed)
        self.assertEqual(self.read_rows(source), [["text"], ["world"]])
        self.assertFalse(output.exists())

    def test_snapshot_cleanup_failure_happens_before_publication(self):
        source = self.write_rows("snapshot-cleanup.csv", [["text"], ["hello"]])
        output = self.path("snapshot-cleanup.out.csv")
        report = self.path("snapshot-cleanup.json")
        original_unlink = Path.unlink

        def reject_snapshot_unlink(path, *args, **kwargs):
            if path.suffix == ".snapshot":
                raise PermissionError("synthetic snapshot lock")
            return original_unlink(path, *args, **kwargs)

        with (
            patch.object(Path, "unlink", reject_snapshot_unlink),
            self.assertRaisesRegex(CsvInputError, "private input snapshot"),
        ):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                report_path=report,
                columns=[0],
                provider=RecordingProvider(prefix="fr:"),
            )

        self.assertFalse(output.exists())
        self.assertFalse(report.exists())

    def test_post_publish_staging_cleanup_failure_does_not_report_fatal(self):
        output = self.path("staging-cleanup.out.csv")
        atomic_writer = AtomicCsvWriter(
            output,
            encoding="utf-8",
            csv_format=CsvFormat(),
            overwrite=False,
        )
        original_unlink = Path.unlink

        def publish_with_a_hard_link(writer):
            os.link(writer._temporary, writer.destination)
            writer._published = True

        def reject_staging_unlink(path, *args, **kwargs):
            if path.suffix == ".tmp":
                raise PermissionError("synthetic staging lock")
            return original_unlink(path, *args, **kwargs)

        with (
            patch.object(AtomicCsvWriter, "_commit", publish_with_a_hard_link),
            patch.object(Path, "unlink", reject_staging_unlink),
        ):
            with atomic_writer as writer:
                writer.writerow(["complete"])

        self.assertEqual(self.read_rows(output), [["complete"]])
        self.assertIn(
            "the private CSV staging file could not be removed",
            atomic_writer.cleanup_warnings,
        )
        for staging in output.parent.glob(f".{output.name}.*.tmp"):
            original_unlink(staging)

    def test_report_is_rolled_back_when_csv_commit_fails(self):
        source = self.write_rows("report-rollback.csv", [["text"], ["hello"]])
        output = self.path("report-rollback.out.csv")
        report = self.path("report-rollback.json")

        with (
            patch.object(
                AtomicCsvWriter,
                "_commit",
                side_effect=OSError("synthetic CSV commit failure"),
            ),
            self.assertRaisesRegex(OSError, "CSV commit failure"),
        ):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                report_path=report,
                columns=[0],
                provider=RecordingProvider(prefix="fr:"),
            )

        self.assertFalse(output.exists())
        self.assertFalse(
            report.exists(),
            "a success report must not survive when its CSV was never published",
        )

    def test_existing_report_is_restored_when_csv_commit_fails(self):
        source = self.write_rows("report-restore.csv", [["text"], ["hello"]])
        output = self.path("report-restore.out.csv")
        report = self.write_text("report-restore.json", "ORIGINAL REPORT\n")

        with (
            patch.object(
                AtomicCsvWriter,
                "_commit",
                side_effect=OSError("synthetic CSV commit failure"),
            ),
            self.assertRaisesRegex(OSError, "CSV commit failure"),
        ):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                report_path=report,
                columns=[0],
                provider=RecordingProvider(prefix="fr:"),
                overwrite=True,
            )

        self.assertFalse(output.exists())
        self.assertEqual(report.read_text(encoding="utf-8"), "ORIGINAL REPORT\n")
        self.assertEqual(list(report.parent.glob(".*.rollback")), [])

    def test_existing_report_is_restored_when_post_publish_validation_fails(self):
        source = self.write_rows("report-identity.csv", [["text"], ["hello"]])
        output = self.path("report-identity.out.csv")
        report = self.write_text("report-identity.json", "ORIGINAL REPORT\n")
        original_identity = core_module._report_file_identity

        def reject_new_report_identity(candidate):
            candidate = Path(candidate)
            if (
                candidate.resolve() == report.resolve()
                and candidate.exists()
                and candidate.read_text(encoding="utf-8") != "ORIGINAL REPORT\n"
            ):
                raise OSError("synthetic post-publish identity failure")
            return original_identity(candidate)

        with (
            patch.object(
                core_module,
                "_report_file_identity",
                side_effect=reject_new_report_identity,
            ),
            self.assertRaisesRegex(OSError, "post-publish identity failure"),
        ):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                report_path=report,
                columns=[0],
                provider=RecordingProvider(prefix="fr:"),
                overwrite=True,
            )

        self.assertFalse(output.exists())
        self.assertEqual(report.read_text(encoding="utf-8"), "ORIGINAL REPORT\n")
        self.assertEqual(list(report.parent.glob(".*.rollback")), [])

    def test_new_report_is_removed_when_post_publish_validation_fails(self):
        source = self.write_rows("new-report-identity.csv", [["text"], ["hello"]])
        output = self.path("new-report-identity.out.csv")
        report = self.path("new-report-identity.json")
        original_identity = core_module._report_file_identity

        def reject_published_identity(candidate):
            candidate = Path(candidate)
            if candidate.resolve() == report.resolve():
                raise OSError("synthetic post-publish identity failure")
            return original_identity(candidate)

        with (
            patch.object(
                core_module,
                "_report_file_identity",
                side_effect=reject_published_identity,
            ),
            self.assertRaisesRegex(OSError, "post-publish identity failure"),
        ):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                report_path=report,
                columns=[0],
                provider=RecordingProvider(prefix="fr:"),
            )

        self.assertFalse(output.exists())
        self.assertFalse(report.exists())

    def test_source_snapshot_defaults_beside_source_and_is_cleaned(self):
        source = self.write_rows("snapshot-location.csv", [["text"], ["hello"]])
        output = self.path("snapshot-location.out.csv")
        observed = []

        class SnapshotObservingProvider(RecordingProvider):
            def translate(self, items, *, source_language, target_language):
                observed.extend(source.parent.glob(".csv-trans-*.snapshot"))
                return super().translate(
                    items,
                    source_language=source_language,
                    target_language=target_language,
                )

        translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=SnapshotObservingProvider(prefix="fr:"),
        )

        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0].parent, source.parent)
        self.assertFalse(observed[0].exists())

    @staticmethod
    def _mutating_provider(name, mutation):
        class MutatingProvider:
            provider_id = name
            is_remote = False
            endpoint = None

            def __init__(self):
                self.name = name
                self.calls = 0

            def translate(self, items, *, source_language, target_language):
                self.calls += 1
                mutation()
                return [
                    TranslationItem(item.id, "translated:" + item.text)
                    for item in items
                ]

        return MutatingProvider()


if __name__ == "__main__":
    unittest.main()
