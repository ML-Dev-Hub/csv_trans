"""Column and cell selection without dataframe type inference."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Iterable, Sequence

from .models import ColumnSelection


_IDENTIFIER_HEADER = re.compile(
    r"^(?:id|uuid|guid|key|pk|sku|code|index|idx|row|number|num|no|zip|postal(?:_?code)?)$",
    re.IGNORECASE,
)
_URL_OR_EMAIL = re.compile(
    r"^(?:https?://|www\.)\S+$|^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$",
    re.IGNORECASE,
)
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_DATE_OR_TIME = re.compile(
    r"^(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})"
    r"(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
_CODE = re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9_.:/-]+$")


def is_numeric(value: str) -> bool:
    """Return whether *value* is a conventional numeric literal."""

    candidate = value.strip()
    if not candidate:
        return False
    # Accept thousands separators only in unambiguous three-digit groups.
    if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", candidate):
        candidate = candidate.replace(",", "")
    if candidate.endswith("%"):
        candidate = candidate[:-1]
    try:
        Decimal(candidate)
    except InvalidOperation:
        return False
    return True


def is_machine_value(value: str) -> bool:
    """Return whether a nonempty field is better preserved than translated."""

    candidate = value.strip()
    if not candidate:
        return True
    if is_numeric(candidate):
        return True
    if _URL_OR_EMAIL.fullmatch(candidate):
        return True
    if _UUID.fullmatch(candidate) or _DATE_OR_TIME.fullmatch(candidate):
        return True
    if _CODE.fullmatch(candidate):
        return True
    return not any(character.isalpha() for character in candidate)


def should_translate_cell(value: str) -> bool:
    """Apply per-cell safeguards after its column has been selected."""

    return bool(value.strip()) and not is_machine_value(value)


def resolve_columns(
    headers: Sequence[str],
    sample_rows: Sequence[Sequence[str]],
    requested: Sequence[str | int] | None,
) -> tuple[list[int], list[ColumnSelection]]:
    """Resolve explicit fields or infer text-like fields from bounded samples."""

    if requested is not None:
        selected = _resolve_explicit(headers, requested)
        selected_set = set(selected)
        report = [
            ColumnSelection(
                index=index,
                name=name,
                selected=index in selected_set,
                reason="explicitly selected" if index in selected_set else "not requested",
            )
            for index, name in enumerate(headers)
        ]
        return selected, report

    selected: list[int] = []
    report: list[ColumnSelection] = []
    for index, name in enumerate(headers):
        values = [
            row[index]
            for row in sample_rows
            if index < len(row) and row[index].strip()
        ]
        decision = _classify_column(name, values)
        report.append(
            ColumnSelection(
                index=index,
                name=name,
                selected=decision[0],
                reason=decision[1],
                confidence=decision[2],
            )
        )
        if decision[0]:
            selected.append(index)
    return selected, report


def _resolve_explicit(
    headers: Sequence[str], requested: Sequence[str | int]
) -> list[int]:
    if not requested:
        return []
    resolved: list[int] = []
    for selector in requested:
        if isinstance(selector, bool):
            raise ValueError("boolean values are not valid column indexes")
        if isinstance(selector, int):
            if selector < 0 or selector >= len(headers):
                raise ValueError(
                    f"column index {selector} is outside 0..{max(0, len(headers) - 1)}"
                )
            index = selector
        elif isinstance(selector, str):
            matches = [index for index, header in enumerate(headers) if header == selector]
            if not matches:
                raise ValueError(f"column {selector!r} was not found")
            if len(matches) > 1:
                raise ValueError(
                    f"column name {selector!r} is duplicated; select it by zero-based index"
                )
            index = matches[0]
        else:
            raise TypeError("columns must contain names or zero-based integer indexes")
        if index not in resolved:
            resolved.append(index)
    return resolved


def _classify_column(name: str, values: Sequence[str]) -> tuple[bool, str, float]:
    normalized_name = re.sub(r"[\s-]+", "_", name.strip())
    if _IDENTIFIER_HEADER.fullmatch(normalized_name):
        return False, "identifier-like header", 0.99
    if not values:
        return False, "empty in selection sample", 1.0

    numeric_count = sum(is_numeric(value) for value in values)
    machine_count = sum(is_machine_value(value) for value in values)
    numeric_ratio = numeric_count / len(values)
    machine_ratio = machine_count / len(values)
    if numeric_ratio >= 0.8:
        return False, "numeric-like values", numeric_ratio
    if machine_ratio >= 0.8:
        return False, "identifier or machine-like values", machine_ratio

    alpha_values = [value for value in values if any(char.isalpha() for char in value)]
    if alpha_values:
        # Natural-language evidence includes alphabetic words even if the
        # values are short (city names and labels should not be mistaken for
        # identifiers merely because they are unique).
        confidence = max(0.55, min(0.99, 1.0 - machine_ratio))
        return True, "text-like values", confidence
    return False, "no text-like values", 0.9


def display_selected_columns(
    selection: Iterable[ColumnSelection],
) -> list[dict[str, object]]:
    """Return a compact serializable selection view for user interfaces."""

    return [
        {"index": item.index, "name": item.name, "reason": item.reason}
        for item in selection
        if item.selected
    ]


__all__ = [
    "display_selected_columns",
    "is_machine_value",
    "is_numeric",
    "resolve_columns",
    "should_translate_cell",
]
