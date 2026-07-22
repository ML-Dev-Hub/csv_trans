"""Public configuration and result models for :mod:`csv_trans`.

The models in this module deliberately contain no provider-specific types.  A
caller can therefore inspect a completed run, or construct a configuration,
without importing an SDK or making a network connection.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import codecs
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Sequence

from .csvio import fsync_parent_directory


def _report_destination(path: str | Path) -> Path:
    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return expanded.parent.resolve() / expanded.name


class PrivacyMode(str, Enum):
    """Network boundary applied before any source text reaches a provider."""

    PUBLIC = "public"
    RESTRICTED = "restricted"
    LOCAL_ONLY = "local-only"


class RunStatus(str, Enum):
    """Final state of a translation run."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DRY_RUN = "dry-run"


@dataclass(slots=True, frozen=True)
class ProgressEvent:
    """A small, content-free progress notification."""

    phase: str
    rows_processed: int = 0
    cells_translated: int = 0
    cells_failed: int = 0


@dataclass(slots=True)
class TranslationConfig:
    """Configuration for :func:`csv_trans.translate_csv`.

    ``provider`` and ``fallback_providers`` accept objects implementing the
    lightweight provider protocol from :mod:`csv_trans.providers`.  When no
    provider is supplied, the built-in no-key Google web adapter is used.
    """

    source_language: str
    target_language: str
    provider: Any | None = None
    fallback_providers: Sequence[Any] = field(default_factory=tuple)
    columns: Sequence[str | int] | None = None
    translate_headers: bool = False
    encoding: str | None = None
    output_encoding: str = "utf-8"
    delimiter: str | None = None
    overwrite: bool = False
    privacy: PrivacyMode | str = PrivacyMode.PUBLIC
    allowed_providers: Sequence[str] = field(default_factory=tuple)
    approved_local_hosts: Sequence[str] = field(default_factory=tuple)
    sample_rows: int = 100
    batch_size: int = 20
    max_chars: int = 3_500
    min_adaptive_chars: int = 32
    max_field_chars: int = 64 * 1024 * 1024
    max_row_chars: int = 128 * 1024 * 1024
    max_columns: int = 10_000
    max_sample_chars: int = 16 * 1024 * 1024
    max_pending_chars: int = 64 * 1024 * 1024
    max_failure_details: int = 10_000
    max_retries: int = 2
    malformed_retries: int = 1
    backoff_base: float = 0.5
    max_backoff: float = 8.0
    jitter: float = 0.1
    cache_size: int = 2_048
    preserve_placeholders: bool = True
    allow_empty_translations: bool = False
    report_path: str | Path | None = None
    snapshot_directory: str | Path | None = None
    dry_run: bool = False
    progress_callback: Callable[[ProgressEvent], None] | None = field(
        default=None, repr=False, compare=False
    )
    cancellation_check: Callable[[], bool] | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.source_language, str):
            raise ValueError("source_language must be a string")
        if not isinstance(self.target_language, str):
            raise ValueError("target_language must be a string")
        self.source_language = self.source_language.strip()
        self.target_language = self.target_language.strip()
        if not self.source_language:
            raise ValueError("source_language must not be empty")
        if not self.target_language:
            raise ValueError("target_language must not be empty")
        if isinstance(self.privacy, str):
            try:
                self.privacy = PrivacyMode(self.privacy.lower())
            except ValueError as exc:
                choices = ", ".join(item.value for item in PrivacyMode)
                raise ValueError(f"privacy must be one of: {choices}") from exc
        elif not isinstance(self.privacy, PrivacyMode):
            raise ValueError("privacy must be a PrivacyMode or its string value")
        if self.delimiter is not None and (
            not isinstance(self.delimiter, str)
            or len(self.delimiter) != 1
            or self.delimiter in {"\r", "\n", "\0"}
        ):
            raise ValueError(
                "delimiter must be one non-newline, non-NUL character"
            )
        positive_integers = (
            "sample_rows",
            "batch_size",
            "max_chars",
            "min_adaptive_chars",
            "max_field_chars",
            "max_row_chars",
            "max_columns",
            "max_sample_chars",
            "max_pending_chars",
        )
        for name in positive_integers:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "max_retries",
            "malformed_retries",
            "cache_size",
            "max_failure_details",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in ("backoff_base", "max_backoff", "jitter"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} must be a finite non-negative number")
        try:
            self.output_encoding = codecs.lookup(self.output_encoding).name
        except (LookupError, TypeError) as exc:
            raise ValueError(f"unknown output_encoding: {self.output_encoding}") from exc
        if self.encoding is not None:
            # Validate symmetrically with output_encoding, but preserve the
            # detect-mode inputs that csvio.detect_encoding interprets: the
            # "auto"/"detect" sentinels and a falsy/empty value all mean detect.
            if not isinstance(self.encoding, str):
                raise ValueError("encoding must be a string or None")
            if self.encoding and self.encoding.lower() not in {"auto", "detect"}:
                try:
                    codecs.lookup(self.encoding)
                except LookupError as exc:
                    raise ValueError(f"unknown encoding: {self.encoding}") from exc
        if self.snapshot_directory is not None:
            try:
                self.snapshot_directory = Path(self.snapshot_directory).expanduser()
            except TypeError as exc:
                raise ValueError("snapshot_directory must be a filesystem path") from exc
        if isinstance(self.fallback_providers, (str, bytes)):
            raise ValueError("fallback_providers must be a sequence of provider objects")
        self.fallback_providers = tuple(self.fallback_providers)
        self.allowed_providers = _string_sequence(
            self.allowed_providers, name="allowed_providers"
        )
        self.approved_local_hosts = _string_sequence(
            self.approved_local_hosts, name="approved_local_hosts"
        )
        if self.columns is not None:
            items = (
                (self.columns,)
                if isinstance(self.columns, str)
                else tuple(self.columns)
            )
            for item in items:
                # bool is an int subclass; reject it so columns=[True] cannot be
                # read as "select column 1". Validate eagerly for a consistent
                # fail-fast ValueError instead of a late TypeError at resolution.
                if isinstance(item, bool) or not isinstance(item, (str, int)):
                    raise ValueError(
                        "columns must contain column names or zero-based integer indexes"
                    )
                if isinstance(item, str) and not item.strip():
                    raise ValueError("columns must not contain empty names")
            self.columns = items
        for name in ("progress_callback", "cancellation_check"):
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise ValueError(f"{name} must be callable or None")


def _string_sequence(value: Sequence[str], *, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    else:
        try:
            values = tuple(value)
        except TypeError as exc:
            raise ValueError(f"{name} must be a sequence of strings") from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{name} must contain only non-empty strings")
    return values


@dataclass(slots=True, frozen=True)
class ColumnSelection:
    """Why a CSV column was or was not selected."""

    index: int
    name: str
    selected: bool
    reason: str


@dataclass(slots=True)
class ProviderAttempt:
    """Aggregate, content-free provider telemetry."""

    provider: str
    chain_index: int = 0
    endpoint: str | None = None
    endpoints: tuple[str, ...] = field(default_factory=tuple)
    batches: int = 0
    items: int = 0
    retries: int = 0
    failures: int = 0


@dataclass(slots=True, frozen=True)
class TranslationFailure:
    """A final cell failure.  Source cell contents are intentionally omitted."""

    row: int
    column_index: int
    column_name: str
    item_id: str
    category: str
    provider: str
    endpoint: str | None
    attempts: int
    message: str
    original_preserved: bool = True


@dataclass(slots=True)
class TranslationResult:
    """Machine-readable outcome returned by every translation run."""

    input_path: Path
    output_path: Path | None
    source_language: str
    target_language: str
    privacy: PrivacyMode = PrivacyMode.PUBLIC
    status: RunStatus = RunStatus.SUCCESS
    input_encoding: str = ""
    output_encoding: str = "utf-8"
    dialect: dict[str, Any] = field(default_factory=dict)
    row_count: int = 0
    total_cells: int = 0
    selected_cells: int = 0
    translated_cells: int = 0
    cached_cells: int = 0
    skipped_cells: int = 0
    failed_cells: int = 0
    omitted_failure_count: int = 0
    selected_columns: list[ColumnSelection] = field(default_factory=list)
    failures: list[TranslationFailure] = field(default_factory=list)
    provider_attempts: list[ProviderAttempt] = field(default_factory=list)
    retries: int = 0
    fallbacks: int = 0
    warnings: list[str] = field(default_factory=list)
    report_path: Path | None = None

    @property
    def succeeded(self) -> bool:
        """Whether the run completed without a final cell failure."""

        return self.status in {RunStatus.SUCCESS, RunStatus.DRY_RUN}

    def to_dict(self, *, include_column_names: bool = False) -> dict[str, Any]:
        """Return a content-free JSON representation.

        Header names remain available on the in-memory result, but serialized
        reports omit them by default because a CSV can use sensitive text as a
        header. Callers may opt in only when their reporting boundary permits.
        """

        data = asdict(self)
        data["input_path"] = str(self.input_path)
        data["output_path"] = str(self.output_path) if self.output_path else None
        data["report_path"] = str(self.report_path) if self.report_path else None
        data["status"] = self.status.value
        data["privacy"] = self.privacy.value
        for attempt in data["provider_attempts"]:
            attempt["endpoints"] = list(attempt["endpoints"])
        if not include_column_names:
            for column in data["selected_columns"]:
                column["name"] = None
            for failure in data["failures"]:
                failure["column_name"] = None
        return data

    def write_json(
        self,
        path: str | Path,
        *,
        overwrite: bool = False,
        include_column_names: bool = False,
    ) -> Path:
        """Write this result atomically as UTF-8 JSON."""

        destination = _report_destination(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            raise FileExistsError(
                f"report path must not be a symbolic link: {destination}"
            )
        if destination.exists() and not destination.is_file():
            raise FileExistsError(f"report path is not a regular file: {destination}")
        data = self.to_dict(include_column_names=include_column_names)
        # Serialize the destination that this call is about to publish without
        # mutating the in-memory result prematurely. If publication fails, the
        # caller's previous report_path must remain truthful.
        data["report_path"] = str(destination)
        payload = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        )
        temporary = Path(handle.name)
        primary_error: BaseException | None = None
        published = False
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if overwrite:
                os.replace(temporary, destination)
            elif os.name == "nt":
                os.rename(temporary, destination)
            else:
                os.link(temporary, destination)
            self.report_path = destination
            published = True
            # Best-effort durability for the just-published entry (shared helper).
            warning = fsync_parent_directory(destination)
            if warning is not None and warning not in self.warnings:
                self.warnings.append(warning)
        except FileExistsError as exc:
            failure = FileExistsError(
                f"report already exists: {destination}; pass overwrite=True to replace it"
            )
            primary_error = failure
            raise failure from exc
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_error:
                if primary_error is not None:
                    primary_error.add_note(
                        f"csv-trans report staging cleanup also failed: {cleanup_error}"
                    )
                elif published:
                    warning = "temporary report staging file could not be removed"
                    if warning not in self.warnings:
                        self.warnings.append(warning)
                else:  # Defensive: no known publication or primary failure.
                    raise
        return destination


__all__ = [
    "ColumnSelection",
    "PrivacyMode",
    "ProgressEvent",
    "ProviderAttempt",
    "RunStatus",
    "TranslationConfig",
    "TranslationFailure",
    "TranslationResult",
]
