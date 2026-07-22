"""Dependency-free CSV inspection, streaming, and atomic output."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import codecs
import csv
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Callable, Iterator, TextIO


class CsvInputError(ValueError):
    """The input cannot be decoded or interpreted safely as CSV."""


class OutputExistsError(FileExistsError):
    """An output collision was rejected by the configured policy."""


_FIELD_LIMIT_LOCK = threading.RLock()


def resolve_destination_path(path: str | Path) -> Path:
    """Resolve a destination parent without following its final component."""

    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return expanded.parent.resolve() / expanded.name


@dataclass(slots=True, frozen=True)
class CsvFormat:
    """The CSV properties preserved by the streaming writer."""

    delimiter: str = ","
    quotechar: str = '"'
    escapechar: str | None = None
    doublequote: bool = True
    skipinitialspace: bool = False
    quoting: int = csv.QUOTE_MINIMAL
    lineterminator: str = "\n"

    def reader_options(self) -> dict[str, object]:
        return {
            "delimiter": self.delimiter,
            "quotechar": self.quotechar,
            "escapechar": self.escapechar,
            "doublequote": self.doublequote,
            "skipinitialspace": self.skipinitialspace,
            "quoting": self.quoting,
            "strict": True,
        }

    def writer_options(self) -> dict[str, object]:
        return {
            "delimiter": self.delimiter,
            "quotechar": self.quotechar,
            "escapechar": self.escapechar,
            "doublequote": self.doublequote,
            "skipinitialspace": self.skipinitialspace,
            "quoting": self.quoting,
            "lineterminator": self.lineterminator,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "delimiter": self.delimiter,
            "quotechar": self.quotechar,
            "escapechar": self.escapechar,
            "doublequote": self.doublequote,
            "skipinitialspace": self.skipinitialspace,
            "quoting": self.quoting,
            "lineterminator": self.lineterminator,
        }


@dataclass(slots=True, frozen=True)
class CsvInspection:
    path: Path
    encoding: str
    format: CsvFormat


def detect_encoding(path: str | Path, requested: str | None = None) -> str:
    """Detect Unicode BOMs or strictly validate UTF-8.

    Legacy encodings are intentionally explicit.  Guessing Latin-1 (which can
    decode every byte sequence) would silently corrupt files whose real code
    page is unknown.
    """

    source = Path(path)
    if requested and requested.lower() not in {"auto", "detect"}:
        try:
            return codecs.lookup(requested).name
        except LookupError as exc:
            raise CsvInputError(f"unknown input encoding: {requested}") from exc

    try:
        with source.open("rb") as stream:
            prefix = stream.read(4)
    except OSError as exc:
        raise CsvInputError(f"cannot read {source}: {exc}") from exc

    if prefix.startswith(codecs.BOM_UTF32_LE) or prefix.startswith(codecs.BOM_UTF32_BE):
        return "utf-32"
    if prefix.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if prefix.startswith(codecs.BOM_UTF16_LE) or prefix.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"

    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    offset = 0
    try:
        with source.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                decoder.decode(chunk)
                offset += len(chunk)
            decoder.decode(b"", final=True)
    except UnicodeDecodeError as exc:
        position = max(0, offset - 4 + exc.start)
        raise CsvInputError(
            "input is not valid UTF-8 and has no Unicode BOM; "
            f"pass an explicit encoding (decode failed near byte {position})"
        ) from exc
    return "utf-8"


def inspect_csv(
    path: str | Path,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    sample_chars: int = 65_536,
) -> CsvInspection:
    """Inspect an input without loading the complete CSV into memory."""

    if sample_chars < 1:
        raise CsvInputError("sample_chars must be at least 1")
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise CsvInputError(f"input file does not exist: {source}")
    if not source.is_file():
        raise CsvInputError(f"input path is not a regular file: {source}")
    selected_encoding = detect_encoding(source, encoding)
    try:
        with source.open("r", encoding=selected_encoding, newline="") as stream:
            sample = stream.read(sample_chars)
            sample_was_truncated = bool(stream.read(1))
    except (OSError, UnicodeError) as exc:
        raise CsvInputError(f"cannot decode {source}: {exc}") from exc
    if not sample:
        raise CsvInputError("input CSV is empty")
    if (
        delimiter is None
        and sample_was_truncated
        and "\n" not in sample
        and "\r" not in sample
    ):
        raise CsvInputError(
            "CSV dialect sample ended before the first record; pass an explicit delimiter"
        )

    line_ending = (
        "\r\n"
        if "\r\n" in sample
        else "\n"
        if "\n" in sample
        else "\r"
        if "\r" in sample
        else "\n"
    )
    candidates = delimiter if delimiter is not None else ",;\t|"
    if delimiter is not None and (
        len(delimiter) != 1 or delimiter in {"\r", "\n", "\0"}
    ):
        raise CsvInputError("delimiter must be one non-newline, non-NUL character")
    try:
        detected = csv.Sniffer().sniff(sample, delimiters=candidates)
        selected_delimiter = delimiter or detected.delimiter
        csv_format = CsvFormat(
            delimiter=selected_delimiter,
            quotechar=detected.quotechar or '"',
            escapechar=detected.escapechar,
            doublequote=detected.doublequote,
            skipinitialspace=detected.skipinitialspace,
            quoting=detected.quoting,
            lineterminator=line_ending,
        )
    except csv.Error:
        if delimiter is None:
            present_candidates = [
                candidate for candidate in ",;\t|" if candidate in sample
            ]
            if len(present_candidates) > 1:
                raise CsvInputError(
                    "CSV delimiter could not be detected unambiguously; pass an explicit delimiter"
                )
            inferred_delimiter = (
                present_candidates[0] if present_candidates else ","
            )
        else:
            inferred_delimiter = delimiter
        csv_format = CsvFormat(
            delimiter=inferred_delimiter,
            lineterminator=line_ending,
        )
    return CsvInspection(source, selected_encoding, csv_format)


@contextmanager
def open_rows(
    inspection: CsvInspection,
    *,
    max_field_chars: int = 64 * 1024 * 1024,
) -> Iterator[Any]:
    """Yield a strict streaming reader for a prior inspection."""

    stream: TextIO | None = None
    try:
        stream = inspection.path.open(
            "r", encoding=inspection.encoding, newline=""
        )
    except (UnicodeError, OSError) as exc:
        raise CsvInputError(f"failed while opening CSV: {exc}") from exc
    try:
        yield _SafeReader(
            csv.reader(stream, **inspection.format.reader_options()),
            max_field_chars=max_field_chars,
        )
    finally:
        if stream is not None:
            stream.close()


class _SafeReader:
    """Normalize only reader failures, not errors raised by the caller body."""

    def __init__(self, reader: Any, *, max_field_chars: int) -> None:
        if max_field_chars < 1:
            raise CsvInputError("max_field_chars must be at least 1")
        self._reader = reader
        self._max_field_chars = max_field_chars

    def __iter__(self) -> "_SafeReader":
        return self

    def __next__(self) -> list[str]:
        # Python's CSV parser uses a process-global field limit. Change it only
        # around one read, serialize csv-trans readers, and restore it even when
        # parsing fails so importing this package does not mutate host policy.
        with _FIELD_LIMIT_LOCK:
            previous_limit = csv.field_size_limit()
            try:
                csv.field_size_limit(self._max_field_chars)
                return next(self._reader)
            except (csv.Error, UnicodeError, OSError, OverflowError) as exc:
                raise CsvInputError(f"failed while reading CSV: {exc}") from exc
            finally:
                csv.field_size_limit(previous_limit)


def default_output_path(input_path: str | Path, target_language: str) -> Path:
    """Return the historical output name with a filesystem-safe language tag."""

    source = Path(input_path).expanduser().resolve()
    safe_target = re.sub(r"[^A-Za-z0-9._-]+", "_", target_language).strip("._")
    if not safe_target:
        safe_target = "target"
    return source.with_name(f"translated_{safe_target}_{source.name}")


def validate_output_path(
    input_path: str | Path, output_path: str | Path, *, overwrite: bool
) -> Path:
    """Validate collision policy before a provider can incur work or cost."""

    source = Path(input_path).expanduser().resolve()
    destination = resolve_destination_path(output_path)
    if destination.is_symlink():
        raise OutputExistsError(f"output path must not be a symbolic link: {destination}")
    if destination.exists() and not overwrite:
        raise OutputExistsError(
            f"output already exists: {destination}; pass overwrite=True to replace it"
        )
    if destination == source and not overwrite:
        raise OutputExistsError("replacing the input requires overwrite=True")
    if destination.exists() and not destination.is_file():
        raise OutputExistsError(f"output path is not a regular file: {destination}")
    return destination


class AtomicCsvWriter:
    """Write beside the destination and publish only after complete success."""

    def __init__(
        self,
        destination: str | Path,
        *,
        encoding: str,
        csv_format: CsvFormat,
        overwrite: bool,
        before_commit: Callable[[], None] | None = None,
    ) -> None:
        self.destination = resolve_destination_path(destination)
        self.encoding = encoding
        self.csv_format = csv_format
        self.overwrite = overwrite
        self.before_commit = before_commit
        self._temporary: Path | None = None
        self._stream: TextIO | None = None
        self._published = False
        self.cleanup_warnings: list[str] = []

    def __enter__(self) -> csv.writer:
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        if self.destination.is_symlink():
            raise OutputExistsError(
                f"output path must not be a symbolic link: {self.destination}"
            )
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding=self.encoding,
            newline="",
            prefix=f".{self.destination.name}.",
            suffix=".tmp",
            dir=self.destination.parent,
            delete=False,
        )
        self._stream = handle
        self._temporary = Path(handle.name)
        return csv.writer(handle, **self.csv_format.writer_options())

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        assert self._stream is not None
        assert self._temporary is not None
        internal_error: BaseException | None = None
        try:
            if exc_type is None:
                try:
                    # Prepare the complete staging file before the caller's
                    # final consistency check.  The callback then runs as close
                    # as practical to the atomic directory-entry operation.
                    self._stream.flush()
                    os.fsync(self._stream.fileno())
                except BaseException as error:
                    internal_error = error

            try:
                self._stream.close()
            except BaseException as close_error:
                target = internal_error or (exc if isinstance(exc, BaseException) else None)
                if target is not None:
                    target.add_note(f"csv-trans staging close also failed: {close_error}")
                else:
                    internal_error = close_error

            if exc_type is None and internal_error is None:
                try:
                    if self.before_commit is not None:
                        self.before_commit()
                    self._commit()
                except BaseException as error:
                    internal_error = error
        finally:
            try:
                self._temporary.unlink(missing_ok=True)
            except OSError as cleanup_error:
                target = internal_error or (exc if isinstance(exc, BaseException) else None)
                if target is not None:
                    target.add_note(
                        f"csv-trans staging cleanup also failed: {cleanup_error}"
                    )
                elif self._published:
                    # The destination is already complete and visible.  A
                    # failure to remove its private staging hard link must not
                    # turn that successful publication into a reported fatal.
                    self.cleanup_warnings.append(
                        "the private CSV staging file could not be removed"
                    )
                else:
                    internal_error = cleanup_error
        if internal_error is not None:
            raise internal_error
        return False

    def _commit(self) -> None:
        assert self._temporary is not None
        if self.overwrite:
            os.replace(self._temporary, self.destination)
            self._published = True
            return
        if os.name == "nt":
            # Windows rename is atomic and refuses to replace an existing
            # destination, so no second hard-link name needs cleanup.
            try:
                os.rename(self._temporary, self.destination)
            except FileExistsError as exc:
                raise OutputExistsError(
                    f"output already exists: {self.destination}"
                ) from exc
            self._published = True
            return
        try:
            # A hard link publishes the completed inode without an overwrite
            # race.  Source and destination share a directory/filesystem.
            os.link(self._temporary, self.destination)
        except FileExistsError as exc:
            raise OutputExistsError(f"output already exists: {self.destination}") from exc
        self._published = True


__all__ = [
    "AtomicCsvWriter",
    "CsvFormat",
    "CsvInputError",
    "CsvInspection",
    "OutputExistsError",
    "default_output_path",
    "detect_encoding",
    "inspect_csv",
    "open_rows",
    "resolve_destination_path",
    "validate_output_path",
]
