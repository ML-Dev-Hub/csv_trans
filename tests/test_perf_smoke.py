"""Correctness smoke tests locking in the optimized core._process_rows paths.

These assert behavior (structure preservation, counting semantics, cell
placement, cache accounting), never timing. They guard the selected-column
iteration, the row-reference write, and the cached-cell accounting introduced
as performance optimizations, so a future regression cannot silently change
observable behavior.
"""

from __future__ import annotations

import csv
from pathlib import Path

from csv_trans.core import translate_csv
from csv_trans.models import RunStatus, TranslationConfig
from csv_trans.providers import EchoProvider


def _read_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def _write_rows(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)


REPRESENTATIVE = [
    ["id", "user_id", "amount", "description", "comment", "status"],
    ["0", "u1", "12.50", "the quick brown fox", "a lazy dog sleeps", "active"],
    ["1", "u2", "9999.99", "jumps over lazily", "", "pending"],
    # quoted field with embedded delimiter and newline
    ["2", "u3", "3.14", "hello, world\nsecond line", "note here", "closed"],
    # ragged (short) row
    ["3", "u4", "1.00", "short row"],
    # duplicate text to exercise dedup / cache accounting
    ["4", "u5", "42.00", "the quick brown fox", "the quick brown fox", "active"],
]


def _config(**overrides):
    base = dict(
        source_language="en",
        target_language="fr",
        provider=EchoProvider(),
        overwrite=True,
    )
    base.update(overrides)
    return TranslationConfig(**base)


def test_identity_echo_preserves_every_cell(tmp_path: Path) -> None:
    src = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    _write_rows(src, REPRESENTATIVE)

    result = translate_csv(str(src), _config(), output_path=str(out))

    assert result.status is RunStatus.SUCCESS
    # Echo is identity: structure and content survive byte-for-byte per row.
    assert _read_rows(out) == REPRESENTATIVE
    # Counting invariant: every cell is either selected or skipped-as-nonselected,
    # and every selected cell is translated, skipped, or failed.
    assert result.failed_cells == 0
    assert result.total_cells == sum(len(r) for r in REPRESENTATIVE[1:])


def test_transform_lands_in_correct_columns(tmp_path: Path) -> None:
    src = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    _write_rows(src, REPRESENTATIVE)

    # Uppercasing transform makes translated text visibly distinct so we can
    # confirm the row-reference write targets exactly the selected columns.
    provider = EchoProvider(transform=lambda text, s, t: text.upper())
    result = translate_csv(
        str(src),
        _config(provider=provider, columns=["description", "comment"]),
        output_path=str(out),
    )

    assert result.status is RunStatus.SUCCESS
    rows = _read_rows(out)
    original = REPRESENTATIVE
    # id/user_id/amount/status columns untouched; description/comment uppercased.
    for produced, source in zip(rows[1:], original[1:], strict=True):
        assert produced[0] == source[0]  # id
        assert produced[1] == source[1]  # user_id
        assert produced[2] == source[2]  # amount
        assert produced[3] == source[3].upper()  # description
        if len(source) > 4:
            assert produced[4] == source[4].upper()  # comment
        if len(source) > 5:
            assert produced[5] == source[5]  # status untouched


def test_non_ascending_explicit_columns_preserve_order(tmp_path: Path) -> None:
    # Selecting columns out of order must not change which cell each translation
    # lands in: the optimized loop iterates selected columns in ascending order.
    src = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    _write_rows(src, REPRESENTATIVE)

    provider = EchoProvider(transform=lambda text, s, t: f"<{text}>")
    result = translate_csv(
        str(src),
        _config(provider=provider, columns=["comment", "description"]),
        output_path=str(out),
    )

    assert result.status is RunStatus.SUCCESS
    rows = _read_rows(out)
    for produced, source in zip(rows[1:], REPRESENTATIVE[1:], strict=True):
        assert produced[3] == f"<{source[3]}>"
        if len(source) > 4 and source[4].strip():
            assert produced[4] == f"<{source[4]}>"
        else:
            # empty comment stays empty; nothing to translate
            if len(source) > 4:
                assert produced[4] == source[4]


def test_identical_languages_skip_everything(tmp_path: Path) -> None:
    src = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    _write_rows(src, REPRESENTATIVE)

    result = translate_csv(
        str(src),
        _config(source_language="en", target_language="en"),
        output_path=str(out),
    )

    assert result.status is RunStatus.SUCCESS
    assert result.translated_cells == 0
    assert _read_rows(out) == REPRESENTATIVE
    # Every cell counted, none translated: all accounted as skipped.
    assert result.skipped_cells == result.total_cells


def test_duplicate_text_reports_cached_cells(tmp_path: Path) -> None:
    src = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    rows = [
        ["id", "text"],
        ["0", "repeated phrase here"],
        ["1", "repeated phrase here"],
        ["2", "repeated phrase here"],
    ]
    _write_rows(src, rows)

    result = translate_csv(str(src), _config(), output_path=str(out))

    assert result.status is RunStatus.SUCCESS
    # First occurrence translated; later identical cells resolved without a new
    # provider unit, so at least one cell is counted as cached.
    assert result.cached_cells >= 1
    assert _read_rows(out) == rows
