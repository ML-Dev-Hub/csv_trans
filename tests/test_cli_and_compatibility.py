"""Command-line contract and the retained v1 four-argument wrapper."""

from __future__ import annotations

import importlib
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from csv_trans import cli
from csv_trans import translate as public_translate
from csv_trans import translate_csv as public_translate_csv
from csv_trans.core import translate_csv as core_translate_csv
from csv_trans.models import TranslationConfig

from tests._support import (
    CliResult,
    CsvTestCase,
    RecordingProvider,
    no_network,
    status_value,
)


translate_module = importlib.import_module("csv_trans.translate")


class CliExitCodeTests(CsvTestCase):
    def _run(self, arguments, result=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(cli, "translate_csv", return_value=result or CliResult()) as call,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = cli.main(arguments)
        return code, call, stdout.getvalue(), stderr.getvalue()

    def test_success_returns_zero(self):
        source = self.write_rows("success.csv", [["text"], ["hello"]])
        code, call, _, _ = self._run(
            ["-f", str(source), "-sl", "en", "-tl", "fr"]
        )

        self.assertEqual(code, 0)
        call.assert_called_once()

    def test_partial_result_returns_two_for_machine_detection(self):
        source = self.write_rows("partial.csv", [["text"], ["hello"]])
        code, _, _, _ = self._run(
            ["-f", str(source), "-sl", "en", "-tl", "fr"],
            CliResult("partial"),
        )

        self.assertEqual(code, 2)

    def test_failed_result_returns_one(self):
        source = self.write_rows("failed.csv", [["text"], ["hello"]])
        code, _, _, _ = self._run(
            ["-f", str(source), "-sl", "en", "-tl", "fr"],
            CliResult("failed"),
        )

        self.assertEqual(code, 1)

    def test_fatal_runtime_error_returns_one_without_a_traceback(self):
        source = self.write_rows("fatal.csv", [["text"], ["hello"]])
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(cli, "translate_csv", side_effect=ValueError("bad configuration")),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = cli.main(["-f", str(source), "-sl", "en", "-tl", "fr"])

        self.assertEqual(code, 1)
        self.assertIn("bad configuration", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_parser_errors_use_standard_exit_code_two(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.main([])
        self.assertEqual(raised.exception.code, 2)


class CliAliasTests(CsvTestCase):
    def test_historical_short_aliases_remain_supported(self):
        source = self.write_rows("short.csv", [["text"], ["hello"]], delimiter=";")

        code, call, _, _ = CliExitCodeTests._run(
            self,
            [
                "-f",
                str(source),
                "-sl",
                "en",
                "-tl",
                "fr",
                "-fs",
                ";",
            ],
        )

        self.assertEqual(code, 0)
        config = call.call_args.args[1]
        self.assertEqual((config.source_language, config.target_language), ("en", "fr"))
        self.assertEqual(config.delimiter, ";")

    def test_hyphenated_long_options_are_supported(self):
        source = self.write_rows("hyphen.csv", [["text"], ["hello"]])

        code, call, _, _ = CliExitCodeTests._run(
            self,
            [
                "--file-path",
                str(source),
                "--source-language",
                "en",
                "--target-language",
                "fr",
                "--file-separator",
                ",",
            ],
        )

        self.assertEqual(code, 0)
        self.assertEqual(Path(call.call_args.args[0]), source)
        self.assertEqual(call.call_args.args[1].delimiter, ",")

    def test_readme_file_alias_and_v2_delimiter_alias_are_supported(self):
        source = self.write_rows("documented.csv", [["text"], ["hello"]], delimiter="|")

        code, call, _, _ = CliExitCodeTests._run(
            self,
            [
                "--file",
                str(source),
                "--source-language",
                "en",
                "--target-language",
                "fr",
                "--delimiter",
                "|",
            ],
        )

        self.assertEqual(code, 0)
        self.assertEqual(Path(call.call_args.args[0]), source)
        self.assertEqual(call.call_args.args[1].delimiter, "|")

    def test_underscore_long_options_remain_supported_for_existing_scripts(self):
        source = self.write_rows("underscore.csv", [["text"], ["hello"]])

        code, call, _, _ = CliExitCodeTests._run(
            self,
            [
                "--file_path",
                str(source),
                "--source_language",
                "en",
                "--target_language",
                "fr",
                "--file_separator",
                ",",
            ],
        )

        self.assertEqual(code, 0)
        self.assertEqual(Path(call.call_args.args[0]), source)

    def test_v2_options_reach_the_core_without_network_activity(self):
        source = self.write_rows("options.csv", [["id", "text"], ["1", "hello"]])
        report = self.path("cli-report.json")
        snapshot_directory = self.path("snapshots")
        output = self.path("cli-output.csv")

        code, call, _, _ = CliExitCodeTests._run(
            self,
            [
                "-f",
                str(source),
                "-sl",
                "en",
                "-tl",
                "fr",
                "--output",
                str(output),
                "--columns",
                "text",
                "--translate-headers",
                "--privacy",
                "local-only",
                "--report",
                str(report),
                "--snapshot-directory",
                str(snapshot_directory),
                "--overwrite",
            ],
        )

        self.assertEqual(code, 0)
        config = call.call_args.args[1]
        self.assertEqual(Path(call.call_args.kwargs["output_path"]), output)
        self.assertEqual(config.columns, ("text",))
        self.assertTrue(config.translate_headers)
        self.assertIn(getattr(config.privacy, "value", config.privacy), ("local-only", "local_only"))
        self.assertEqual(Path(config.report_path), report)
        self.assertEqual(Path(config.snapshot_directory), snapshot_directory)
        self.assertTrue(config.overwrite)


class CliV2SafetyTests(CsvTestCase):
    def test_implicit_google_provider_prints_a_remote_disclosure_warning(self):
        source = self.write_rows("implicit-google.csv", [["text"], ["hello"]])

        code, _, _, stderr = CliExitCodeTests._run(
            self, ["-f", str(source), "-sl", "en", "-tl", "fr"]
        )

        self.assertEqual(code, 0)
        self.assertIn("default google-free provider sends selected cell text", stderr)

    def test_quiet_suppresses_the_implicit_google_warning(self):
        source = self.write_rows("quiet-google.csv", [["text"], ["hello"]])

        code, _, _, stderr = CliExitCodeTests._run(
            self,
            ["-f", str(source), "-sl", "en", "-tl", "fr", "--quiet"],
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_bare_numeric_selector_is_a_header_name_and_hash_is_an_index(self):
        parser = cli.build_parser()
        source = self.write_rows("numeric-header.csv", [["0", "text"], ["hello", "world"]])

        named = parser.parse_args(
            ["-f", str(source), "-sl", "en", "-tl", "fr", "--columns", "0"]
        )
        indexed = parser.parse_args(
            ["-f", str(source), "-sl", "en", "-tl", "fr", "--columns", "#0"]
        )

        self.assertEqual(named.columns, ["0"])
        self.assertEqual(indexed.columns, [0])

    def test_dry_run_does_not_require_or_construct_a_credentialed_provider(self):
        source = self.write_rows("dry.csv", [["text"], ["hello"]])
        with patch.dict("os.environ", {}, clear=True):
            code = cli.main(
                [
                    "-f",
                    str(source),
                    "-sl",
                    "en",
                    "-tl",
                    "fr",
                    "--provider",
                    "anthropic",
                    "--dry-run",
                    "--columns",
                    "text",
                    "--quiet",
                ]
            )

        self.assertEqual(code, 0)
        self.assertFalse(self.path("translated_fr_dry.csv").exists())

    def test_dry_run_still_rejects_an_unknown_provider_name(self):
        source = self.write_rows("dry-unknown.csv", [["text"], ["hello"]])
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            code = cli.main(
                [
                    "-f",
                    str(source),
                    "-sl",
                    "en",
                    "-tl",
                    "fr",
                    "--provider",
                    "typo-provider",
                    "--dry-run",
                    "--quiet",
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("unknown provider", stderr.getvalue())

    def test_local_alias_never_defaults_to_the_public_openai_endpoint(self):
        source = self.write_rows("local.csv", [["text"], ["hello"]])
        stderr = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), redirect_stderr(stderr):
            code = cli.main(
                [
                    "-f",
                    str(source),
                    "-sl",
                    "en",
                    "-tl",
                    "fr",
                    "--provider",
                    "local",
                    "--model",
                    "local-model",
                    "--quiet",
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("requires --base-url", stderr.getvalue())
        self.assertNotIn("api.openai.com", stderr.getvalue())

    def test_sensitive_literal_header_is_rejected_without_echoing_its_value(self):
        source = self.write_rows("header.csv", [["text"], ["hello"]])
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = cli.main(
                [
                    "-f",
                    str(source),
                    "-sl",
                    "en",
                    "-tl",
                    "fr",
                    "--header",
                    "Authorization=Bearer do-not-print",
                    "--quiet",
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("sensitive header", stderr.getvalue())
        self.assertNotIn("do-not-print", stderr.getvalue())

    def test_named_compatible_alias_keeps_identity_for_restricted_allowlist(self):
        source = self.write_rows("deepseek.csv", [["text"], ["hello"]])
        output = self.path("deepseek.out.csv")

        with patch.dict("os.environ", {}, clear=True), no_network():
            code = cli.main(
                [
                    "-f",
                    str(source),
                    "-sl",
                    "en",
                    "-tl",
                    "en",
                    "--provider",
                    "deepseek",
                    "--model",
                    "synthetic-model",
                    "--base-url",
                    "https://deepseek.example/v1",
                    "--privacy",
                    "restricted",
                    "--allow-provider",
                    "deepseek",
                    "--columns",
                    "text",
                    "--output",
                    str(output),
                    "--quiet",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(self.read_rows(output), [["text"], ["hello"]])

    def test_noncanonical_provider_aliases_are_normalized_for_allowlists(self):
        self.assertEqual(cli._canonical_provider_name("Claude"), "anthropic")
        self.assertEqual(cli._canonical_provider_name("free"), "google-free")
        self.assertEqual(cli._canonical_provider_name("identity"), "echo")


class CliProviderEnvironmentTests(CsvTestCase):
    def _arguments(self, *extra):
        source = self.write_rows("provider-env.csv", [["text"], ["hello"]])
        return cli.build_parser().parse_args(
            ["-f", str(source), "-sl", "en", "-tl", "fr", *extra]
        )

    def test_official_openai_prefers_csv_trans_key_over_ambient_key(self):
        args = self._arguments("--provider", "openai")
        environment = {
            "CSV_TRANS_OPENAI_MODEL": "official-model",
            "CSV_TRANS_OPENAI_API_KEY": "scoped-key",
            "OPENAI_API_KEY": "ambient-key",
        }

        with patch.dict("os.environ", environment, clear=True):
            provider = cli._build_provider("openai", args, primary=True)

        self.assertEqual(provider.api_key, "scoped-key")
        self.assertEqual(provider.base_url, "https://api.openai.com/v1")

    def test_generic_compatible_endpoint_never_inherits_ambient_openai_key(self):
        args = self._arguments("--provider", "openai-compatible")
        environment = {
            "CSV_TRANS_OPENAI_COMPATIBLE_MODEL": "compatible-model",
            "CSV_TRANS_OPENAI_COMPATIBLE_BASE_URL": "https://compatible.example/v1",
            "OPENAI_API_KEY": "must-not-cross-origin",
        }

        with patch.dict("os.environ", environment, clear=True):
            provider = cli._build_provider(
                "openai-compatible", args, primary=True
            )

        self.assertIsNone(provider.api_key)
        self.assertEqual(provider.base_url, "https://compatible.example/v1")

    def test_primary_explicit_key_and_options_do_not_flow_to_fallback(self):
        args = self._arguments(
            "--provider",
            "openai-compatible",
            "--model",
            "primary-model",
            "--base-url",
            "https://primary.example/v1",
            "--api-key-env",
            "PRIMARY_ONLY_KEY",
            "--header",
            "X-Tenant=primary",
        )
        environment = {
            "PRIMARY_ONLY_KEY": "primary-key",
            "CSV_TRANS_DEEPSEEK_MODEL": "fallback-model",
            "CSV_TRANS_DEEPSEEK_BASE_URL": "https://fallback.example/v1",
            "CSV_TRANS_DEEPSEEK_API_KEY": "fallback-key",
        }

        with patch.dict("os.environ", environment, clear=True):
            primary = cli._build_provider(
                "openai-compatible", args, primary=True
            )
            fallback = cli._build_provider("deepseek", args, primary=False)

        self.assertEqual(primary.api_key, "primary-key")
        self.assertEqual(primary.model, "primary-model")
        self.assertEqual(primary.extra_headers, {"X-Tenant": "primary"})
        self.assertEqual(fallback.api_key, "fallback-key")
        self.assertEqual(fallback.model, "fallback-model")
        self.assertEqual(fallback.base_url, "https://fallback.example/v1")
        self.assertEqual(fallback.extra_headers, {})

    def test_custom_anthropic_endpoint_requires_custom_scoped_key(self):
        args = self._arguments(
            "--provider",
            "anthropic",
            "--model",
            "custom-claude",
            "--base-url",
            "https://anthropic-compatible.example",
        )

        with patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "ambient-key"}, clear=True
        ):
            with self.assertRaisesRegex(
                ValueError, "CSV_TRANS_ANTHROPIC_CUSTOM_API_KEY"
            ):
                cli._build_provider("anthropic", args, primary=True)

        with patch.dict(
            "os.environ",
            {
                "ANTHROPIC_API_KEY": "ambient-key",
                "CSV_TRANS_ANTHROPIC_CUSTOM_API_KEY": "custom-key",
            },
            clear=True,
        ):
            provider = cli._build_provider("anthropic", args, primary=True)

        self.assertEqual(provider.api_key, "custom-key")


class CompatibilityWrapperTests(CsvTestCase):
    def test_public_package_export_is_the_compatibility_function(self):
        self.assertIs(public_translate, translate_module.translate)
        self.assertTrue(callable(public_translate))

    def test_v2_core_is_exported_from_the_package_root(self):
        self.assertIs(public_translate_csv, core_translate_csv)

    def test_wrapper_forwards_v2_options_and_returns_a_structured_result(self):
        source = self.write_rows("wrapper.csv", [["text"], ["hello"]], delimiter=";")
        output = self.path("wrapper.out.csv")
        provider = RecordingProvider(prefix="fr:")

        result = public_translate(
            source,
            "en",
            "fr",
            output_path=output,
            columns=[0],
            provider=provider,
            delimiter=";",
        )

        self.assertEqual(self.read_rows(output, delimiter=";"), [["text"], ["fr:hello"]])
        self.assertEqual(status_value(result), "success")
        self.assertEqual(result.output_path.resolve(), output.resolve())

    def test_wrapper_builds_a_config_and_delegates_to_translate_csv(self):
        source = self.path("keyword.csv")
        expected = CliResult("success")

        with patch.object(translate_module, "translate_csv", return_value=expected) as call:
            translate_module.translate(source, "en", "fr", delimiter="|")

        config = call.call_args.args[1]
        self.assertEqual(config.source_language, "en")
        self.assertEqual(config.target_language, "fr")
        self.assertEqual(config.delimiter, "|")

    # --- csv-trans 1.x calling interface -----------------------------------

    def test_v1_positional_separator_is_forwarded_as_delimiter(self):
        # 1.x: translate(file, source_lang, target_lang, sep)
        source = self.write_rows("v1pos.csv", [["text"], ["hello"]], delimiter=";")
        output = self.path("v1pos.out.csv")

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

    def test_v1_keyword_argument_names_are_accepted(self):
        # 1.x kwargs: file=, source_lang=, target_lang=, sep=
        source = self.write_rows("v1kw.csv", [["text"], ["hello"]], delimiter=";")
        output = self.path("v1kw.out.csv")

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

    def test_v1_main_alias_is_exported_and_delegates(self):
        # 1.x: from csv_trans.translate import main; main(file_path, sl, tl, file_separator)
        self.assertIn("main", translate_module.__all__)
        source = self.write_rows("v1main.csv", [["text"], ["hello"]], delimiter=";")
        output = self.path("v1main.out.csv")

        result = translate_module.main(
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

    def test_explicit_v2_delimiter_wins_over_the_v1_sep_positional(self):
        source = self.path("precedence.csv")
        expected = CliResult("success")

        with patch.object(translate_module, "translate_csv", return_value=expected) as call:
            translate_module.translate(source, "en", "fr", ",", delimiter="|")

        self.assertEqual(call.call_args.args[1].delimiter, "|")


class ConfigurationPrecedenceTests(CsvTestCase):
    def test_reusable_config_can_be_passed_positionally(self):
        source = self.write_rows("config.csv", [["text"], ["hello"]])
        output = self.path("config.out.csv")
        config = TranslationConfig(
            "en",
            "fr",
            provider=RecordingProvider(prefix="fr:"),
            columns=[0],
            max_retries=0,
            backoff_base=0,
            jitter=0,
        )

        result = core_translate_csv(source, config, output_path=output)

        self.assertEqual(self.read_rows(output), [["text"], ["fr:hello"]])
        self.assertEqual(status_value(result), "success")

    def test_translate_csv_rejects_a_non_config_second_argument(self):
        with self.assertRaises(TypeError):
            translate_module.translate_csv("x.csv", "en")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()