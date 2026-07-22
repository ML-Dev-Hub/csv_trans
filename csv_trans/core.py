"""Streaming CSV translation orchestration and bounded failure recovery."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
import hashlib
from itertools import chain, islice
import os
import random
from pathlib import Path
import stat
import tempfile
import time
from typing import Any, Iterable, Iterator, Sequence
from urllib.parse import urlsplit

from .chunking import TextSegment, reconstruct_segments, segment_text
from .csvio import (
    AtomicCsvWriter,
    CsvInputError,
    OutputExistsError,
    default_output_path,
    inspect_csv,
    open_rows,
    resolve_destination_path,
    validate_output_path,
)
from .models import (
    PrivacyMode,
    ProgressEvent,
    ProviderAttempt,
    RunStatus,
    TranslationConfig,
    TranslationFailure,
    TranslationResult,
)
from .selection import resolve_columns, should_translate_cell


class PrivacyViolation(ValueError):
    """A configured provider would cross the selected network boundary."""


class ProviderResponseError(RuntimeError):
    """A provider returned data that cannot be mapped back to input items."""

    category = "malformed"
    retryable = True


class ProviderOutputEncodingError(RuntimeError):
    """A translation cannot be represented in the requested output codec."""

    category = "output_encoding"
    retryable = False


class _Cancelled(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class _Item:
    id: str
    text: str


@dataclass(slots=True)
class _ItemFailure:
    category: str
    provider: str
    endpoint: str | None
    attempts: int
    message: str


@dataclass(slots=True)
class _CellPlan:
    row_number: int
    column_index: int
    column_name: str
    original: str
    segments: list[TextSegment]
    translations: dict[int, str] = field(default_factory=dict)
    cached_segments: set[int] = field(default_factory=set)
    failures: list[_ItemFailure] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"r{self.row_number}c{self.column_index}"


@dataclass(slots=True)
class _ReportPublication:
    """A report published before its CSV, with enough state to undo it."""

    result: TranslationResult
    path: Path | None = None
    backup: Path | None = None
    published_identity: tuple[int, int, int, int, int] | None = None
    active: bool = True

    def commit(self) -> None:
        """Forget the rollback copy after the CSV commit succeeds."""

        if not self.active:
            return
        if self.backup is not None:
            self.backup.unlink(missing_ok=True)
            self.backup = None
        self.active = False

    def rollback(self) -> None:
        """Remove our report or restore the report it replaced."""

        if not self.active:
            return
        try:
            if self.path is None or self.published_identity is None:
                return
            current = _report_file_identity(self.path)
            if current is None:
                if self.backup is not None:
                    os.replace(self.backup, self.path)
                    self.backup = None
            elif current == self.published_identity:
                if self.backup is not None:
                    os.replace(self.backup, self.path)
                    self.backup = None
                else:
                    self.path.unlink()
            else:
                raise OSError(
                    "report destination changed after publication; "
                    "the prior report was left in its private rollback file"
                )
        finally:
            self.result.report_path = None
            self.active = False


class _TranslationCache:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._values: OrderedDict[tuple[str, str, str], str] = OrderedDict()

    def get(self, key: tuple[str, str, str]) -> str | None:
        if key not in self._values:
            return None
        value = self._values.pop(key)
        self._values[key] = value
        return value

    def put(self, key: tuple[str, str, str], value: str) -> None:
        if self.capacity == 0:
            return
        self._values.pop(key, None)
        self._values[key] = value
        while len(self._values) > self.capacity:
            self._values.popitem(last=False)


def translate_csv(
    input_path: str | Path,
    source_language: str | TranslationConfig,
    target_language: str | None = None,
    *,
    output_path: str | Path | None = None,
    config: TranslationConfig | None = None,
    **options: Any,
) -> TranslationResult:
    """Translate selected CSV fields and return a structured result.

    The input is sampled only for column selection and then processed in bounded
    row groups.  Output is published atomically after the final row is written.
    Failed cells retain their complete original value and appear in ``failures``.
    """

    normalized = _normalize_config(
        source_language, target_language, config=config, options=options
    )
    return _translate_csv_config(input_path, normalized, output_path=output_path)


def _translate_csv_config(
    input_path: str | Path,
    config: TranslationConfig,
    *,
    output_path: str | Path | None,
) -> TranslationResult:
    source = Path(input_path).expanduser().resolve()
    destination = resolve_destination_path(output_path) if output_path else default_output_path(
        source, config.target_language
    )

    _validate_explicit_report_path(config, source, destination)
    providers = _provider_chain(config)
    if not config.dry_run:
        _enforce_privacy(providers, config)
        destination = validate_output_path(source, destination, overwrite=config.overwrite)

    with _source_snapshot(
        source, directory=config.snapshot_directory
    ) as (snapshot, source_digest, source_metadata, snapshot_warnings):
        inspection = inspect_csv(
            snapshot, encoding=config.encoding, delimiter=config.delimiter
        )
        _assert_source_metadata_unchanged(source, source_metadata)
        result = _translate_csv_snapshot_config(
            source,
            destination,
            config,
            providers,
            inspection,
            source_digest,
            source_metadata,
        )
    result.warnings.extend(snapshot_warnings)
    return result


def _translate_csv_snapshot_config(
    source: Path,
    destination: Path,
    config: TranslationConfig,
    providers: Sequence[Any],
    inspection: Any,
    source_digest: str,
    source_metadata: tuple[int, int, int, int, int],
) -> TranslationResult:
    result = TranslationResult(
        input_path=source,
        output_path=None if config.dry_run else destination,
        source_language=config.source_language,
        target_language=config.target_language,
        privacy=config.privacy,
        input_encoding=inspection.encoding,
        output_encoding=config.output_encoding,
        dialect=inspection.format.to_dict(),
    )
    attempts: dict[tuple[int, int], ProviderAttempt] = {}
    cache = _TranslationCache(config.cache_size)

    with open_rows(inspection, max_field_chars=config.max_field_chars) as reader:
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise CsvInputError("input CSV does not contain a header row") from exc
        _validate_row_limits(headers, config, location="header")
        sample: list[list[str]] = []
        sample_chars = 0
        for sample_index in range(1, config.sample_rows + 1):
            try:
                row = next(reader)
            except StopIteration:
                break
            row_chars = _validate_row_limits(
                row, config, location=f"sample row {sample_index}"
            )
            sample.append(row)
            sample_chars += row_chars
            if sample_chars >= config.max_sample_chars:
                result.warnings.append(
                    "column-selection sampling stopped at max_sample_chars"
                )
                break
        selected_indexes, decisions = resolve_columns(headers, sample, config.columns)
        result.selected_columns = decisions
        sampled_headers = tuple(headers)

        _assert_source_metadata_unchanged(source, source_metadata)

        if config.dry_run:
            try:
                _measure_dry_run(
                    chain(sample, reader), selected_indexes, result, config
                )
                result.status = RunStatus.DRY_RUN
                result.warnings.append(
                    "dry run: no provider was contacted and no CSV was written"
                )
            except _Cancelled:
                result.status = RunStatus.CANCELLED
                result.warnings.append("dry run was cancelled; no CSV was written")

    if config.dry_run:
        # Do not publish even a dry-run report while a plaintext working copy
        # is still awaiting deletion.
        _remove_source_snapshot(inspection.path)
        publication = _finalize_report(result, config)
        publication.commit()
        return result

    # The atomic writer is deliberately the outer context.  This closes the
    # source reader before publishing the completed temporary file, which is
    # required for safe in-place replacement on Windows.
    publication = _ReportPublication(result)

    def validate_before_commit() -> None:
        _check_cancelled(config)
        _assert_source_unchanged(source, source_digest, source_metadata)

    atomic_writer = AtomicCsvWriter(
        destination,
        encoding=config.output_encoding,
        csv_format=inspection.format,
        overwrite=config.overwrite,
        before_commit=validate_before_commit,
    )
    try:
        with atomic_writer as writer:
            with open_rows(
                inspection, max_field_chars=config.max_field_chars
            ) as reader:
                try:
                    headers = next(reader)
                except StopIteration as exc:
                    raise CsvInputError("input CSV does not contain a header row") from exc
                _validate_row_limits(headers, config, location="header")
                _validate_output_row(headers, config.output_encoding, location="header")
                if tuple(headers) != sampled_headers:
                    raise CsvInputError(
                        "input CSV header changed between sampling and processing"
                    )
                _assert_source_metadata_unchanged(source, source_metadata)
                if config.translate_headers:
                    translated_headers = _process_rows(
                        [(0, headers)],
                        selected_indexes,
                        headers,
                        providers,
                        config,
                        result,
                        attempts,
                        cache,
                        count_total=True,
                    )[0][1]
                    _check_cancelled(config)
                    _assert_source_metadata_unchanged(source, source_metadata)
                    writer.writerow(translated_headers)
                else:
                    writer.writerow(headers)

                pending: list[tuple[int, list[str]]] = []
                pending_selected = 0
                pending_chars = 0
                for row_number, row in enumerate(reader, start=1):
                    _check_cancelled(config)
                    row_chars = _validate_row_limits(
                        row, config, location=f"row {row_number}"
                    )
                    _validate_output_row(
                        row, config.output_encoding, location=f"row {row_number}"
                    )
                    pending.append((row_number, row))
                    pending_chars += row_chars
                    pending_selected += sum(index < len(row) for index in selected_indexes)
                    if (
                        pending_selected >= config.batch_size
                        or len(pending) >= config.batch_size
                        or pending_chars >= config.max_pending_chars
                    ):
                        translated_rows = _process_rows(
                            pending,
                            selected_indexes,
                            headers,
                            providers,
                            config,
                            result,
                            attempts,
                            cache,
                            count_total=True,
                        )
                        _check_cancelled(config)
                        _assert_source_metadata_unchanged(source, source_metadata)
                        for _, translated_row in translated_rows:
                            writer.writerow(translated_row)
                        pending = []
                        pending_selected = 0
                        pending_chars = 0
                        _notify(config, result, "translating")
                if pending:
                    translated_rows = _process_rows(
                        pending,
                        selected_indexes,
                        headers,
                        providers,
                        config,
                        result,
                        attempts,
                        cache,
                        count_total=True,
                    )
                    _check_cancelled(config)
                    _assert_source_metadata_unchanged(source, source_metadata)
                    for _, translated_row in translated_rows:
                        writer.writerow(translated_row)
                    _notify(config, result, "translating")

            # The snapshot reader is closed. Remove its plaintext working copy
            # before either report or CSV is made visible.
            _remove_source_snapshot(inspection.path)
            _check_cancelled(config)
            result.provider_attempts = list(attempts.values())
            result.status = (
                RunStatus.PARTIAL if result.failed_cells else RunStatus.SUCCESS
            )
            if not selected_indexes:
                result.warnings.append(
                    "no text-like columns were selected; the CSV was copied unchanged"
                )
            if config.source_language.casefold() == config.target_language.casefold():
                result.warnings.append("source and target languages are identical")
            _notify(config, result, "complete")
            # Publish a requested/partial report before the CSV. If reporting
            # fails, the mixed-language output is never made visible.
            publication = _finalize_report(result, config)
            # AtomicCsvWriter now flushes and fsyncs its staging file, then runs
            # the cancellation and source-digest callback immediately before
            # the atomic directory-entry operation.
        result.warnings.extend(atomic_writer.cleanup_warnings)
        try:
            publication.commit()
        except OSError:
            result.warnings.append(
                "the private report rollback file could not be removed"
            )
    except _Cancelled:
        _rollback_report(publication)
        _remove_source_snapshot(inspection.path)
        result.status = RunStatus.CANCELLED
        result.output_path = None
        result.provider_attempts = list(attempts.values())
        result.warnings.append("translation was cancelled; no output CSV was published")
        cancelled_publication = _finalize_report(result, config)
        cancelled_publication.commit()
        return result
    except BaseException as exc:
        try:
            publication.rollback()
        except OSError as rollback_error:
            exc.add_note(f"csv-trans report rollback also failed: {rollback_error}")
        raise

    return result


def _normalize_config(
    source_language: str | TranslationConfig,
    target_language: str | None,
    *,
    config: TranslationConfig | None,
    options: dict[str, Any],
) -> TranslationConfig:
    """Merge a reusable config with explicit call-site overrides."""

    valid_fields = {item.name for item in fields(TranslationConfig)}
    unknown = sorted(set(options) - valid_fields)
    if unknown:
        raise TypeError("unexpected translation option(s): " + ", ".join(unknown))

    if isinstance(source_language, TranslationConfig):
        if config is not None:
            raise TypeError("pass a TranslationConfig either positionally or by config, not both")
        if target_language is not None:
            raise TypeError("target_language is already contained in TranslationConfig")
        base = source_language
        language_overrides: dict[str, Any] = {}
    else:
        if target_language is None:
            raise TypeError("target_language is required")
        base = config
        language_overrides = {
            "source_language": source_language,
            "target_language": target_language,
        }

    values: dict[str, Any] = {}
    if base is not None:
        if not isinstance(base, TranslationConfig):
            raise TypeError("config must be a TranslationConfig")
        values.update({item.name: getattr(base, item.name) for item in fields(base)})
    values.update(language_overrides)
    values.update(options)
    return TranslationConfig(**values)


def _provider_chain(config: TranslationConfig) -> tuple[Any, ...]:
    provider = config.provider
    if provider is None:
        from .providers import GoogleFreeProvider

        provider = GoogleFreeProvider()
    return (provider, *config.fallback_providers)


def _source_digest(path: Path, *, expected_size: int | None = None) -> str:
    """Hash a source without retaining any decoded content in memory."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            remaining = expected_size
            while remaining is None or remaining > 0:
                read_size = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
                chunk = stream.read(read_size)
                if not chunk:
                    break
                digest.update(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
            if expected_size is not None and (remaining or stream.read(1)):
                raise CsvInputError("input CSV size changed while it was being read")
    except OSError as exc:
        raise CsvInputError("could not read the input CSV snapshot") from exc
    return digest.hexdigest()


def _source_metadata(path: Path) -> tuple[int, int, int, int, int]:
    try:
        status = path.stat()
    except OSError as exc:
        raise CsvInputError("could not inspect input CSV metadata") from exc
    if not stat.S_ISREG(status.st_mode):
        raise CsvInputError("input path is not a regular file")
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


@contextmanager
def _source_snapshot(
    path: Path,
    *,
    directory: str | Path | None = None,
) -> Iterator[
    tuple[Path, str, tuple[int, int, int, int, int], list[str]]
]:
    """Create a private immutable working copy and return its content digest."""

    snapshot_directory = (
        path.parent
        if directory is None
        else Path(directory).expanduser().resolve()
    )
    try:
        snapshot_directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CsvInputError("could not create the snapshot directory") from exc
    if not snapshot_directory.is_dir():
        raise CsvInputError("snapshot_directory is not a directory")
    handle = tempfile.NamedTemporaryFile(
        mode="w+b",
        prefix=".csv-trans-",
        suffix=".snapshot",
        dir=snapshot_directory,
        delete=False,
    )
    snapshot = Path(handle.name)
    digest = hashlib.sha256()
    cleanup_warnings: list[str] = []
    body_error: BaseException | None = None
    try:
        initial_metadata = _source_metadata(path)
        expected_size = initial_metadata[2]
        try:
            with handle, path.open("rb") as source:
                remaining = expected_size
                while remaining > 0:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                if remaining or source.read(1):
                    raise CsvInputError(
                        "input CSV size changed while its snapshot was created"
                    )
                handle.flush()
        except OSError as exc:
            raise CsvInputError("could not create a private input snapshot") from exc
        expected = digest.hexdigest()
        _assert_source_metadata_unchanged(path, initial_metadata)
        if _source_digest(path, expected_size=expected_size) != expected:
            raise CsvInputError("input CSV changed while its snapshot was created")
        _assert_source_metadata_unchanged(path, initial_metadata)
        try:
            yield snapshot, expected, initial_metadata, cleanup_warnings
        except BaseException as error:
            body_error = error
            raise
    finally:
        try:
            snapshot.unlink(missing_ok=True)
        except OSError as cleanup_error:
            if body_error is not None:
                body_error.add_note(
                    f"csv-trans snapshot cleanup also failed: {cleanup_error}"
                )
            else:
                # Normal control flow removes the snapshot before publication.
                # Keep this outer guard non-fatal in case a future return path
                # misses that early cleanup and an output is already visible.
                cleanup_warnings.append(
                    "the private input snapshot could not be removed"
                )


def _remove_source_snapshot(path: Path) -> None:
    """Remove plaintext staging before publishing any successful artefact."""

    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise CsvInputError("could not remove the private input snapshot") from exc


def _assert_source_unchanged(
    path: Path,
    expected: str,
    expected_metadata: tuple[int, int, int, int, int],
) -> None:
    """Refuse to publish work after the original source content changes."""

    _assert_source_metadata_unchanged(path, expected_metadata)
    if _source_digest(path, expected_size=expected_metadata[2]) != expected:
        raise CsvInputError("input CSV changed while translation was in progress")
    _assert_source_metadata_unchanged(path, expected_metadata)


def _assert_source_metadata_unchanged(
    path: Path, expected: tuple[int, int, int, int, int]
) -> None:
    if _source_metadata(path) != expected:
        raise CsvInputError("input CSV changed while translation was in progress")


def _enforce_privacy(providers: Sequence[Any], config: TranslationConfig) -> None:
    for provider in providers:
        _enforce_provider_privacy(provider, config)


def _enforce_provider_privacy(
    provider: Any,
    config: TranslationConfig,
    *,
    endpoints: Sequence[str] | None = None,
) -> None:
    """Validate one provider at preflight and again immediately before use."""

    name = _provider_name(provider)
    endpoints = tuple(endpoints) if endpoints is not None else _provider_recipient_urls(provider)

    from .exceptions import ProviderConfigurationError
    from .providers import EchoProvider, validate_endpoint, validate_local_endpoint

    for endpoint in endpoints:
        try:
            validate_endpoint(
                endpoint,
                provider=name,
                allow_insecure_http=config.privacy is PrivacyMode.LOCAL_ONLY,
            )
        except (TypeError, ValueError, ProviderConfigurationError) as exc:
            raise PrivacyViolation(f"provider endpoint rejected for {name}: {exc}") from exc

    if config.privacy is PrivacyMode.PUBLIC:
        return
    if config.privacy is PrivacyMode.RESTRICTED:
        if not config.allowed_providers:
            raise PrivacyViolation(
                "restricted mode requires an explicit allowed_providers list"
            )
        allowed = {allowed_name.casefold() for allowed_name in config.allowed_providers}
        if name.casefold() not in allowed:
            raise PrivacyViolation(f"restricted mode rejected provider: {name}")
        return

    if not endpoints:
        # An extension's self-reported ``is_remote=False`` flag is not an
        # enforceable network boundary: arbitrary provider code can still open
        # sockets.  The only endpointless provider the core can prove offline
        # is its exact built-in EchoProvider without an injected transform.
        # Custom/local model providers must declare the endpoint that receives
        # text so local-only policy can validate it.
        if type(provider) is EchoProvider and provider._transform is None:
            return
        raise PrivacyViolation(
            f"local-only mode cannot verify endpoint for {name}"
        )
    for endpoint in endpoints:
        try:
            validate_local_endpoint(
                endpoint, approved_local_hosts=config.approved_local_hosts
            )
        except (TypeError, ValueError, ProviderConfigurationError) as exc:
            raise PrivacyViolation(
                f"local-only mode rejected {name}: {exc}"
            ) from exc


def _validate_row_limits(
    row: Sequence[str], config: TranslationConfig, *, location: str
) -> int:
    """Enforce row-shape and character budgets without including cell text."""

    if len(row) > config.max_columns:
        raise CsvInputError(
            f"{location} has {len(row)} columns, exceeding max_columns={config.max_columns}"
        )
    character_count = sum(len(value) for value in row)
    if character_count > config.max_row_chars:
        raise CsvInputError(
            f"{location} exceeds max_row_chars={config.max_row_chars}"
        )
    return character_count


def _validate_output_row(
    row: Sequence[str], encoding: str, *, location: str
) -> None:
    """Ensure original values can be preserved in the requested output codec."""

    try:
        for value in row:
            value.encode(encoding, errors="strict")
    except UnicodeEncodeError as exc:
        raise CsvInputError(
            f"{location} cannot be represented in output_encoding={encoding!r}"
        ) from exc


def _measure_dry_run(
    rows: Iterable[Sequence[str]],
    selected: Sequence[int],
    result: TranslationResult,
    config: TranslationConfig,
) -> None:
    selected_set = set(selected)
    for row_number, row in enumerate(rows, start=1):
        _check_cancelled(config)
        _validate_row_limits(row, config, location=f"row {row_number}")
        result.row_count += 1
        result.total_cells += len(row)
        for index, _ in enumerate(row):
            if index in selected_set:
                result.selected_cells += 1
            result.skipped_cells += 1


def _process_rows(
    rows: Sequence[tuple[int, list[str]]],
    selected_indexes: Sequence[int],
    headers: Sequence[str],
    providers: Sequence[Any],
    config: TranslationConfig,
    result: TranslationResult,
    attempts: dict[tuple[int, int], ProviderAttempt],
    cache: _TranslationCache,
    *,
    count_total: bool,
) -> list[tuple[int, list[str]]]:
    _check_cancelled(config)
    selected_set = set(selected_indexes)
    output = [(number, list(row)) for number, row in rows]
    cells: list[_CellPlan] = []

    for row_number, row in output:
        if count_total:
            if row_number > 0:
                result.row_count += 1
            result.total_cells += len(row)
        for index, value in enumerate(row):
            if index not in selected_set:
                if count_total:
                    result.skipped_cells += 1
                continue
            if count_total:
                result.selected_cells += 1
            explicitly_selected = config.columns is not None
            eligible = bool(value.strip()) if explicitly_selected else should_translate_cell(value)
            if config.source_language.casefold() == config.target_language.casefold() or not eligible:
                if count_total:
                    result.skipped_cells += 1
                continue
            column_name = headers[index] if index < len(headers) else ""
            segments = segment_text(
                value,
                config.max_chars,
                preserve_placeholders=config.preserve_placeholders,
            )
            if not any(segment.translatable for segment in segments):
                if count_total:
                    result.skipped_cells += 1
                continue
            cells.append(
                _CellPlan(
                    row_number=row_number,
                    column_index=index,
                    column_name=column_name,
                    original=value,
                    segments=segments,
                )
            )

    if not cells:
        return output

    pending_by_text: OrderedDict[str, _Item] = OrderedDict()
    locations: dict[str, list[tuple[_CellPlan, int]]] = {}
    canonical_for_text: dict[str, str] = {}
    source_key = config.source_language.casefold()
    target_key = config.target_language.casefold()

    for cell in cells:
        for segment_index, segment in enumerate(cell.segments):
            if not segment.translatable:
                continue
            cache_key = (source_key, target_key, segment.text)
            cached = cache.get(cache_key)
            if cached is not None:
                cell.translations[segment_index] = cached
                cell.cached_segments.add(segment_index)
                continue
            if segment.text in canonical_for_text:
                canonical_id = canonical_for_text[segment.text]
                locations[canonical_id].append((cell, segment_index))
                cell.cached_segments.add(segment_index)
                continue
            item_id = f"{cell.id}s{segment_index}"
            canonical_for_text[segment.text] = item_id
            item = _Item(item_id, segment.text)
            pending_by_text[item_id] = item
            locations[item_id] = [(cell, segment_index)]

    translated: dict[str, str] = {}
    failed: dict[str, _ItemFailure] = {}
    pending_items = list(pending_by_text.values())
    for start in range(0, len(pending_items), config.batch_size):
        batch = pending_items[start : start + config.batch_size]
        batch_values, batch_failures = _translate_with_chain(
            batch, providers, config, result, attempts
        )
        translated.update(batch_values)
        failed.update(batch_failures)

    for item_id, item in pending_by_text.items():
        if item_id in translated:
            value = translated[item_id]
            cache.put((source_key, target_key, item.text), value)
            for cell, segment_index in locations[item_id]:
                cell.translations[segment_index] = value
        else:
            failure = failed[item_id]
            for cell, _ in locations[item_id]:
                cell.failures.append(failure)

    row_lookup = {row_number: row for row_number, row in output}
    for cell in cells:
        if cell.failures:
            first = cell.failures[0]
            result.failed_cells += 1
            _append_failure(
                result,
                config,
                TranslationFailure(
                    row=cell.row_number,
                    column_index=cell.column_index,
                    column_name=cell.column_name,
                    item_id=cell.id,
                    category=first.category,
                    provider=first.provider,
                    endpoint=first.endpoint,
                    attempts=max(item.attempts for item in cell.failures),
                    message=first.message,
                ),
            )
            # The copied output row already contains the complete source value.
            continue
        translated_value = reconstruct_segments(cell.segments, cell.translations)
        try:
            translated_value.encode(config.output_encoding, errors="strict")
        except UnicodeEncodeError:
            result.failed_cells += 1
            _append_failure(
                result,
                config,
                TranslationFailure(
                    row=cell.row_number,
                    column_index=cell.column_index,
                    column_name=cell.column_name,
                    item_id=cell.id,
                    category="output_encoding",
                    provider="csv-trans",
                    endpoint=None,
                    attempts=0,
                    message="translated value could not be represented in the output encoding",
                ),
            )
            # The original row was prevalidated and remains untouched.
            continue
        row_lookup[cell.row_number][cell.column_index] = translated_value
        result.translated_cells += 1
        translatable_indexes = {
            index for index, segment in enumerate(cell.segments) if segment.translatable
        }
        if translatable_indexes and translatable_indexes <= cell.cached_segments:
            result.cached_cells += 1
    return output


def _append_failure(
    result: TranslationResult,
    config: TranslationConfig,
    failure: TranslationFailure,
) -> None:
    if len(result.failures) < config.max_failure_details:
        result.failures.append(failure)
    else:
        result.omitted_failure_count += 1


def _translate_with_chain(
    items: Sequence[_Item],
    providers: Sequence[Any],
    config: TranslationConfig,
    result: TranslationResult,
    attempts: dict[tuple[int, int], ProviderAttempt],
) -> tuple[dict[str, str], dict[str, _ItemFailure]]:
    successful: dict[str, str] = {}
    unresolved = list(items)
    final_failures: dict[str, _ItemFailure] = {}
    for provider_index, provider in enumerate(providers):
        if not unresolved:
            break
        if provider_index:
            result.fallbacks += 1
        values, failures = _recover_provider(
            unresolved,
            provider,
            config,
            result,
            attempts,
            chain_index=provider_index,
            inherited_attempts=0,
        )
        successful.update(values)
        final_failures.update(failures)
        unresolved = [item for item in unresolved if item.id in failures]
    return successful, {item.id: final_failures[item.id] for item in unresolved}


def _recover_provider(
    items: Sequence[_Item],
    provider: Any,
    config: TranslationConfig,
    result: TranslationResult,
    attempts: dict[tuple[int, int], ProviderAttempt],
    *,
    chain_index: int,
    inherited_attempts: int,
) -> tuple[dict[str, str], dict[str, _ItemFailure]]:
    _check_cancelled(config)
    name = _provider_name(provider)
    attempt_key = (chain_index, id(provider))
    record = attempts.get(attempt_key)
    endpoint: str | None = None
    local_attempts = 0
    last_message = "provider failed without an error message"
    category = "unknown"
    transient_retries = 0
    malformed_retries = 0
    corrective_next = False

    while True:
        _check_cancelled(config)
        raw_endpoints = _provider_recipient_urls(provider)
        _enforce_provider_privacy(provider, config, endpoints=raw_endpoints)
        current_endpoints = _sanitized_endpoints(raw_endpoints)
        endpoint = current_endpoints[0] if current_endpoints else None
        if record is None:
            record = ProviderAttempt(
                provider=name,
                chain_index=chain_index,
                endpoint=endpoint,
                endpoints=current_endpoints,
            )
            attempts[attempt_key] = record
        else:
            record.endpoints = _ordered_unique((*record.endpoints, *current_endpoints))
            if record.endpoint is None:
                record.endpoint = endpoint
        local_attempts += 1
        record.batches += 1
        record.items += len(items)
        try:
            translated = _call_provider(
                provider, items, config, corrective=corrective_next
            )
        except _Cancelled:
            raise
        except Exception as exc:  # providers are an extension boundary
            category = _error_category(exc)
            retryable = _is_retryable(exc)
            last_message = _safe_error_message(exc)
            # Never retain a third-party traceback/cause after classification;
            # transport URLs and parser exceptions can contain submitted text.
            exc.__traceback__ = None
            exc.__cause__ = None
            exc.__context__ = None
            record.failures += 1
            if category == "invalid_response":
                if malformed_retries >= config.malformed_retries:
                    break
                malformed_retries += 1
                retry_number = malformed_retries
                corrective_next = True
            elif retryable and transient_retries < config.max_retries:
                transient_retries += 1
                retry_number = transient_retries
                corrective_next = False
            else:
                break
            record.retries += 1
            result.retries += 1
            _sleep_before_retry(config, retry_number)
        else:
            _check_cancelled(config)
            return translated, {}

    total_attempts = inherited_attempts + local_attempts
    if len(items) > 1 and _should_split(category):
        middle = len(items) // 2
        left_values, left_failures = _recover_provider(
            items[:middle],
            provider,
            config,
            result,
            attempts,
            chain_index=chain_index,
            inherited_attempts=total_attempts,
        )
        right_values, right_failures = _recover_provider(
            items[middle:],
            provider,
            config,
            result,
            attempts,
            chain_index=chain_index,
            inherited_attempts=total_attempts,
        )
        left_values.update(right_values)
        left_failures.update(right_failures)
        return left_values, left_failures

    if (
        len(items) == 1
        and category == "context_limit"
        and len(items[0].text) > config.min_adaptive_chars
    ):
        adaptive = _recover_adaptive_item(
            items[0],
            provider,
            config,
            result,
            attempts,
            chain_index=chain_index,
            inherited_attempts=total_attempts,
        )
        if adaptive is not None:
            return adaptive

    failure = _ItemFailure(
        category=category,
        provider=name,
        endpoint=endpoint,
        attempts=total_attempts,
        message=last_message,
    )
    return {}, {item.id: failure for item in items}


def _recover_adaptive_item(
    item: _Item,
    provider: Any,
    config: TranslationConfig,
    result: TranslationResult,
    attempts: dict[tuple[int, int], ProviderAttempt],
    *,
    chain_index: int,
    inherited_attempts: int,
) -> tuple[dict[str, str], dict[str, _ItemFailure]] | None:
    """Split one context-limited item into smaller, separately sent requests."""

    next_limit = max(config.min_adaptive_chars, len(item.text) // 2)
    if next_limit >= len(item.text):
        return None
    segments = segment_text(
        item.text,
        next_limit,
        preserve_placeholders=config.preserve_placeholders,
    )
    indexes = [
        index for index, segment in enumerate(segments) if segment.translatable
    ]
    if len(indexes) < 2:
        return None

    translated_segments: dict[int, str] = {}
    for index in indexes:
        subitem = _Item(f"{item.id}a{index}", segments[index].text)
        values, failures = _recover_provider(
            [subitem],
            provider,
            config,
            result,
            attempts,
            chain_index=chain_index,
            inherited_attempts=inherited_attempts,
        )
        if failures:
            failure = failures[subitem.id]
            return {}, {item.id: failure}
        translated_segments[index] = values[subitem.id]
    return {item.id: reconstruct_segments(segments, translated_segments)}, {}


def _call_provider(
    provider: Any,
    items: Sequence[_Item],
    config: TranslationConfig,
    *,
    corrective: bool = False,
) -> dict[str, str]:
    provider_items = _make_provider_items(items)
    source_language = (
        None
        if config.source_language.casefold() in {"auto", "detect", "automatic"}
        else config.source_language
    )
    if corrective and hasattr(provider, "translate_corrective"):
        response = provider.translate_corrective(
            provider_items,
            source_language=source_language,
            target_language=config.target_language,
        )
    elif hasattr(provider, "translate"):
        response = provider.translate(
            provider_items,
            source_language=source_language,
            target_language=config.target_language,
        )
    elif hasattr(provider, "translate_batch"):
        response = provider.translate_batch(
            provider_items,
            source_language=source_language,
            target_language=config.target_language,
        )
    else:
        raise TypeError(f"provider {_provider_name(provider)!r} has no translate method")

    expected = [item.id for item in items]
    try:
        iterator = iter(response.items()) if isinstance(response, dict) else iter(response)
        raw_values = list(islice(iterator, len(expected) + 1))
        if isinstance(response, dict):
            pairs = raw_values
        else:
            pairs = [(item.id, item.text) for item in raw_values]
    except (AttributeError, TypeError) as exc:
        raise ProviderResponseError(
            "provider response must contain items with string id and text fields"
        ) from exc
    if len(pairs) > len(expected):
        raise ProviderResponseError("provider returned more items than requested")
    received_order = [item_id for item_id, _ in pairs]
    if received_order != expected:
        raise ProviderResponseError("provider response item order did not match the request")
    received: dict[str, str] = {}
    for item_id, text in pairs:
        if not isinstance(item_id, str) or not isinstance(text, str):
            raise ProviderResponseError("provider response IDs and text must be strings")
        if item_id in received:
            raise ProviderResponseError(f"provider returned duplicate item ID {item_id!r}")
        received[item_id] = text
    if set(received) != set(expected):
        missing = sorted(set(expected) - set(received))
        unexpected = sorted(set(received) - set(expected))
        raise ProviderResponseError(
            f"provider response ID mismatch (missing={missing}, unexpected={unexpected})"
        )
    for source_item in items:
        value = received[source_item.id]
        maximum = max(4_096, len(source_item.text) * 8 + 1_024)
        if len(value) > maximum:
            raise ProviderResponseError(
                f"provider response for {source_item.id!r} exceeded the safety limit"
            )
        if (
            source_item.text.strip()
            and not value.strip()
            and not config.allow_empty_translations
        ):
            raise ProviderResponseError(
                "provider returned an empty translation for non-empty source text"
            )
        try:
            value.encode(config.output_encoding, errors="strict")
        except UnicodeEncodeError as exc:
            raise ProviderOutputEncodingError(
                "provider translation is not representable in the output encoding"
            ) from exc
    return {item_id: received[item_id] for item_id in expected}


def _make_provider_items(items: Sequence[_Item]) -> list[Any]:
    try:
        from .providers import TranslationItem

        return [TranslationItem(id=item.id, text=item.text) for item in items]
    except ImportError:
        return list(items)


def _provider_name(provider: Any) -> str:
    return str(
        getattr(
            provider,
            "name",
            getattr(provider, "provider_id", provider.__class__.__name__),
        )
    )


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _provider_recipient_urls(provider: Any) -> tuple[str, ...]:
    """Return every URL a provider declares it may submit source text to.

    ``recipient_endpoints`` is the extensible provider convention. Conventional
    ``endpoint``/``base_url`` attributes remain supported, and the built-in
    Google adapter's separately named HTML fallback is included only when that
    fallback is enabled.
    """

    collected: list[str] = []

    declared = getattr(provider, "recipient_endpoints", None)
    if callable(declared):
        declared = declared()
    if declared:
        if isinstance(declared, str):
            collected.append(declared)
        else:
            try:
                collected.extend(str(value) for value in declared if value)
            except TypeError:
                collected.append(str(declared))

    for attribute in ("endpoint", "base_url"):
        value = getattr(provider, attribute, None)
        if value:
            collected.append(str(value))

    if getattr(provider, "allow_html_fallback", False):
        fallback = getattr(provider, "fallback_url", None)
        if fallback:
            collected.append(str(fallback))

    return _ordered_unique(collected)


def _sanitize_endpoint(raw: str) -> str | None:
    """Return only a scheme/host/port recipient identity, never URL secrets."""

    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not host:
        return None
    display_host = f"[{host}]" if ":" in host else host
    port_part = f":{port}" if port is not None else ""
    return f"{parsed.scheme.casefold()}://{display_host}{port_part}"


def _sanitized_endpoints(endpoints: Iterable[str]) -> tuple[str, ...]:
    sanitized: list[str] = []
    seen: set[str] = set()
    for raw in endpoints:
        endpoint = _sanitize_endpoint(raw)
        if endpoint is None or endpoint.casefold() in seen:
            continue
        seen.add(endpoint.casefold())
        sanitized.append(endpoint)
    return tuple(sanitized)


def _provider_endpoint(provider: Any) -> str | None:
    """Return the provider's first sanitized recipient for compatibility."""

    endpoints = _sanitized_endpoints(_provider_recipient_urls(provider))
    return endpoints[0] if endpoints else None


def _error_category(error: Exception) -> str:
    if isinstance(error, (TimeoutError, ConnectionError)):
        return "transient"
    value = getattr(error, "category", "unknown")
    if hasattr(value, "value"):
        value = value.value
    normalized = str(value).lower().replace("-", "_")
    aliases = {
        "auth": "authentication",
        "malformed": "invalid_response",
        "malformed_response": "invalid_response",
        "response": "invalid_response",
        "quota": "rate_limit",
    }
    normalized = aliases.get(normalized, normalized)
    allowed = {
        "authentication",
        "configuration",
        "rate_limit",
        "context_limit",
        "timeout",
        "transient",
        "connection",
        "invalid_request",
        "invalid_response",
        "server",
        "unavailable",
        "privacy",
        "policy",
        "unsupported_language",
        "output_encoding",
        "unknown",
    }
    return normalized if normalized in allowed else "unknown"


def _is_retryable(error: Exception) -> bool:
    if hasattr(error, "retryable"):
        return bool(getattr(error, "retryable"))
    return isinstance(error, (TimeoutError, ConnectionError))


def _should_split(category: str) -> bool:
    return category in {"context_limit", "invalid_response", "output_encoding"}


def _safe_error_message(error: Exception | None) -> str:
    if error is None:
        return "provider failed without an error message"
    # Provider exceptions are an extension boundary: even an instance of the
    # public ProviderError class may have been raised by third-party code with
    # a source cell, response body, or API key embedded in its message. Reports
    # therefore serialize only our own category-derived wording.
    category = _error_category(error)
    messages = {
        "authentication": "provider authentication failed",
        "configuration": "provider configuration failed",
        "rate_limit": "provider rate limit was exceeded",
        "context_limit": "provider context limit was exceeded",
        "timeout": "provider request timed out",
        "transient": "provider request failed transiently",
        "connection": "provider connection failed",
        "invalid_request": "provider rejected the request",
        "invalid_response": "provider response failed validation",
        "malformed": "provider response failed validation",
        "malformed_response": "provider response failed validation",
        "response": "provider response failed validation",
        "server": "provider reported a server error",
        "unavailable": "provider was unavailable",
        "privacy": "provider was rejected by privacy policy",
        "policy": "provider rejected the request by policy",
        "output_encoding": "provider output was incompatible with the output encoding",
    }
    return messages.get(category, "provider failed with an unclassified error")


def _sleep_before_retry(config: TranslationConfig, attempt: int) -> None:
    delay = min(config.max_backoff, config.backoff_base * (2 ** (attempt - 1)))
    if config.jitter and config.max_backoff:
        delay = min(config.max_backoff, delay + random.uniform(0.0, config.jitter))
    if delay:
        time.sleep(delay)


def _check_cancelled(config: TranslationConfig) -> None:
    if config.cancellation_check and config.cancellation_check():
        raise _Cancelled()


def _notify(
    config: TranslationConfig, result: TranslationResult, phase: str
) -> None:
    if config.progress_callback:
        try:
            config.progress_callback(
                ProgressEvent(
                    phase=phase,
                    rows_processed=result.row_count,
                    cells_translated=result.translated_cells,
                    cells_failed=result.failed_cells,
                )
            )
        except Exception:
            warning = "progress callback failed and was ignored"
            if warning not in result.warnings:
                result.warnings.append(warning)


def _report_file_identity(path: Path) -> tuple[int, int, int, int, int] | None:
    """Return a final-component identity without following symbolic links."""

    try:
        status = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise OSError("could not inspect the report destination") from exc
    if not stat.S_ISREG(status.st_mode):
        raise OSError("report destination is no longer a regular file")
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _report_rollback_link(path: Path) -> Path:
    """Hard-link an existing report so an output-commit failure can restore it."""

    original_identity = _report_file_identity(path)
    if original_identity is None:
        raise FileNotFoundError("report disappeared before it could be preserved")
    descriptor, raw_backup = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".rollback", dir=path.parent
    )
    os.close(descriptor)
    backup = Path(raw_backup)
    backup.unlink()
    try:
        os.link(path, backup, follow_symlinks=False)
        if not os.path.samefile(path, backup):
            raise OSError("report rollback link did not preserve the expected file")
        if _report_file_identity(backup) is None:
            raise OSError("report rollback link is not a regular file")
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _publish_report(
    result: TranslationResult,
    path: Path,
    *,
    overwrite: bool,
) -> _ReportPublication:
    """Publish one report and capture rollback state for the CSV transaction."""

    backup: Path | None = None
    published = False
    try:
        if overwrite and path.exists():
            backup = _report_rollback_link(path)
        result.write_json(path, overwrite=overwrite)
        published = True
        identity = _report_file_identity(path)
        if identity is None:
            raise OSError("report disappeared immediately after publication")
        return _ReportPublication(
            result=result,
            path=path,
            backup=backup,
            published_identity=identity,
        )
    except BaseException as error:
        if published:
            try:
                if backup is not None:
                    os.replace(backup, path)
                    backup = None
                else:
                    path.unlink(missing_ok=True)
            except OSError as rollback_error:
                # Keep an unconsumed backup: deleting the last copy of the
                # caller's prior report would make the recovery failure worse.
                error.add_note(
                    f"csv-trans report publication rollback also failed: {rollback_error}"
                )
        elif backup is not None:
            # Publication never completed, so the original report remains at
            # its destination and this extra hard link is no longer needed.
            try:
                backup.unlink(missing_ok=True)
                backup = None
            except OSError as cleanup_error:
                error.add_note(
                    f"csv-trans report rollback cleanup also failed: {cleanup_error}"
                )
        result.report_path = None
        raise


def _rollback_report(publication: _ReportPublication) -> None:
    publication.rollback()


def _finalize_report(
    result: TranslationResult, config: TranslationConfig
) -> _ReportPublication:
    if config.report_path:
        return _publish_report(
            result,
            resolve_destination_path(config.report_path),
            overwrite=config.overwrite,
        )
    if not result.failed_cells or result.output_path is None:
        return _ReportPublication(result)

    prohibited = {
        result.input_path.expanduser().resolve(),
        resolve_destination_path(result.output_path),
    }
    counter = 0
    while True:
        suffix = ".report.json" if counter == 0 else f".report.{counter}.json"
        candidate = result.output_path.with_name(result.output_path.name + suffix)
        resolved = resolve_destination_path(candidate)
        counter += 1

        # An automatic sidecar must never replace either CSV, even when the
        # caller enabled overwrite for a rerun. Avoid following a pre-existing
        # sidecar symlink as well; choose the next deterministic name instead.
        if resolved in prohibited or candidate.is_symlink():
            continue
        if config.overwrite and candidate.exists() and not candidate.is_file():
            continue
        try:
            return _publish_report(
                result,
                resolved,
                overwrite=config.overwrite,
            )
        except FileExistsError:
            if config.overwrite:
                raise
            # Publication, not a prior exists() probe, decides the winner. This
            # makes automatic numbering safe when concurrent runs race.
            continue


def _validate_explicit_report_path(
    config: TranslationConfig, source: Path, destination: Path
) -> None:
    if not config.report_path:
        return
    report = resolve_destination_path(config.report_path)
    if report.is_symlink():
        raise OutputExistsError(f"report path must not be a symbolic link: {report}")
    if report in {source, destination}:
        raise ValueError("report_path must differ from both input and output CSV paths")
    if report.exists() and not config.overwrite:
        raise OutputExistsError(
            f"report already exists: {report}; pass overwrite=True to replace it"
        )
    if report.exists() and not report.is_file():
        raise OutputExistsError(f"report path is not a regular file: {report}")


__all__ = ["PrivacyViolation", "ProviderResponseError", "translate_csv"]
