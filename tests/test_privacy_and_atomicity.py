"""Privacy-boundary and atomic filesystem behavior tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from csv_trans import translate, translate_csv
from csv_trans.core import PrivacyViolation
from csv_trans.csvio import CsvInputError, open_rows as real_open_rows
from csv_trans.exceptions import ProviderConfigurationError, ProviderTimeoutError
from csv_trans.models import PrivacyMode, TranslationConfig, TranslationResult
from csv_trans.providers import EchoProvider, GoogleFreeProvider, HttpResponse

from tests._support import (
    AlwaysFailProvider,
    CsvTestCase,
    FakeHttpClient,
    RecordingProvider,
    no_network,
    status_value,
)


class LocalOnlyPrivacyTests(CsvTestCase):
    def _assert_rejected_without_disclosure(self, source, provider, **options):
        output = self.path("rejected.out.csv")
        caught = None
        result = None
        try:
            with no_network():
                result = translate(
                    source,
                    "en",
                    "fr",
                    output_path=output,
                    columns=[0],
                    provider=provider,
                    privacy=PrivacyMode.LOCAL_ONLY,
                    **options,
                )
        except Exception as error:  # A preflight policy exception is a valid API shape.
            caught = error

        self.assertEqual(provider.calls, [], "privacy rejection must occur before disclosure")
        if caught is None:
            self.assertEqual(status_value(result), "failed")
            self.assertFalse(output.exists())
        else:
            self.assertIsInstance(caught, (PrivacyViolation, ProviderConfigurationError))

    def test_local_only_rejects_a_remote_provider_before_sending_source_text(self):
        source = self.write_rows("secret.csv", [["text"], ["CONFIDENTIAL"]])
        remote = RecordingProvider(
            prefix="remote:",
            name="remote-vendor",
            remote=True,
            endpoint="https://api.vendor.example/v1",
        )

        self._assert_rejected_without_disclosure(source, remote)

    def test_local_only_rejects_a_non_loopback_endpoint_even_if_mislabeled_local(self):
        source = self.write_rows("endpoint.csv", [["text"], ["CONFIDENTIAL"]])
        deceptive = RecordingProvider(
            prefix="remote:",
            name="misconfigured-local",
            remote=False,
            endpoint="http://203.0.113.10:8000/v1",
        )

        self._assert_rejected_without_disclosure(source, deceptive)

    def test_local_only_rejects_an_endpointless_custom_provider_mislabeled_local(self):
        source = self.write_rows("endpointless.csv", [["text"], ["CONFIDENTIAL"]])
        class EndpointlessProvider(RecordingProvider):
            endpoint = None

        endpointless = EndpointlessProvider(
            prefix="unverifiable:",
            name="endpointless-extension",
            remote=False,
        )

        self._assert_rejected_without_disclosure(source, endpointless)

    def test_local_only_allows_only_the_unmodified_builtin_endpointless_echo(self):
        source = self.write_rows("echo.csv", [["text"], ["hello"]])
        output = self.path("echo.out.csv")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=EchoProvider(),
            privacy=PrivacyMode.LOCAL_ONLY,
        )

        self.assertEqual(status_value(result), "success")
        self.assertEqual(self.read_rows(output), [["text"], ["hello"]])

        transformed = EchoProvider(lambda text, source, target: text.upper())
        transformed.calls = []
        self._assert_rejected_without_disclosure(source, transformed)

    def test_local_only_rejects_a_remote_fallback_before_any_provider_runs(self):
        source = self.write_rows("fallback-secret.csv", [["text"], ["CONFIDENTIAL"]])
        output = self.path("fallback-secret.out.csv")
        local = AlwaysFailProvider(
            name="local-model",
            remote=False,
            endpoint="http://127.0.0.1:11434/v1",
        )
        remote = RecordingProvider(
            prefix="remote:",
            name="remote-vendor",
            remote=True,
            endpoint="https://api.vendor.example/v1",
        )
        config = TranslationConfig(
            "en",
            "fr",
            privacy=PrivacyMode.LOCAL_ONLY,
            max_retries=0,
            backoff_base=0,
            jitter=0,
            columns=[0],
            provider=local,
            fallback_providers=(remote,),
        )

        with no_network(), self.assertRaises((PrivacyViolation, ProviderConfigurationError)):
            translate_csv(source, config, output_path=output)

        self.assertEqual(local.calls, [])
        self.assertEqual(remote.calls, [])
        self.assertFalse(output.exists())

    def test_public_mode_still_rejects_plain_http_to_a_remote_host(self):
        source = self.write_rows("public-http.csv", [["text"], ["secret"]])
        output = self.path("public-http.out.csv")
        provider = RecordingProvider(
            name="insecure-remote",
            remote=True,
            endpoint="http://remote.example/v1",
        )

        with self.assertRaises(PrivacyViolation):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
                privacy="public",
            )

        self.assertEqual(provider.calls, [])
        self.assertFalse(output.exists())

    def test_loopback_provider_is_allowed_and_stays_off_the_public_network(self):
        source = self.write_rows("loopback.csv", [["text"], ["private text"]])
        output = self.path("loopback.out.csv")
        local = RecordingProvider(
            prefix="local:",
            name="local-model",
            remote=False,
            endpoint="http://localhost:11434/v1",
        )

        with no_network():
            result = translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=local,
                privacy="local-only",
            )

        self.assertEqual(self.read_rows(output), [["text"], ["local:private text"]])
        self.assertEqual(status_value(result), "success")

    def test_explicitly_approved_private_host_is_allowed_in_local_only_mode(self):
        source = self.write_rows("approved.csv", [["text"], ["private text"]])
        output = self.path("approved.out.csv")
        local = RecordingProvider(
            prefix="approved:",
            name="lan-model",
            remote=False,
            endpoint="http://modelbox.lan:8000/v1",
        )

        with no_network():
            result = translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=local,
                privacy="local-only",
                approved_local_hosts=("modelbox.lan",),
            )

        self.assertEqual(self.read_rows(output), [["text"], ["approved:private text"]])
        self.assertEqual(status_value(result), "success")

    def test_google_html_fallback_is_preflighted_before_primary_disclosure(self):
        source = self.write_rows("google-secret.csv", [["text"], ["CONFIDENTIAL"]])
        output = self.path("google-secret.out.csv")
        client = FakeHttpClient()
        provider = GoogleFreeProvider(http_client=client)
        provider.base_url = "http://127.0.0.1:8765/translate"

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

        self.assertEqual(client.requests, [])
        self.assertFalse(output.exists())

    def test_endpoint_mutation_is_rejected_before_the_next_batch(self):
        source = self.write_rows(
            "mutable.csv", [["text"], ["first secret"], ["second secret"]]
        )
        output = self.path("mutable.out.csv")
        provider = RecordingProvider(
            prefix="local:",
            name="mutable-local",
            remote=False,
            endpoint="http://127.0.0.1:11434/v1",
        )

        def mutate_after_first_batch(event):
            provider.endpoint = "https://remote.example/v1"

        with self.assertRaises(PrivacyViolation):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
                privacy="local-only",
                batch_size=1,
                progress_callback=mutate_after_first_batch,
            )

        self.assertEqual(provider.received_texts, ["first secret"])
        self.assertFalse(output.exists())

    def test_endpoint_mutation_is_rejected_before_a_retry(self):
        class MutatingFailureProvider(RecordingProvider):
            def translate_batch(self, items, source_lang=None, target_lang=None, **kwargs):
                super().translate_batch(items, source_lang, target_lang, **kwargs)
                self.endpoint = "https://remote.example/v1"
                raise ProviderTimeoutError("temporary outage", provider=self.name)

        source = self.write_rows("retry-mutable.csv", [["text"], ["private text"]])
        output = self.path("retry-mutable.out.csv")
        provider = MutatingFailureProvider(
            name="retry-local",
            remote=False,
            endpoint="http://127.0.0.1:11434/v1",
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
                max_retries=1,
                backoff_base=0,
                jitter=0,
            )

        self.assertEqual(provider.received_texts, ["private text"])
        self.assertFalse(output.exists())

    def test_endpoint_mutation_is_rejected_before_a_fallback(self):
        fallback = RecordingProvider(
            prefix="fallback:",
            name="mutable-fallback",
            remote=False,
            endpoint="http://127.0.0.1:11435/v1",
        )

        class MutatingPrimary(AlwaysFailProvider):
            def translate_batch(self, items, source_lang=None, target_lang=None, **kwargs):
                fallback.endpoint = "https://remote.example/v1"
                return super().translate_batch(items, source_lang, target_lang, **kwargs)

        source = self.write_rows("fallback-mutable.csv", [["text"], ["private text"]])
        output = self.path("fallback-mutable.out.csv")
        primary = MutatingPrimary(
            name="local-primary",
            remote=False,
            endpoint="http://127.0.0.1:11434/v1",
        )

        with self.assertRaises(PrivacyViolation):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=primary,
                fallback_providers=(fallback,),
                privacy="local-only",
                max_retries=0,
                backoff_base=0,
                jitter=0,
            )

        self.assertEqual(primary.received_texts, ["private text"])
        self.assertEqual(fallback.calls, [])
        self.assertFalse(output.exists())

    def test_attempt_telemetry_lists_every_google_recipient(self):
        source = self.write_rows("google.csv", [["text"], ["Hello"]])
        output = self.path("google.out.csv")
        response = HttpResponse(
            200,
            json.dumps([[["Bonjour", "Hello"]], None, "en"]),
            {"Content-Type": "application/json"},
        )
        provider = GoogleFreeProvider(http_client=FakeHttpClient(response))

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
        )

        self.assertEqual(
            result.provider_attempts[0].endpoints,
            (
                "https://translate.googleapis.com",
                "https://translate.google.com",
            ),
        )


class AtomicOutputTests(CsvTestCase):
    @staticmethod
    def _fail_report_staging_unlink(original_unlink, report_name):
        def unlink(path, *args, **kwargs):
            if path.name.startswith(f".{report_name}.") and path.name.endswith(".tmp"):
                raise PermissionError("synthetic report staging cleanup failure")
            return original_unlink(path, *args, **kwargs)

        return unlink

    def test_failed_direct_report_write_does_not_publish_stale_result_state(self):
        existing = self.write_text("direct-existing.json", "EXISTING\n")
        result = TranslationResult(
            input_path=self.path("input.csv"),
            output_path=self.path("output.csv"),
            source_language="en",
            target_language="fr",
        )

        with self.assertRaises(FileExistsError):
            result.write_json(existing)

        self.assertIsNone(result.report_path)
        self.assertEqual(existing.read_text(encoding="utf-8"), "EXISTING\n")

    def test_successful_direct_report_write_sets_and_serializes_its_path(self):
        report = self.path("direct-success.json")
        result = TranslationResult(
            input_path=self.path("input.csv"),
            output_path=self.path("output.csv"),
            source_language="en",
            target_language="fr",
        )

        published = result.write_json(report)
        payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(published.resolve(), report.resolve())
        self.assertEqual(result.report_path.resolve(), report.resolve())
        self.assertEqual(Path(payload["report_path"]).resolve(), report.resolve())

    def test_post_publish_report_cleanup_failure_is_a_nonfatal_warning(self):
        report = self.path("direct-cleanup.json")
        result = TranslationResult(
            input_path=self.path("input.csv"),
            output_path=self.path("output.csv"),
            source_language="en",
            target_language="fr",
        )
        original_unlink = Path.unlink

        with patch.object(
            Path,
            "unlink",
            new=self._fail_report_staging_unlink(original_unlink, report.name),
        ):
            published = result.write_json(report)

        self.assertEqual(published.resolve(), report.resolve())
        self.assertEqual(result.report_path.resolve(), report.resolve())
        self.assertTrue(report.is_file())
        self.assertIn(
            "temporary report staging file could not be removed", result.warnings
        )

    def test_report_cleanup_failure_does_not_mask_publication_collision(self):
        report = self.write_text("direct-collision.json", "EXISTING\n")
        result = TranslationResult(
            input_path=self.path("input.csv"),
            output_path=self.path("output.csv"),
            source_language="en",
            target_language="fr",
        )
        original_unlink = Path.unlink

        with (
            patch.object(
                Path,
                "unlink",
                new=self._fail_report_staging_unlink(original_unlink, report.name),
            ),
            self.assertRaises(FileExistsError) as raised,
        ):
            result.write_json(report)

        self.assertIsNone(result.report_path)
        self.assertEqual(report.read_text(encoding="utf-8"), "EXISTING\n")
        self.assertTrue(
            any("staging cleanup also failed" in note for note in raised.exception.__notes__)
        )

    def test_report_cannot_replace_the_input_or_output_csv(self):
        source = self.write_rows("report-source.csv", [["text"], ["hello"]])
        output = self.path("report-output.csv")
        provider = RecordingProvider(prefix="fr:")

        for report in (source, output):
            with self.subTest(report=report), self.assertRaises(ValueError):
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

        self.assertEqual(self.read_rows(source), [["text"], ["hello"]])
        self.assertFalse(output.exists())
        self.assertEqual(provider.calls, [])

    def test_existing_explicit_report_is_rejected_before_provider_work(self):
        source = self.write_rows("report-existing-source.csv", [["text"], ["hello"]])
        output = self.path("report-existing-output.csv")
        report = self.write_text("existing-report.json", "DO NOT REPLACE\n")
        provider = RecordingProvider(prefix="fr:")

        with self.assertRaises(FileExistsError):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                report_path=report,
                columns=[0],
                provider=provider,
            )

        self.assertEqual(report.read_text(encoding="utf-8"), "DO NOT REPLACE\n")
        self.assertFalse(output.exists())
        self.assertEqual(provider.calls, [])

    def test_existing_explicit_report_is_replaced_only_with_overwrite(self):
        source = self.write_rows("report-overwrite-source.csv", [["text"], ["hello"]])
        output = self.path("report-overwrite-output.csv")
        report = self.write_text("report-overwrite.json", "OLD REPORT\n")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            report_path=report,
            columns=[0],
            provider=RecordingProvider(prefix="fr:"),
            overwrite=True,
        )

        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "success")
        self.assertEqual(result.report_path.resolve(), report.resolve())

    def test_automatic_report_never_replaces_the_input_even_with_overwrite(self):
        source = self.write_rows(
            "result.csv.report.json", [["text"], ["ORIGINAL SECRET"]]
        )
        output = self.path("result.csv")
        provider = AlwaysFailProvider(name="local-failure")

        result = translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            privacy="local-only",
            overwrite=True,
            max_retries=0,
            backoff_base=0,
            jitter=0,
        )

        self.assertEqual(self.read_rows(source), [["text"], ["ORIGINAL SECRET"]])
        self.assertEqual(
            result.report_path.resolve(),
            self.path("result.csv.report.1.json").resolve(),
        )
        self.assertTrue(result.report_path.exists())

    def test_automatic_report_numbering_handles_a_publication_race(self):
        source = self.write_rows("race-source.csv", [["text"], ["hello"]])
        output = self.path("race-output.csv")
        first_report = self.path("race-output.csv.report.json")
        original_write_json = TranslationResult.write_json
        calls = []

        def publish_with_race(
            result,
            path,
            *,
            overwrite=False,
            include_column_names=False,
        ):
            calls.append(self.path(path).resolve())
            if len(calls) == 1:
                first_report.write_text("RACE WINNER\n", encoding="utf-8")
            return original_write_json(
                result,
                path,
                overwrite=overwrite,
                include_column_names=include_column_names,
            )

        with patch.object(TranslationResult, "write_json", new=publish_with_race):
            result = translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=AlwaysFailProvider(name="local-failure"),
                privacy="local-only",
                max_retries=0,
                backoff_base=0,
                jitter=0,
            )

        self.assertEqual(first_report.read_text(encoding="utf-8"), "RACE WINNER\n")
        self.assertEqual(
            result.report_path.resolve(),
            self.path("race-output.csv.report.1.json").resolve(),
        )
        self.assertEqual(len(calls), 2)

    def test_existing_output_is_untouched_when_overwrite_is_not_enabled(self):
        source = self.write_rows("source.csv", [["text"], ["hello"]])
        output = self.write_text("existing.csv", "DO NOT REPLACE\n")
        provider = RecordingProvider(prefix="fr:")

        with self.assertRaises(FileExistsError):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
                overwrite=False,
            )

        self.assertEqual(output.read_text(encoding="utf-8"), "DO NOT REPLACE\n")
        self.assertEqual(provider.calls, [], "output preflight should avoid provider cost/disclosure")

    def test_in_place_overwrite_replaces_the_complete_file_atomically(self):
        source = self.write_rows("in-place.csv", [["text"], ["hello"], ["world"]])

        result = translate(
            source,
            "en",
            "fr",
            output_path=source,
            columns=[0],
            provider=RecordingProvider(prefix="fr:"),
            overwrite=True,
        )

        self.assertEqual(self.read_rows(source), [["text"], ["fr:hello"], ["fr:world"]])
        self.assertEqual(status_value(result), "success")
        self.assertEqual(
            sorted(path.name for path in self.directory.iterdir()),
            ["in-place.csv"],
            "atomic write must clean temporary artifacts",
        )

    def test_failed_atomic_replace_preserves_the_previous_destination(self):
        source = self.write_rows("atomic-source.csv", [["text"], ["hello"]])
        output = self.write_text("atomic-output.csv", "ORIGINAL DESTINATION\n")

        with (
            patch.object(os, "replace", side_effect=OSError("simulated replace failure")),
            self.assertRaises(OSError),
        ):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=RecordingProvider(prefix="fr:"),
                overwrite=True,
            )

        self.assertEqual(output.read_text(encoding="utf-8"), "ORIGINAL DESTINATION\n")
        self.assertEqual(
            sorted(path.name for path in self.directory.iterdir()),
            ["atomic-output.csv", "atomic-source.csv"],
            "failed atomic write must clean temporary artifacts",
        )


class SourceConsistencyTests(CsvTestCase):
    def _changing_open_rows(self, source, replacement_rows):
        call_count = 0

        def open_with_change(inspection, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                self.write_rows(source.name, replacement_rows)
            return real_open_rows(inspection, **kwargs)

        return open_with_change

    def test_header_change_after_sampling_is_rejected_before_provider_call(self):
        source = self.write_rows("changing-header.csv", [["text"], ["secret"]])
        output = self.path("changing-header.out.csv")
        provider = RecordingProvider(prefix="fr:")

        with (
            patch(
                "csv_trans.core.open_rows",
                side_effect=self._changing_open_rows(
                    source, [["different header"], ["secret"]]
                ),
            ),
            self.assertRaises(CsvInputError),
        ):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
            )

        self.assertEqual(provider.calls, [])
        self.assertFalse(output.exists())

    def test_data_change_after_sampling_is_rejected_before_provider_call(self):
        source = self.write_rows("changing-data.csv", [["text"], ["secret"]])
        output = self.path("changing-data.out.csv")
        provider = RecordingProvider(prefix="fr:")

        with (
            patch(
                "csv_trans.core.open_rows",
                side_effect=self._changing_open_rows(
                    source, [["text"], ["secret"], ["added row"]]
                ),
            ),
            self.assertRaises(CsvInputError),
        ):
            translate(
                source,
                "en",
                "fr",
                output_path=output,
                columns=[0],
                provider=provider,
            )

        self.assertEqual(provider.calls, [])
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()