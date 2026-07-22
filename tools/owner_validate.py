#!/usr/bin/env python3
"""Cross-platform owner validation for csv-trans release candidates.

This script performs deterministic, non-provider validation in isolated
temporary environments. It never makes a translation-provider request.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Sequence


EXPECTED_VERSION = "2.0.0"
EXPECTED_TEST_COUNT = 190
SUPPORTED_PYTHON_MIN = (3, 11)
SUPPORTED_PYTHON_MAX = (3, 14)
WORK_PREFIX = "csv-trans-owner-validation-"
COMMAND_TIMEOUT_SECONDS = 300.0

REQUIRED_REPOSITORY_PATHS = (
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "pyproject.toml",
    "csv_trans",
    "tests",
)
ESSENTIAL_SDIST_ROOT_FILES = (
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "SECURITY.md",
    "TESTING.md",
    "pyproject.toml",
    "setup.py",
)

WINDOWS_ALLOWED_SKIPS = {
    "test_output_symlink_is_rejected_even_with_overwrite",
    "test_report_symlink_is_rejected_even_with_overwrite",
}


class ValidationError(RuntimeError):
    """A concise owner-facing validation failure."""


def _command_text(arguments: Sequence[str]) -> str:
    display = list(arguments)
    for index, argument in enumerate(display[:-1]):
        if argument == "-c" and len(display[index + 1]) > 120:
            display[index + 1] = "<embedded Python validation>"
    if os.name == "nt":
        return subprocess.list2cmdline(display)
    return shlex.join(display)


def run_checked(
    arguments: Sequence[str | Path],
    *,
    label: str,
    cwd: Path,
    env: dict[str, str],
) -> None:
    command = [str(argument) for argument in arguments]
    print(f"\n$ {_command_text(command)}", flush=True)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationError(
            f"{label} exceeded the {COMMAND_TIMEOUT_SECONDS:g}-second command timeout"
        ) from exc
    except OSError as exc:
        raise ValidationError(f"{label} could not start: {exc}") from exc
    if completed.returncode != 0:
        raise ValidationError(
            f"{label} failed with exit code {completed.returncode}: "
            f"{_command_text(command)}"
        )


def capture_checked(
    arguments: Sequence[str | Path],
    *,
    label: str,
    cwd: Path,
    env: dict[str, str],
    binary: bool = False,
) -> str | bytes:
    command = [str(argument) for argument in arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=not binary,
            encoding=None if binary else "utf-8",
            errors=None if binary else "replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationError(
            f"{label} exceeded the {COMMAND_TIMEOUT_SECONDS:g}-second command timeout"
        ) from exc
    except OSError as exc:
        raise ValidationError(f"{label} could not start: {exc}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise ValidationError(
            f"{label} failed with exit code {completed.returncode}: "
            f"{str(stderr).strip()}"
        )
    return completed.stdout


def stage(message: str) -> None:
    print(f"\n{'=' * 72}\n{message}\n{'=' * 72}", flush=True)


def validate_interpreter() -> None:
    version = sys.version_info[:2]
    if platform.python_implementation() != "CPython":
        raise ValidationError("use CPython 3.11, 3.12, 3.13, or 3.14")
    if not (SUPPORTED_PYTHON_MIN <= version <= SUPPORTED_PYTHON_MAX):
        raise ValidationError(
            f"unsupported Python {version[0]}.{version[1]}; "
            "use CPython 3.11 through 3.14"
        )
    if sys.flags.optimize:
        raise ValidationError("do not run owner validation with python -O or -OO")


def read_project_version(repository: Path) -> str:
    with (repository / "pyproject.toml").open("rb") as stream:
        document = tomllib.load(stream)
    try:
        version = document["project"]["version"]
    except (KeyError, TypeError) as exc:
        raise ValidationError("pyproject.toml does not contain project.version") from exc
    if version != EXPECTED_VERSION:
        raise ValidationError(
            f"expected project version {EXPECTED_VERSION}, found {version!r}"
        )
    return version


def clean_environment(work_directory: Path) -> dict[str, str]:
    environment = os.environ.copy()
    unsafe_names = {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "PIP_PREFIX",
        "PIP_ROOT",
        "PIP_TARGET",
        "PIP_USER",
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONOPTIMIZE",
        "PYTHONPATH",
        "PYTHONSAFEPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "VIRTUAL_ENV",
        "__PYVENV_LAUNCHER__",
    }
    for name in tuple(environment):
        if name in unsafe_names or name.startswith("CSV_TRANS_"):
            environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    environment["PIP_NO_CACHE_DIR"] = "1"
    environment["PIP_CACHE_DIR"] = str(work_directory / "pip-cache")
    environment["PYTHONPYCACHEPREFIX"] = str(work_directory / "pycache")
    return environment


def repository_file_manifest(
    repository: Path,
    *,
    git: str,
    env: dict[str, str],
) -> dict[str, str]:
    raw = capture_checked(
        [git, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        label="Git working-tree file listing",
        cwd=repository,
        env=env,
        binary=True,
    )
    if not isinstance(raw, bytes):
        raise ValidationError("Git returned an unexpected file-list representation")

    manifest: dict[str, str] = {}
    for encoded_name in raw.split(b"\0"):
        if not encoded_name:
            continue
        name = os.fsdecode(encoded_name)
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationError(f"Git returned an unsafe path: {name!r}")
        source = repository / relative
        if not source.exists() and not source.is_symlink():
            # A tracked deletion correctly represents the current working tree.
            continue
        if source.is_symlink():
            raise ValidationError(
                f"source snapshots reject symbolic links: {relative.as_posix()}"
            )
        if not source.is_file():
            raise ValidationError(
                f"source snapshot entry is not a regular file: {relative.as_posix()}"
            )
        resolved = source.resolve()
        if not resolved.is_relative_to(repository):
            raise ValidationError(f"source path escapes the repository: {relative}")
        normalized = relative.as_posix()
        if normalized in manifest:
            raise ValidationError(f"duplicate source path: {normalized}")
        manifest[normalized] = sha256(source)

    if not manifest:
        raise ValidationError("Git returned an empty working-tree snapshot")
    return dict(sorted(manifest.items()))


def create_source_snapshot(
    repository: Path,
    destination: Path,
    manifest: dict[str, str],
) -> None:
    destination.mkdir(parents=True)
    for relative_name, expected_digest in manifest.items():
        relative = Path(relative_name)
        source = repository / relative
        target = destination / relative
        if target.exists() or target.is_symlink():
            raise ValidationError(f"snapshot path collision: {relative_name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        actual_digest = sha256(target)
        if actual_digest != expected_digest:
            raise ValidationError(
                f"source changed while snapshotting: {relative_name}"
            )


def venv_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def venv_command(environment: Path, name: str) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / f"{name}.exe"
    return environment / "bin" / name


def create_venv(
    destination: Path,
    *,
    base_python: Path,
    cwd: Path,
    env: dict[str, str],
    label: str,
) -> Path:
    run_checked(
        [base_python, "-m", "venv", destination],
        label=label,
        cwd=cwd,
        env=env,
    )
    python = venv_python(destination)
    if not python.is_file():
        raise ValidationError(f"{label} did not create {python}")
    return python


def pip_install(
    python: Path,
    packages: Sequence[str | Path],
    *,
    label: str,
    cwd: Path,
    env: dict[str, str],
    wheelhouse: Path | None = None,
    no_deps: bool = False,
    no_build_isolation: bool = False,
    no_index: bool = False,
) -> None:
    command: list[str | Path] = [python, "-m", "pip", "install", "--no-user"]
    if no_index or wheelhouse is not None:
        command.append("--no-index")
    if wheelhouse is not None:
        command.extend(("--find-links", wheelhouse))
    if no_deps:
        command.append("--no-deps")
    if no_build_isolation:
        command.append("--no-build-isolation")
    command.extend(packages)
    run_checked(command, label=label, cwd=cwd, env=env)


TEST_RUNNER = textwrap.dedent(
    f"""
    import sys
    import unittest

    allowed_windows_skips = {WINDOWS_ALLOWED_SKIPS!r}
    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    if result.testsRun < {EXPECTED_TEST_COUNT}:
        raise SystemExit(
            f"expected at least {EXPECTED_TEST_COUNT} tests, discovered {{result.testsRun}}"
        )

    if sys.platform == "win32":
        unexpected = []
        for test, reason in result.skipped:
            test_name = test.id().rsplit(".", 1)[-1]
            if test_name not in allowed_windows_skips or "symlink" not in reason.lower():
                unexpected.append((test.id(), reason))
        if unexpected or len(result.skipped) > len(allowed_windows_skips):
            raise SystemExit(f"unexpected Windows skips: {{unexpected or result.skipped}}")
    elif result.skipped:
        raise SystemExit(f"non-Windows validation requires zero skips: {{result.skipped}}")

    print(
        f"SOURCE TESTS PASSED: {{result.testsRun}} tests, "
        f"{{len(result.skipped)}} platform skips",
        flush=True,
    )
    """
)


def install_build_tools(
    python: Path,
    *,
    snapshot: Path,
    env: dict[str, str],
    wheelhouse: Path | None,
) -> None:
    pip_install(
        python,
        ("setuptools==83.0.0", "build==1.5.0"),
        label="build-tool installation",
        cwd=snapshot,
        env=env,
        wheelhouse=wheelhouse,
    )
    location_check = textwrap.dedent(
        """
        import build
        import setuptools
        import sys
        from pathlib import Path

        prefix = Path(sys.prefix).resolve()
        for module in (build, setuptools):
            location = Path(module.__file__).resolve()
            if not location.is_relative_to(prefix):
                raise SystemExit(f"build tool escaped the validation venv: {location}")
        if setuptools.__version__ != "83.0.0":
            raise SystemExit(f"wrong setuptools version: {setuptools.__version__}")
        print("isolated build tools: PASS")
        """
    )
    run_checked(
        [python, "-c", location_check],
        label="isolated build-tool location check",
        cwd=snapshot,
        env=env,
    )


def find_artifacts(artifacts: Path) -> tuple[Path, Path]:
    wheels = sorted(artifacts.glob("*.whl"))
    sdists = sorted(artifacts.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValidationError(
            "expected exactly one wheel and one sdist, found "
            f"{len(wheels)} wheel(s) and {len(sdists)} sdist(s)"
        )
    return wheels[0], sdists[0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshot_group(
    snapshot: Path,
    directory: str,
    *,
    suffix: str | None = None,
) -> dict[str, str]:
    root = snapshot / directory
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or (suffix is not None and path.suffix != suffix):
            continue
        relative = path.relative_to(snapshot).as_posix()
        result[relative] = sha256(path)
    return result


def _validate_archive_names(label: str, names: Sequence[str]) -> None:
    forbidden_markers = (
        "/.git/",
        "/.github/",
        "/.agents/",
        "/.venv",
        "/__pycache__/",
        ".pyc",
        "/dist/",
        "/data/",
        "/tools/",
        "/owner_local_testing.md",
    )
    offenders: list[str] = []
    for raw_name in names:
        name = raw_name.replace("\\", "/")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValidationError(f"{label} contains an unsafe path: {raw_name!r}")
        normalized = "/" + name.lower().lstrip("/")
        if any(marker in normalized for marker in forbidden_markers):
            offenders.append(normalized)
    if offenders:
        raise ValidationError(
            f"{label} contains forbidden local residue: {offenders[:10]}"
        )


def inspect_artifacts(wheel: Path, sdist: Path, snapshot: Path) -> None:
    expected_runtime = _snapshot_group(snapshot, "csv_trans")
    expected_sdist = dict(expected_runtime)
    expected_sdist.update(_snapshot_group(snapshot, "tests", suffix=".py"))
    expected_sdist.update(_snapshot_group(snapshot, "docs", suffix=".md"))
    for name in ESSENTIAL_SDIST_ROOT_FILES:
        path = snapshot / name
        if not path.is_file():
            raise ValidationError(f"snapshot is missing required sdist file: {name}")
        expected_sdist[name] = sha256(path)

    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
        _validate_archive_names("wheel", wheel_names)
        package_names = {
            name
            for name in wheel_names
            if name.startswith("csv_trans/") and not name.endswith("/")
        }
        if package_names != set(expected_runtime):
            missing = sorted(set(expected_runtime) - package_names)
            extra = sorted(package_names - set(expected_runtime))
            raise ValidationError(
                f"wheel package file mismatch; missing={missing}, extra={extra}"
            )
        for name, expected_digest in expected_runtime.items():
            actual_digest = hashlib.sha256(archive.read(name)).hexdigest()
            if actual_digest != expected_digest:
                raise ValidationError(f"wheel content differs from source: {name}")

        metadata_names = [
            name for name in wheel_names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValidationError("wheel does not contain exactly one METADATA file")
        metadata = archive.read(metadata_names[0]).decode("utf-8")

    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        sdist_names = [member.name for member in members]
        _validate_archive_names("sdist", sdist_names)
        if any(member.issym() or member.islnk() for member in members):
            raise ValidationError("sdist unexpectedly contains a symbolic or hard link")
        roots = {PurePosixPath(name).parts[0] for name in sdist_names if name}
        if len(roots) != 1:
            raise ValidationError(f"sdist must contain exactly one root directory: {roots}")
        root = next(iter(roots))
        members_by_name = {member.name: member for member in members}
        for relative_name, expected_digest in expected_sdist.items():
            archive_name = f"{root}/{relative_name}"
            member = members_by_name.get(archive_name)
            if member is None or not member.isfile():
                raise ValidationError(f"sdist is missing source file: {relative_name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValidationError(f"could not read sdist file: {relative_name}")
            with extracted:
                actual_digest = hashlib.sha256(extracted.read()).hexdigest()
            if actual_digest != expected_digest:
                raise ValidationError(f"sdist content differs from source: {relative_name}")

    if not wheel.name.endswith("-py3-none-any.whl"):
        raise ValidationError(f"wheel is not platform-independent: {wheel.name}")
    if f"Version: {EXPECTED_VERSION}\n" not in metadata.replace("\r\n", "\n"):
        raise ValidationError("wheel METADATA contains the wrong version")
    if any(line.startswith("Requires-Dist:") for line in metadata.splitlines()):
        raise ValidationError("wheel unexpectedly declares a runtime dependency")


INSTALLED_METADATA_CHECK = textwrap.dedent(
    f"""
    import importlib.metadata as metadata
    from importlib.resources import files
    from pathlib import Path
    import csv_trans
    import sys

    repository = Path(sys.argv[1]).resolve()
    location = Path(csv_trans.__file__).resolve()
    if csv_trans.__version__ != {EXPECTED_VERSION!r}:
        raise SystemExit(f"wrong import version: {{csv_trans.__version__}}")
    if metadata.version("csv-trans") != {EXPECTED_VERSION!r}:
        raise SystemExit("wrong installed metadata version")
    if metadata.requires("csv-trans") or []:
        raise SystemExit("installed distribution has runtime requirements")
    if not files("csv_trans").joinpath("py.typed").is_file():
        raise SystemExit("installed distribution is missing py.typed")
    if location.is_relative_to(repository):
        raise SystemExit(f"source checkout shadowed installed package: {{location}}")
    print(f"installed metadata: PASS ({{location}})")
    """
)


def smoke_installed_distribution(
    *,
    label: str,
    environment: Path,
    python: Path,
    smoke_directory: Path,
    repository: Path,
    env: dict[str, str],
) -> None:
    smoke_directory.mkdir()
    cli = venv_command(environment, "csv-trans")
    legacy_cli = venv_command(environment, "csv_trans")
    if not cli.is_file() or not legacy_cli.is_file():
        raise ValidationError(f"{label} did not install both console commands")

    run_checked(
        [python, "-m", "pip", "check"],
        label=f"{label} pip check",
        cwd=smoke_directory,
        env=env,
    )
    run_checked(
        [python, "-c", INSTALLED_METADATA_CHECK, repository],
        label=f"{label} metadata check",
        cwd=smoke_directory,
        env=env,
    )
    run_checked(
        [cli, "--version"],
        label=f"{label} csv-trans entry point",
        cwd=smoke_directory,
        env=env,
    )
    run_checked(
        [legacy_cli, "--version"],
        label=f"{label} csv_trans compatibility entry point",
        cwd=smoke_directory,
        env=env,
    )
    run_checked(
        [python, "-m", "csv_trans", "--version"],
        label=f"{label} module entry point",
        cwd=smoke_directory,
        env=env,
    )

    source = smoke_directory / "input.csv"
    output = smoke_directory / "output.csv"
    report_path = smoke_directory / "report.json"
    with source.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows((("id", "text"), ("1", "hello")))

    run_checked(
        [
            cli,
            "-f",
            source,
            "-sl",
            "en",
            "-tl",
            "fr",
            "--provider",
            "echo",
            "--columns",
            "text",
            "--output",
            output,
            "--report",
            report_path,
            "--privacy",
            "local-only",
            "--quiet",
        ],
        label=f"{label} installed Echo CLI smoke",
        cwd=smoke_directory,
        env=env,
    )

    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    raw_report = report_path.read_text(encoding="utf-8")
    report = json.loads(raw_report)
    if rows != [["id", "text"], ["1", "hello"]]:
        raise ValidationError(f"{label} Echo smoke changed CSV content: {rows!r}")
    if report["status"] != "success" or report["failed_cells"] != 0:
        raise ValidationError(f"{label} Echo smoke reported failure: {report!r}")
    if not any(
        attempt["provider"] == "echo" for attempt in report["provider_attempts"]
    ):
        raise ValidationError(f"{label} report is missing Echo telemetry")
    if "hello" in raw_report:
        raise ValidationError(f"{label} report leaked source-cell text")
    print(f"{label.upper()} INSTALL AND ECHO SMOKE: PASS")


def repository_status(
    git: str,
    repository: Path,
    env: dict[str, str],
) -> bytes:
    value = capture_checked(
        [git, "status", "--porcelain=v1", "-z"],
        label="git status",
        cwd=repository,
        env=env,
        binary=True,
    )
    if not isinstance(value, bytes):
        raise ValidationError("git status returned an unexpected representation")
    return value


def validate_repository_identity(
    git: str,
    repository: Path,
    env: dict[str, str],
) -> None:
    for relative in REQUIRED_REPOSITORY_PATHS:
        if not (repository / relative).exists():
            raise ValidationError(f"required repository path is missing: {relative}")
    raw_root = capture_checked(
        [git, "rev-parse", "--show-toplevel"],
        label="Git repository-root check",
        cwd=repository,
        env=env,
    )
    if not isinstance(raw_root, str):
        raise ValidationError("Git returned an unexpected repository-root value")
    git_root = Path(raw_root.strip()).resolve()
    if git_root != repository.resolve():
        raise ValidationError(
            f"tool repository {repository} differs from Git root {git_root}"
        )


def safe_remove_workdir(work_directory: Path, temp_root: Path) -> None:
    resolved = work_directory.resolve()
    if (
        resolved.parent != temp_root.resolve()
        or not resolved.name.startswith(WORK_PREFIX)
    ):
        raise ValidationError(f"refusing to remove unexpected path: {resolved}")
    shutil.rmtree(resolved)


def positive_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not 1 <= timeout <= 3600:
        raise argparse.ArgumentTypeError("timeout must be between 1 and 3600 seconds")
    return timeout


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic csv-trans owner validation on Windows or Linux. "
            "No live translation provider is configured."
        )
    )
    parser.add_argument(
        "--tests-only",
        action="store_true",
        help="run the clean source suite but skip build and install validation",
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="retain the temporary environments and artifacts after success",
    )
    parser.add_argument(
        "--wheelhouse",
        type=Path,
        help=(
            "install build tools from this wheel directory with --no-index; "
            "include transitive dependencies"
        ),
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        help=(
            "existing directory outside the checkout for the unique temporary "
            "workspace; useful when the system temp directory is mounted noexec"
        ),
    )
    parser.add_argument(
        "--command-timeout",
        type=positive_timeout,
        default=COMMAND_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="maximum duration of each child command (default: 300)",
    )
    return parser.parse_args()


def main() -> int:
    global COMMAND_TIMEOUT_SECONDS
    arguments = parse_arguments()
    COMMAND_TIMEOUT_SECONDS = arguments.command_timeout
    repository = Path(__file__).resolve().parents[1]
    if arguments.work_root is None:
        temp_root = Path(tempfile.gettempdir()).resolve()
    else:
        temp_root = arguments.work_root.expanduser().resolve()
    work_directory: Path | None = None

    try:
        validate_interpreter()
        read_project_version(repository)
        git = shutil.which("git")
        if git is None:
            raise ValidationError("Git is required but was not found on PATH")
        if not temp_root.is_dir():
            raise ValidationError(f"work root is not an existing directory: {temp_root}")
        if temp_root == repository or temp_root.is_relative_to(repository):
            raise ValidationError("--work-root and the system temp directory must be outside the checkout")
        if arguments.wheelhouse is not None:
            arguments.wheelhouse = arguments.wheelhouse.expanduser().resolve()
            if not arguments.wheelhouse.is_dir():
                raise ValidationError(
                    f"wheelhouse is not a directory: {arguments.wheelhouse}"
                )
            if arguments.wheelhouse.is_relative_to(repository):
                raise ValidationError("place --wheelhouse outside the repository")

        work_directory = Path(
            tempfile.mkdtemp(prefix=WORK_PREFIX, dir=temp_root)
        ).resolve()
        if work_directory == repository or work_directory.is_relative_to(repository):
            safe_remove_workdir(work_directory, temp_root)
            work_directory = None
            raise ValidationError(
                "the operating-system temporary directory is inside the repository; "
                "set TEMP/TMPDIR to a directory outside the checkout"
            )

        environment = clean_environment(work_directory)
        validate_repository_identity(git, repository, environment)
        initial_status = repository_status(git, repository, environment)
        initial_manifest = repository_file_manifest(
            repository,
            git=git,
            env=environment,
        )

        print("csv-trans owner validation")
        print(f"Repository : {repository}")
        print(f"Platform   : {platform.platform()}")
        print(f"Python     : {sys.executable} ({platform.python_version()})")
        print(f"Workspace  : {work_directory}")
        print("Providers  : not configured; tests use fakes, loopback, and Echo")

        stage("1. Create a clean source snapshot and Python environment")
        snapshot = work_directory / "source-snapshot"
        create_source_snapshot(repository, snapshot, initial_manifest)
        source_venv = work_directory / "source-venv"
        source_python = create_venv(
            source_venv,
            base_python=Path(sys.executable),
            cwd=snapshot,
            env=environment,
            label="source virtual environment creation",
        )

        stage("2. Run the complete deterministic source test suite")
        run_checked(
            [source_python, "-B", "-c", TEST_RUNNER],
            label="source test suite",
            cwd=snapshot,
            env=environment,
        )
        run_checked(
            [
                source_python,
                "-c",
                (
                    "import csv_trans; "
                    "actual = csv_trans.__version__; "
                    f"expected = {EXPECTED_VERSION!r}; "
                    "print(actual); "
                    "raise SystemExit(0 if actual == expected else "
                    "f'wrong source version: {actual!r}')"
                ),
            ],
            label="source import and version check",
            cwd=snapshot,
            env=environment,
        )
        run_checked(
            [source_python, "-m", "csv_trans", "--version"],
            label="source module CLI check",
            cwd=snapshot,
            env=environment,
        )
        run_checked(
            [source_python, "-m", "compileall", "-q", "csv_trans", "tests"],
            label="source byte-compilation check",
            cwd=snapshot,
            env=environment,
        )
        run_checked(
            [git, "diff", "--check"],
            label="Git whitespace check",
            cwd=repository,
            env=environment,
        )

        if not arguments.tests_only:
            stage("3. Install isolated build tools and build both distributions")
            install_build_tools(
                source_python,
                snapshot=snapshot,
                env=environment,
                wheelhouse=arguments.wheelhouse,
            )
            artifacts = work_directory / "artifacts"
            artifacts.mkdir()
            run_checked(
                [
                    source_python,
                    "-m",
                    "build",
                    "--no-isolation",
                    "--outdir",
                    artifacts,
                    snapshot,
                ],
                label="wheel and sdist build",
                cwd=snapshot,
                env=environment,
            )
            wheel, sdist = find_artifacts(artifacts)
            inspect_artifacts(wheel, sdist, snapshot)
            print(f"Wheel SHA256: {sha256(wheel)}  {wheel.name}")
            print(f"Sdist SHA256: {sha256(sdist)}  {sdist.name}")
            print("ARCHIVE CONTENT: PASS")

            stage("4. Install and smoke-test the wheel outside the checkout")
            wheel_venv = work_directory / "wheel-venv"
            wheel_python = create_venv(
                wheel_venv,
                base_python=Path(sys.executable),
                cwd=work_directory,
                env=environment,
                label="wheel virtual environment creation",
            )
            pip_install(
                wheel_python,
                (wheel,),
                label="wheel installation",
                cwd=work_directory,
                env=environment,
                no_deps=True,
                no_index=True,
            )
            smoke_installed_distribution(
                label="wheel",
                environment=wheel_venv,
                python=wheel_python,
                smoke_directory=work_directory / "wheel-smoke",
                repository=repository,
                env=environment,
            )

            stage("5. Install and smoke-test the sdist outside the checkout")
            sdist_venv = work_directory / "sdist-venv"
            sdist_python = create_venv(
                sdist_venv,
                base_python=Path(sys.executable),
                cwd=work_directory,
                env=environment,
                label="sdist virtual environment creation",
            )
            pip_install(
                sdist_python,
                ("setuptools==83.0.0",),
                label="sdist build-backend installation",
                cwd=work_directory,
                env=environment,
                wheelhouse=arguments.wheelhouse,
            )
            pip_install(
                sdist_python,
                (sdist,),
                label="sdist installation",
                cwd=work_directory,
                env=environment,
                no_deps=True,
                no_build_isolation=True,
                no_index=True,
            )
            smoke_installed_distribution(
                label="sdist",
                environment=sdist_venv,
                python=sdist_python,
                smoke_directory=work_directory / "sdist-smoke",
                repository=repository,
                env=environment,
            )

        stage("6. Confirm validation did not change the repository")
        final_status = repository_status(git, repository, environment)
        if final_status != initial_status:
            before = initial_status.decode("utf-8", errors="replace")
            after = final_status.decode("utf-8", errors="replace")
            raise ValidationError(
                "repository status changed during validation\n"
                f"before: {before!r}\nafter:  {after!r}"
            )
        final_manifest = repository_file_manifest(
            repository,
            git=git,
            env=environment,
        )
        if final_manifest != initial_manifest:
            changed = sorted(set(initial_manifest) ^ set(final_manifest))
            changed.extend(
                name
                for name in set(initial_manifest) & set(final_manifest)
                if initial_manifest[name] != final_manifest[name]
            )
            raise ValidationError(
                f"repository file contents changed during validation: {sorted(set(changed))}"
            )
        run_checked(
            [git, "diff", "--check"],
            label="final Git whitespace check",
            cwd=repository,
            env=environment,
        )
        print("REPOSITORY HYGIENE: PASS")

        if arguments.keep_workdir:
            print(f"Retained temporary workspace (requested): {work_directory}")
            work_directory = None
        else:
            completed_work = work_directory
            safe_remove_workdir(completed_work, temp_root)
            work_directory = None
            print(f"Removed temporary workspace: {completed_work}")

        if arguments.tests_only:
            print("\nSOURCE VALIDATION PASSED")
        else:
            print("\nFULL LOCAL VALIDATION PASSED")
        return 0
    except KeyboardInterrupt:
        print("\nVALIDATION INTERRUPTED", file=sys.stderr)
        return 130
    except Exception as exc:
        print(
            f"\nVALIDATION FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        if work_directory is not None and work_directory.exists():
            print(f"Retained temporary workspace (for diagnosis): {work_directory}")


if __name__ == "__main__":
    raise SystemExit(main())
