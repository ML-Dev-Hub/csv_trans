#!/usr/bin/env python3
"""Bounded, synthetic live-provider smoke checks for csv-trans owners."""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import platform
from pathlib import Path
from urllib.parse import urlsplit


SYNTHETIC_TEXT = "Hello from the csv-trans owner live test."
WORK_PREFIX = "csv-trans-owner-live-"
PROVIDERS = (
    "echo",
    "google-free",
    "openai",
    "anthropic",
    "qwen",
    "deepseek",
    "openai-compatible",
)
HOSTED_PROVIDERS = {"openai", "anthropic", "qwen", "deepseek"}
OFFICIAL_ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}
GOOGLE_HOSTS = {"translate.googleapis.com", "translate.google.com"}

PROVIDER_ENVIRONMENT_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CSV_TRANS_OPENAI_API_KEY",
    "CSV_TRANS_OPENAI_BASE_URL",
    "CSV_TRANS_OPENAI_MODEL",
    "CSV_TRANS_OPENAI_CUSTOM_API_KEY",
    "CSV_TRANS_ANTHROPIC_API_KEY",
    "CSV_TRANS_ANTHROPIC_BASE_URL",
    "CSV_TRANS_ANTHROPIC_MODEL",
    "CSV_TRANS_ANTHROPIC_CUSTOM_API_KEY",
    "CSV_TRANS_QWEN_API_KEY",
    "CSV_TRANS_QWEN_BASE_URL",
    "CSV_TRANS_QWEN_MODEL",
    "CSV_TRANS_DEEPSEEK_API_KEY",
    "CSV_TRANS_DEEPSEEK_BASE_URL",
    "CSV_TRANS_DEEPSEEK_MODEL",
    "CSV_TRANS_OPENAI_COMPATIBLE_API_KEY",
    "CSV_TRANS_OPENAI_COMPATIBLE_BASE_URL",
    "CSV_TRANS_OPENAI_COMPATIBLE_MODEL",
)


class LiveCheckError(RuntimeError):
    """A concise live-check configuration or result failure."""


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send one fixed synthetic cell through one explicitly selected "
            "csv-trans provider. This can use quota or incur cost."
        )
    )
    parser.add_argument("provider", choices=PROVIDERS)
    parser.add_argument("--model", help="exact model ID enabled for this provider")
    parser.add_argument("--base-url", help="verified provider or local base URL")
    parser.add_argument(
        "--key-env",
        metavar="NAME",
        help="read the provider key from this existing environment variable",
    )
    parser.add_argument(
        "--prompt-for-key",
        action="store_true",
        help="prompt for an optional local-compatible server key",
    )
    parser.add_argument(
        "--approved-local-host",
        action="append",
        default=[],
        help="exact trusted LAN host for local-only mode (repeatable)",
    )
    parser.add_argument("--source-language", default="en")
    parser.add_argument("--target-language", default="fr")
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="retain the synthetic CSV, output, and report after success",
    )
    return parser.parse_args()


def validate_arguments(arguments: argparse.Namespace) -> tuple[str | None, str]:
    provider = arguments.provider
    if provider in {"echo", "google-free"}:
        if arguments.model or arguments.base_url:
            raise LiveCheckError(f"{provider} does not accept --model or --base-url")
        if arguments.key_env or arguments.prompt_for_key:
            raise LiveCheckError(f"{provider} does not use an API key")
    elif not arguments.model or not arguments.model.strip():
        raise LiveCheckError(f"{provider} requires --model")

    if provider in OFFICIAL_ENDPOINTS:
        official = OFFICIAL_ENDPOINTS[provider]
        if arguments.base_url and arguments.base_url.rstrip("/") != official.rstrip("/"):
            raise LiveCheckError(
                f"the {provider} owner check is restricted to {official}; "
                "use an OpenAI-compatible alias for a custom endpoint"
            )
        base_url: str | None = official
    elif provider in {"qwen", "deepseek", "openai-compatible"}:
        if not arguments.base_url or not arguments.base_url.strip():
            raise LiveCheckError(f"{provider} requires --base-url")
        base_url = arguments.base_url.strip()
        parsed = urlsplit(base_url)
        if not parsed.hostname:
            raise LiveCheckError("--base-url must contain a hostname")
    else:
        base_url = None

    if provider != "openai-compatible" and arguments.approved_local_host:
        raise LiveCheckError(
            "--approved-local-host is valid only for openai-compatible"
        )
    return base_url, provider


def obtain_key(arguments: argparse.Namespace) -> str | None:
    required = arguments.provider in HOSTED_PROVIDERS
    requested = required or arguments.prompt_for_key or arguments.key_env is not None
    if not requested:
        return None

    if arguments.key_env:
        key = os.environ.get(arguments.key_env, "")
        if not key.strip():
            raise LiveCheckError(
                f"environment variable {arguments.key_env!r} is missing or empty"
            )
        return key.strip()

    try:
        key = getpass.getpass(f"{arguments.provider} API key: ")
    except (EOFError, KeyboardInterrupt) as exc:
        raise LiveCheckError("API-key prompt was cancelled") from exc
    if not key.strip():
        raise LiveCheckError("an empty API key is not allowed")
    return key.strip()


def expected_hosts(provider: str, base_url: str | None) -> set[str]:
    if provider == "echo":
        return set()
    if provider == "google-free":
        return GOOGLE_HOSTS
    if base_url is None:
        raise LiveCheckError(f"{provider} is missing its validated base URL")
    host = urlsplit(base_url).hostname
    if not host:
        raise LiveCheckError("could not determine the selected recipient host")
    return {host.lower().rstrip(".")}


def child_environment(key: str | None, work_directory: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONOPTIMIZE",
        "PYTHONPATH",
        "PYTHONSAFEPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "VIRTUAL_ENV",
        "__PYVENV_LAUNCHER__",
    ):
        environment.pop(name, None)
    for name in PROVIDER_ENVIRONMENT_NAMES:
        environment.pop(name, None)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPYCACHEPREFIX"] = str(work_directory / "pycache")
    if key is not None:
        environment["CSV_TRANS_OWNER_LIVE_KEY"] = key
    return environment


def build_command(
    arguments: argparse.Namespace,
    *,
    repository: Path,
    work_directory: Path,
    base_url: str | None,
    key: str | None,
) -> tuple[list[str], Path, Path, Path]:
    source = work_directory / "input.csv"
    output = work_directory / "output.csv"
    report = work_directory / "report.json"
    with source.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows((("id", "text"), ("1", SYNTHETIC_TEXT)))

    command = [
        sys.executable,
        "-m",
        "csv_trans",
        "-f",
        str(source),
        "-sl",
        arguments.source_language,
        "-tl",
        arguments.target_language,
        "--provider",
        arguments.provider,
        "--columns",
        "text",
        "--batch-size",
        "1",
        "--timeout",
        "30",
        "--max-retries",
        "0",
        "--malformed-retries",
        "0",
        "--output",
        str(output),
        "--report",
        str(report),
        "--quiet",
    ]
    if arguments.model:
        command.extend(("--model", arguments.model))
    if base_url:
        command.extend(("--base-url", base_url))
    if key is not None:
        command.extend(("--api-key-env", "CSV_TRANS_OWNER_LIVE_KEY"))

    if arguments.provider == "echo":
        command.extend(("--privacy", "local-only"))
    elif arguments.provider == "google-free":
        command.extend(("--privacy", "public"))
    elif arguments.provider == "openai-compatible":
        command.extend(("--privacy", "local-only"))
        for host in arguments.approved_local_host:
            command.extend(("--approved-local-host", host))
    else:
        command.extend(
            (
                "--privacy",
                "restricted",
                "--allow-provider",
                arguments.provider,
            )
        )
    return command, source, output, report


def validate_publication(
    *,
    provider: str,
    source: Path,
    output: Path,
    report_path: Path,
    key: str | None,
    allowed_hosts: set[str],
    returncode: int,
) -> str:
    if not output.is_file() or not report_path.is_file():
        raise LiveCheckError("provider did not publish both output and report")

    with source.open(encoding="utf-8", newline="") as stream:
        source_rows = list(csv.reader(stream))
    with output.open(encoding="utf-8", newline="") as stream:
        output_rows = list(csv.reader(stream))
    if len(output_rows) != 2 or len(output_rows[1]) != 2 or not output_rows[1][1]:
        raise LiveCheckError(f"unexpected output CSV shape: {output_rows!r}")

    raw_report = report_path.read_text(encoding="utf-8")
    report = json.loads(raw_report)
    if SYNTHETIC_TEXT in raw_report:
        raise LiveCheckError("report leaked the synthetic source-cell text")
    translated_text = output_rows[1][1]
    if translated_text != SYNTHETIC_TEXT and translated_text in raw_report:
        raise LiveCheckError("report leaked the translated cell text")
    if key and key in raw_report:
        raise LiveCheckError("report leaked the provider key")
    if "authorization" in raw_report.lower():
        raise LiveCheckError("report unexpectedly contains an authorization field")

    attempts = [
        attempt
        for attempt in report.get("provider_attempts", [])
        if attempt.get("provider") == provider
    ]
    if not attempts:
        raise LiveCheckError(f"report is missing telemetry for {provider}")

    reported_hosts = {
        host.lower().rstrip(".")
        for attempt in attempts
        for endpoint in attempt.get("endpoints", [])
        if (host := urlsplit(endpoint).hostname)
    }
    if provider == "echo":
        if reported_hosts:
            raise LiveCheckError(f"Echo unexpectedly reported hosts: {reported_hosts}")
    elif not reported_hosts or not reported_hosts <= allowed_hosts:
        raise LiveCheckError(
            f"unexpected recipient hosts: {reported_hosts}; allowed: {allowed_hosts}"
        )

    if returncode == 0:
        if report.get("status") != "success":
            raise LiveCheckError(f"exit 0 report has status {report.get('status')!r}")
        if report.get("translated_cells") != 1 or report.get("failed_cells") != 0:
            raise LiveCheckError(f"unexpected success counters: {report!r}")
        # Verify data-integrity for every provider, not only echo: the unselected
        # id cell must be preserved byte-exact and the row shape unchanged.
        if len(output_rows) != len(source_rows) or len(output_rows[1]) != len(source_rows[1]):
            raise LiveCheckError("output row/field shape changed")
        if output_rows[1][0] != source_rows[1][0]:
            raise LiveCheckError("unselected id cell was not preserved")
        if provider == "echo" and output_rows != source_rows:
            raise LiveCheckError("Echo changed the synthetic CSV")
        return "success"

    if returncode == 2:
        if report.get("status") != "partial" or report.get("failed_cells", 0) < 1:
            raise LiveCheckError(f"exit 2 report is not a valid partial result: {report!r}")
        if output_rows[1][1] != SYNTHETIC_TEXT:
            raise LiveCheckError("partial publication did not preserve the source cell")
        return "partial"

    raise LiveCheckError(f"unexpected publication exit code {returncode}")


def safe_remove(work_directory: Path, temp_root: Path) -> None:
    resolved = work_directory.resolve()
    if resolved.parent != temp_root.resolve() or not resolved.name.startswith(WORK_PREFIX):
        raise LiveCheckError(f"refusing to remove unexpected path: {resolved}")
    shutil.rmtree(resolved)


def main() -> int:
    arguments = parse_arguments()
    repository = Path(__file__).resolve().parents[1]
    temp_root = Path(tempfile.gettempdir()).resolve()
    work_directory: Path | None = None

    try:
        if platform.python_implementation() != "CPython" or not (
            (3, 11) <= sys.version_info[:2] <= (3, 14)
        ):
            raise LiveCheckError("use CPython 3.11, 3.12, 3.13, or 3.14")
        if sys.flags.optimize:
            raise LiveCheckError("do not run the live check with python -O or -OO")
        base_url, provider = validate_arguments(arguments)
        key = obtain_key(arguments)
        work_directory = Path(
            tempfile.mkdtemp(prefix=WORK_PREFIX, dir=temp_root)
        ).resolve()
        if work_directory == repository or work_directory.is_relative_to(repository):
            safe_remove(work_directory, temp_root)
            work_directory = None
            raise LiveCheckError("the temporary directory must be outside the repository")

        environment = child_environment(key, work_directory)
        command, source, output, report = build_command(
            arguments,
            repository=repository,
            work_directory=work_directory,
            base_url=base_url,
            key=key,
        )
        hosts = expected_hosts(provider, base_url)

        print(f"Provider       : {provider}")
        print(f"Recipient hosts: {', '.join(sorted(hosts)) or 'none (offline Echo)'}")
        print(f"Synthetic text : {SYNTHETIC_TEXT}")
        print(f"Workspace      : {work_directory}")
        if provider not in {"echo", "google-free", "openai-compatible"}:
            print("This request can consume hosted-provider quota or incur cost.")

        completed = subprocess.run(
            command,
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
        if completed.returncode not in {0, 2}:
            message = (completed.stderr or completed.stdout).strip()
            raise LiveCheckError(
                f"provider command failed with exit {completed.returncode}: {message}"
            )

        status = validate_publication(
            provider=provider,
            source=source,
            output=output,
            report_path=report,
            key=key,
            allowed_hosts=hosts,
            returncode=completed.returncode,
        )
        if status == "partial":
            print(
                "SAFE PARTIAL RESULT: failed source cells were preserved, but this "
                "is not a passing provider check.",
                file=sys.stderr,
            )
            return 2

        if arguments.keep_workdir:
            print(f"Retained workspace (requested): {work_directory}")
            work_directory = None
        else:
            completed_work = work_directory
            safe_remove(completed_work, temp_root)
            work_directory = None
            print(f"Removed temporary workspace: {completed_work}")
        print("LIVE PROVIDER CHECK PASSED")
        return 0
    except Exception as exc:
        print(
            f"LIVE PROVIDER CHECK FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        if work_directory is not None and work_directory.exists():
            print(f"Retained workspace for inspection: {work_directory}")


if __name__ == "__main__":
    raise SystemExit(main())
