"""Command-line interface for the csv-trans v2 engine."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Sequence
from urllib.parse import urlsplit

from . import __version__
from .core import translate_csv
from .models import PrivacyMode, RunStatus


_SUPPORTED_PROVIDER_IDS = {
    "anthropic",
    "claude",
    "deepseek",
    "default",
    "echo",
    "free",
    "google",
    "google-free",
    "identity",
    "llama.cpp",
    "lm-studio",
    "local",
    "localai",
    "ollama",
    "openai",
    "openai-compatible",
    "qwen",
    "vllm",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csv-trans",
        description="Translate selected CSV fields while preserving row and column shape.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-f",
        "--file",
        "--file-path",
        "--file_path",
        dest="input_path",
        required=True,
        help="input CSV path",
    )
    parser.add_argument(
        "-sl",
        "--source-language",
        "--source_language",
        dest="source_language",
        required=True,
        help="source language code/name, or auto",
    )
    parser.add_argument(
        "-tl",
        "--target-language",
        "--target_language",
        dest="target_language",
        required=True,
        help="target language code/name",
    )
    parser.add_argument("-o", "--output", type=Path, help="output CSV path")
    parser.add_argument(
        "-fs",
        "--delimiter",
        "--file-separator",
        "--file_separator",
        dest="delimiter",
        help="one-character delimiter; auto-detected when omitted",
    )
    parser.add_argument(
        "--columns",
        nargs="+",
        type=_column_selector,
        help="column names or zero-based indexes written as #N",
    )
    parser.add_argument(
        "--translate-headers",
        action="store_true",
        help="translate selected column headers as well as their values",
    )
    parser.add_argument("--encoding", help="input encoding; default is BOM/strict UTF-8")
    parser.add_argument(
        "--output-encoding", default="utf-8", help="output encoding (default: utf-8)"
    )
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output")
    parser.add_argument(
        "--provider",
        action="append",
        help=(
            "primary provider ID; repeat to append fallbacks (default: remote, "
            "experimental google-free)"
        ),
    )
    parser.add_argument(
        "--fallback-provider",
        action="append",
        default=[],
        help="explicit fallback provider ID (repeatable)",
    )
    parser.add_argument("--model", help="model for the primary LLM provider")
    parser.add_argument("--base-url", help="base URL for the primary LLM provider")
    parser.add_argument(
        "--api-key-env",
        help="read the primary provider API key from this environment variable",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="additional primary-provider HTTP header (repeatable; avoid secrets in shell history)",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds")
    parser.add_argument(
        "--privacy",
        choices=[mode.value for mode in PrivacyMode],
        default=PrivacyMode.PUBLIC.value,
    )
    parser.add_argument(
        "--allow-provider",
        action="append",
        default=[],
        help="provider allowed in restricted mode (repeatable)",
    )
    parser.add_argument(
        "--approved-local-host",
        action="append",
        default=[],
        help="exact non-loopback host approved for local-only mode",
    )
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--max-chars", type=int, default=3_500)
    parser.add_argument("--min-adaptive-chars", type=int, default=32)
    parser.add_argument(
        "--max-field-chars",
        type=int,
        default=64 * 1024 * 1024,
        help="maximum decoded characters in one CSV field",
    )
    parser.add_argument("--max-row-chars", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--max-columns", type=int, default=10_000)
    parser.add_argument("--max-sample-chars", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--max-pending-chars", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-failure-details", type=int, default=10_000)
    parser.add_argument(
        "--allow-empty-translations",
        action="store_true",
        help="accept an empty provider result for non-empty source text",
    )
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--malformed-retries", type=int, default=1)
    parser.add_argument("--backoff-base", type=float, default=0.5)
    parser.add_argument("--max-backoff", type=float, default=8.0)
    parser.add_argument("--report", type=Path, help="write the structured JSON result here")
    parser.add_argument(
        "--snapshot-directory",
        type=Path,
        help=(
            "directory for the transient plaintext source snapshot "
            "(default: beside the input CSV)"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="inspect selection without translating")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--quiet", action="store_true", help="suppress the human summary")
    return parser


def parse_arguments_from_cli(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Compatibility helper retained for callers that extended the old parser."""

    # The old function mutated a supplied empty parser.  Recreating every alias
    # twice invites drift, so copy the actions from the canonical parser.
    canonical = build_parser()
    for action in canonical._actions:  # argparse has no public action-copy API
        if not action.option_strings or action.dest == "help":
            continue
        if any(option in parser._option_string_actions for option in action.option_strings):
            continue
        parser._add_action(action)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a stable machine-readable exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("--timeout must be a finite number greater than zero")
        provider_ids, provider_was_explicit = _provider_ids(args.provider, args.fallback_provider)
        unknown_provider_ids = sorted(set(provider_ids) - _SUPPORTED_PROVIDER_IDS)
        if unknown_provider_ids:
            raise ValueError(
                "unknown provider(s): " + ", ".join(unknown_provider_ids)
            )
        if args.dry_run:
            # Selection inspection must never require credentials, resolve a
            # remote endpoint, or construct a provider that might make a call.
            from .providers import EchoProvider

            providers = [EchoProvider()]
        else:
            providers = [
                _build_provider(name, args, primary=index == 0)
                for index, name in enumerate(provider_ids)
            ]
        allowed = [_canonical_provider_name(name) for name in args.allow_provider]
        if (
            args.privacy == PrivacyMode.RESTRICTED.value
            and not allowed
            and provider_was_explicit
        ):
            allowed = [_provider_name(provider) for provider in providers]

        if not provider_was_explicit and not args.dry_run and not args.quiet:
            print(
                "csv-trans: warning: the default google-free provider sends selected "
                "cell text to undocumented Google web endpoints; use --provider to "
                "choose a different destination",
                file=sys.stderr,
            )

        result = translate_csv(
            args.input_path,
            args.source_language,
            args.target_language,
            output_path=args.output,
            delimiter=args.delimiter,
            columns=args.columns,
            translate_headers=args.translate_headers,
            encoding=args.encoding,
            output_encoding=args.output_encoding,
            overwrite=args.overwrite,
            provider=providers[0],
            fallback_providers=tuple(providers[1:]),
            privacy=args.privacy,
            allowed_providers=allowed,
            approved_local_hosts=args.approved_local_host,
            batch_size=args.batch_size,
            max_chars=args.max_chars,
            min_adaptive_chars=args.min_adaptive_chars,
            max_field_chars=args.max_field_chars,
            max_row_chars=args.max_row_chars,
            max_columns=args.max_columns,
            max_sample_chars=args.max_sample_chars,
            max_pending_chars=args.max_pending_chars,
            max_failure_details=args.max_failure_details,
            allow_empty_translations=args.allow_empty_translations,
            max_retries=args.max_retries,
            malformed_retries=args.malformed_retries,
            backoff_base=args.backoff_base,
            max_backoff=args.max_backoff,
            report_path=args.report,
            snapshot_directory=args.snapshot_directory,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"csv-trans: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    elif not args.quiet:
        status = _status_value(result.status)
        destination = getattr(result, "output_path", None)
        summary = (
            f"{status}: translated={result.translated_cells}, "
            f"failed={result.failed_cells}, skipped={result.skipped_cells}"
        )
        if destination:
            summary += f", output={destination}"
        report_path = getattr(result, "report_path", None)
        if report_path:
            summary += f", report={report_path}"
        if status == RunStatus.DRY_RUN.value:
            selected = [
                f"#{column.index}={column.name!r} ({column.reason})"
                for column in getattr(result, "selected_columns", ())
                if column.selected
            ]
            summary += "; selected-columns=" + (", ".join(selected) or "none")
        print(summary)

    status = _status_value(result.status)
    if status in {RunStatus.SUCCESS.value, RunStatus.DRY_RUN.value}:
        return 0
    if status == RunStatus.PARTIAL.value:
        return 2
    return 1


def _column_selector(value: str) -> str | int:
    if value.startswith("#") and value[1:].isdigit():
        return int(value[1:])
    return value


def _provider_ids(
    cli_primary: Sequence[str] | None, cli_fallbacks: Sequence[str]
) -> tuple[list[str], bool]:
    raw: list[str] = []
    explicit = bool(cli_primary) or bool(os.environ.get("CSV_TRANS_PROVIDER"))
    if cli_primary:
        raw.extend(cli_primary)
    elif os.environ.get("CSV_TRANS_PROVIDER"):
        raw.extend(os.environ["CSV_TRANS_PROVIDER"].split(","))
    else:
        raw.append("google-free")
    raw.extend(cli_fallbacks)
    names = [item.strip().casefold() for value in raw for item in value.split(",") if item.strip()]
    if not names:
        raise ValueError("at least one provider is required")
    return names, explicit


def _build_provider(name: str, args: argparse.Namespace, *, primary: bool) -> Any:
    from .providers import (
        AnthropicProvider,
        EchoProvider,
        GoogleFreeProvider,
        OpenAICompatibleProvider,
    )

    # Shared CLI overrides belong only to the primary provider. Reusing a base
    # URL/header across different fallback protocols could disclose one
    # vendor's credential to another destination. Fallbacks use their
    # provider-specific environment variables; advanced chains should use the
    # Python API and explicit provider objects.
    extra_headers = _parse_headers(args.header) if primary else {}
    if name in {"google", "google-free", "free", "default"}:
        return GoogleFreeProvider(timeout=min(args.timeout, 60.0))
    if name in {"echo", "identity"}:
        return EchoProvider()
    if name in {"anthropic", "claude"}:
        base_url = (args.base_url if primary else None) or os.environ.get(
            "CSV_TRANS_ANTHROPIC_BASE_URL"
        ) or AnthropicProvider.DEFAULT_BASE_URL
        official_endpoint = _endpoint_host(base_url) == "api.anthropic.com"
        key = _credential(
            args.api_key_env if primary else None,
            (
                "CSV_TRANS_ANTHROPIC_API_KEY"
                if official_endpoint
                else "CSV_TRANS_ANTHROPIC_CUSTOM_API_KEY"
            ),
            "ANTHROPIC_API_KEY" if official_endpoint else None,
            required=True,
        )
        model = (args.model if primary else None) or os.environ.get(
            "CSV_TRANS_ANTHROPIC_MODEL"
        )
        if not model:
            raise ValueError("Anthropic requires --model or CSV_TRANS_ANTHROPIC_MODEL")
        options: dict[str, Any] = {
            "model": model,
            "api_key": key,
            "timeout": args.timeout,
            "extra_headers": extra_headers,
            "allow_insecure_http": args.privacy == PrivacyMode.LOCAL_ONLY.value,
        }
        options["base_url"] = base_url
        return AnthropicProvider(**options)
    if name in {
        "openai",
        "openai-compatible",
        "local",
        "qwen",
        "deepseek",
        "ollama",
        "llama.cpp",
        "vllm",
        "lm-studio",
        "localai",
    }:
        env_prefix = {
            "deepseek": "DEEPSEEK",
            "qwen": "QWEN",
            "local": "LOCAL",
            "ollama": "OLLAMA",
            "llama.cpp": "LLAMA_CPP",
            "vllm": "VLLM",
            "lm-studio": "LM_STUDIO",
            "localai": "LOCALAI",
            "openai-compatible": "OPENAI_COMPATIBLE",
        }.get(name, "OPENAI")
        model = (args.model if primary else None) or os.environ.get(
            f"CSV_TRANS_{env_prefix}_MODEL"
        )
        if not model:
            raise ValueError(
                "OpenAI-compatible providers require --model or their provider-specific model environment variable"
            )
        base_url = (args.base_url if primary else None) or os.environ.get(
            f"CSV_TRANS_{env_prefix}_BASE_URL"
        )
        if name == "openai":
            base_url = base_url or "https://api.openai.com/v1"
        elif not base_url:
            raise ValueError(
                f"provider {name!r} requires --base-url (when primary) or "
                f"CSV_TRANS_{env_prefix}_BASE_URL"
            )
        official_openai = (
            name == "openai" and _endpoint_host(base_url) == "api.openai.com"
        )
        if name == "openai" and not official_openai:
            credential_name = "CSV_TRANS_OPENAI_CUSTOM_API_KEY"
            fallback_credential_name = None
            credential_required = False
        else:
            credential_name = f"CSV_TRANS_{env_prefix}_API_KEY"
            fallback_credential_name = "OPENAI_API_KEY" if official_openai else None
            credential_required = official_openai
        key = _credential(
            args.api_key_env if primary else None,
            credential_name,
            fallback_credential_name,
            required=credential_required,
        )
        provider = OpenAICompatibleProvider(
            model=model,
            api_key=key,
            base_url=base_url,
            timeout=args.timeout,
            extra_headers=extra_headers,
            allow_insecure_http=args.privacy == PrivacyMode.LOCAL_ONLY.value,
        )
        # Preserve the selected alias for restricted allowlists and telemetry;
        # the wire protocol remains OpenAI-compatible.
        provider.provider_id = name
        provider.name = name
        return provider
    raise ValueError(f"unknown provider: {name}")


def _credential(
    explicit_name: str | None,
    primary_name: str,
    fallback_name: str | None,
    *,
    required: bool,
) -> str | None:
    if explicit_name:
        value = os.environ.get(explicit_name)
        if not value:
            raise ValueError(f"environment variable {explicit_name} is not set")
        return value
    value = os.environ.get(primary_name)
    if not value and fallback_name:
        value = os.environ.get(fallback_name)
    if required and not value:
        alternatives = f" (or {fallback_name})" if fallback_name else ""
        raise ValueError(f"set {primary_name}{alternatives}")
    return value


def _parse_headers(values: Sequence[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    sensitive = {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
    }
    for value in values:
        name, separator, header_value = value.partition("=")
        if not separator or not name.strip():
            raise ValueError("invalid --header; expected NAME=VALUE")
        normalized_name = name.strip()
        folded_name = normalized_name.casefold()
        if folded_name in sensitive or folded_name.endswith(
            ("-api-key", "-auth-token", "-access-token")
        ):
            raise ValueError(
                f"sensitive header {normalized_name!r} is not accepted on the command line; "
                "use the provider API-key environment variable"
            )
        headers[normalized_name] = header_value
    return headers


def _provider_name(provider: Any) -> str:
    return str(getattr(provider, "name", getattr(provider, "provider_id", type(provider).__name__)))


def _endpoint_host(url: str) -> str | None:
    try:
        host = urlsplit(url).hostname
    except (TypeError, ValueError):
        return None
    return host.casefold().rstrip(".") if host else None


def _canonical_provider_name(name: str) -> str:
    normalized = name.strip().casefold()
    return {
        "google": "google-free",
        "free": "google-free",
        "default": "google-free",
        "claude": "anthropic",
        "identity": "echo",
    }.get(normalized, normalized)


def _status_value(status: Any) -> str:
    return str(getattr(status, "value", status)).casefold()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main", "parse_arguments_from_cli"]
