"""Column and cell selection without dataframe type inference."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Sequence

from .models import ColumnSelection


_IDENTIFIER_HEADER = re.compile(
    r"^(?:id|uuid|guid|key|pk|sku|code|index|idx|row|number|num|no|zip|postal(?:_?code)?)$",
    re.IGNORECASE,
)
# Credential/secret words appearing as a component of a (possibly composite)
# header name. A column named ``client_secret``/``session_token``/``api_key``
# must never be auto-selected and disclosed to a provider. Skipping is the safe
# direction, so this is intentionally aggressive on credential vocabulary.
_SECRET_HEADER = re.compile(
    r"(?:^|_)(?:password|passwd|pwd|secret|token|apikey|api_?key|auth|"
    r"access_?token|refresh_?token|credential|credentials|private_?key|"
    r"client_?secret|signing_?key)(?:$|_)",
    re.IGNORECASE,
)
# Unambiguous identifier affixes in composite names (user_id, order_uuid, ...).
# Kept narrow so ordinary text columns are not over-skipped; value-based
# heuristics still catch identifier columns that use other naming.
_IDENTIFIER_AFFIX = re.compile(
    r"(?:^|_)(?:id|uuid|guid|sku)(?:$|_)",
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
_THOUSANDS = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?")


def _is_non_finite_token(candidate: str) -> bool:
    """Whether *candidate* is a Decimal NaN/sNaN/Infinity missing-value marker.

    NaN / inf / Infinity (any sign, case, payload, or underscore grouping) are
    missing-value tokens in numpy/pandas exports, not natural-language words. A
    fixed ``nan|inf|infinity`` regex silently misses signaling NaNs (``sNaN``,
    ``-sNaN``), NaN payloads that carry no digit (``sNaN`` vs ``NaN123``), and
    underscore-broken spellings that Decimal still accepts (``s_nan``). Decimal's
    own parser is the authoritative grammar for these, so we defer to it and test
    finiteness directly rather than guessing at the surface form.
    """

    try:
        number = Decimal(candidate)
    except InvalidOperation:
        return False
    return number.is_nan() or number.is_infinite()


def is_numeric(value: str) -> bool:
    """Return whether *value* is a conventional numeric literal."""

    candidate = value.strip()
    if not candidate:
        return False
    # Decimal also parses the words NaN/Infinity and underscore-grouped literals;
    # neither is a conventional CSV number, and treating "NaN"/"Infinity" as
    # numeric would wrongly skip genuine text cells that happen to read that way.
    if "_" in candidate:
        return False
    # Accept thousands separators only in unambiguous three-digit groups.
    if _THOUSANDS.fullmatch(candidate):
        candidate = candidate.replace(",", "")
    if candidate.endswith("%"):
        candidate = candidate[:-1]
    try:
        number = Decimal(candidate)
    except InvalidOperation:
        return False
    return number.is_finite()


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
    # A single, whitespace-free base64/token-shaped blob (e.g. an AWS secret key
    # or standard base64) contains ``+``/``=`` and is long; natural-language text
    # never is. Requiring one of those symbols avoids dropping ordinary words or
    # slash-joined phrases, so this only preserves opaque secrets from disclosure.
    if (
        len(candidate) >= 20
        and ("+" in candidate or "=" in candidate)
        and re.fullmatch(r"[A-Za-z0-9+/=_-]+", candidate)
    ):
        return True
    # Non-finite numeric tokens (NaN/sNaN/inf/Infinity, any sign/case/payload)
    # are missing-value markers from numpy/pandas exports, not prose.
    # ``is_numeric`` rejects them (finiteness check) so they don't count as
    # numbers, but they must still be preserved rather than shipped to the
    # provider and rewritten.
    if _is_non_finite_token(candidate):
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
        is_selected, reason = _classify_column(name, values)
        report.append(
            ColumnSelection(
                index=index,
                name=name,
                selected=is_selected,
                reason=reason,
            )
        )
        if is_selected:
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


def _classify_column(name: str, values: Sequence[str]) -> tuple[bool, str]:
    normalized_name = re.sub(r"[\s-]+", "_", name.strip())
    if _SECRET_HEADER.search(normalized_name):
        return False, "credential-like header"
    if _IDENTIFIER_HEADER.fullmatch(normalized_name) or _IDENTIFIER_AFFIX.search(
        normalized_name
    ):
        return False, "identifier-like header"
    if not values:
        return False, "empty in selection sample"

    # is_machine_value subsumes is_numeric, so one pass yields both counts.
    numeric_count = 0
    machine_count = 0
    for value in values:
        if is_numeric(value):
            numeric_count += 1
            machine_count += 1
        elif is_machine_value(value):
            machine_count += 1
    if numeric_count / len(values) >= 0.8:
        return False, "numeric-like values"
    if machine_count / len(values) >= 0.8:
        return False, "identifier or machine-like values"

    # Natural-language evidence is any alphabetic word, even a short one (city
    # names and labels must not be mistaken for identifiers merely for brevity).
    if any(any(char.isalpha() for char in value) for value in values):
        return True, "text-like values"
    return False, "no text-like values"


__all__ = [
    "is_machine_value",
    "is_numeric",
    "resolve_columns",
    "should_translate_cell",
]
