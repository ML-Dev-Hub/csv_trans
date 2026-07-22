"""Numerical-correctness hardening for the column-classification predicates.

These tests pin down the behaviour of ``is_numeric`` / ``is_machine_value`` /
``should_translate_cell`` across the full space of what a CSV cell can hold,
reasoning explicitly about ``decimal.Decimal`` parsing semantics.

Core invariants under test:
  * conventional numeric literals are numeric (and therefore skipped);
  * tokens Decimal accepts but a human would not call a plain number
    (underscore grouping, NaN/Infinity words) are classified the intended way;
  * numeric-ish tokens Decimal rejects ($12.50, 3/4, 1.2.3, hex/uuid) are still
    preserved as machine values, never shipped to a provider;
  * genuine prose that merely *contains* digits / inf / nan / e stays
    translatable;
  * non-finite markers -- crucially including signaling NaN (``sNaN``) -- are
    machine values, not translatable text.
"""

from __future__ import annotations

import unittest

from decimal import Decimal, InvalidOperation

try:
    import pytest
    from hypothesis import given, strategies as st
except ImportError as exc:  # stdlib-only CI runs skip this optional suite
    raise unittest.SkipTest(f"optional test dependency not installed: {exc.name}") from exc

from csv_trans.selection import (
    is_machine_value,
    is_numeric,
    should_translate_cell,
)


# --------------------------------------------------------------------------- #
# Explicit edge cases: conventional numeric literals -> numeric (skip)         #
# --------------------------------------------------------------------------- #

CONVENTIONAL_NUMBERS = [
    "0", "-0", "+0", "007", "42", "-42", "+42",
    "3.14", ".5", "5.", "-.5", "+.5",
    "1e5", "1E-3", "2.5e10", "-2.5E10", "1e1000", "1e-1000",
    "  12  ", "\t5\n", "  3.14  ",
    "123456789012345678901234567890",
    "0.00000000000000001",
]


@pytest.mark.parametrize("token", CONVENTIONAL_NUMBERS)
def test_conventional_numbers_are_numeric(token):
    assert is_numeric(token) is True, token
    assert is_machine_value(token) is True, token
    assert should_translate_cell(token) is False, token


def test_thousands_and_percent_are_numeric_ish_and_skipped():
    # Decimal rejects both surface forms; is_numeric normalises them.
    for token in ("1,000", "1,000,000", "1,234.56", "12%", "-5%", "100%"):
        assert is_numeric(token) is True, token
        assert should_translate_cell(token) is False, token


# --------------------------------------------------------------------------- #
# Tokens Decimal ACCEPTS but a human would not call a plain number             #
# --------------------------------------------------------------------------- #

def test_underscore_grouped_literals_are_not_numeric_but_are_machine():
    # Decimal("1_000") == 1000, but underscore grouping is not a conventional
    # CSV number. is_numeric rejects it; it still must be preserved (it has no
    # letters, so it is a machine value and skipped -- never translated).
    for token in ("1_000", "1_0.0_0", "1_", "_1", "1__0"):
        assert Decimal(token).is_finite()  # sanity: Decimal really accepts it
        assert is_numeric(token) is False, token
        assert should_translate_cell(token) is False, token


# --------------------------------------------------------------------------- #
# Non-finite markers -- NaN / sNaN / Infinity, all sign/case/payload variants  #
# --------------------------------------------------------------------------- #

NON_FINITE_TOKENS = [
    "NaN", "nan", "NAN", "-NaN", "+NaN",
    "sNaN", "snan", "SNAN", "-sNaN", "+sNaN",  # signaling NaN: the fix target
    "NaN123", "sNaN99",                        # NaN with payload
    "inf", "Inf", "INF", "-inf", "+inf",
    "Infinity", "infinity", "INFINITY", "-Infinity", "+Infinity",
]


@pytest.mark.parametrize("token", NON_FINITE_TOKENS)
def test_non_finite_markers_are_machine_not_translatable(token):
    # Never a "conventional number" (finiteness check rejects it) ...
    assert is_numeric(token) is False, token
    # ... but always a machine value that is preserved, not shipped out.
    assert is_machine_value(token) is True, token
    assert should_translate_cell(token) is False, token


def test_signaling_nan_regression():
    # Direct regression for the misclassification this change fixes: a bare
    # signaling NaN carries no digit, so it was missed by the nan|inf|infinity
    # regex AND by the alnum _CODE rule, and leaked to the provider.
    assert should_translate_cell("sNaN") is False
    assert is_machine_value("sNaN") is True


# --------------------------------------------------------------------------- #
# Numeric-ish tokens Decimal REJECTS -> still preserved as machine values      #
# --------------------------------------------------------------------------- #

NUMERIC_ISH_REJECTED_BY_DECIMAL = [
    "1.2.3",      # version / dotted number
    "$12.50",     # currency
    "3/4",        # fraction
    "1/2/2020",   # slashed
    "0x1F",       # hex literal
    "5f4dcc3b5aa765d61d8327deb882cf99",          # md5 hex
    "d41d8cd98f00b204e9800998ecf8427e",          # md5 hex
    "550e8400-e29b-41d4-a716-446655440000",      # uuid
    "2020-01-31",                                 # date
    "12:30:00",                                   # time-ish -> no alpha
    "SKU-1234", "ABC123", "A1",                    # alnum codes
]


@pytest.mark.parametrize("token", NUMERIC_ISH_REJECTED_BY_DECIMAL)
def test_numeric_ish_rejected_by_decimal_still_skipped(token):
    with pytest.raises(InvalidOperation):
        Decimal(token)  # sanity: Decimal really rejects the surface form
    assert is_machine_value(token) is True, token
    assert should_translate_cell(token) is False, token


# --------------------------------------------------------------------------- #
# Genuine prose that merely contains digits / inf / nan / e -> translatable    #
# --------------------------------------------------------------------------- #

PROSE = [
    "information", "finished", "infamous", "define", "plan",
    "banana", "significant", "inference", "confinement",
    "2 apples", "plan B", "3 blind mice", "top 10 list",
    "the quick brown fox", "Best regards, John",
    "Rindfleischetikettierungsueberwachung",
]


@pytest.mark.parametrize("token", PROSE)
def test_genuine_prose_is_translatable(token):
    assert is_numeric(token) is False, token
    assert is_machine_value(token) is False, token
    assert should_translate_cell(token) is True, token


# --------------------------------------------------------------------------- #
# Unicode digits: documented, consistent behaviour                            #
# --------------------------------------------------------------------------- #

def test_unicode_digit_runs_are_numeric_words_are_not():
    # Decimal accepts Unicode decimal digits (category Nd): Arabic-Indic and
    # full-width digit runs are genuine numbers and are treated as numeric.
    for token in ("٤", "١٢٣", "１２３"):
        assert is_numeric(token) is True, repr(token)
        assert should_translate_cell(token) is False, repr(token)
    # Decimal never accepts Unicode *letters*, so no real word is mislabelled
    # numeric via a Unicode code point.
    for word in ("café", "naïve", "中文", "مرحبا"):
        assert is_numeric(word) is False, repr(word)
        assert is_machine_value(word) is False, repr(word)
        assert should_translate_cell(word) is True, repr(word)


# --------------------------------------------------------------------------- #
# Property tests                                                               #
# --------------------------------------------------------------------------- #

@given(st.integers())
def test_property_integers_are_numeric_and_skipped(n):
    token = str(n)
    assert is_numeric(token) is True
    assert should_translate_cell(token) is False


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_property_finite_floats_are_numeric(x):
    token = repr(x)
    assert is_numeric(token) is True, token
    assert should_translate_cell(token) is False, token


# Scientific-notation numbers built from parts stay numeric.
@given(
    st.integers(-10_000, 10_000),
    st.integers(0, 9999),
    st.integers(-30, 30),
    st.sampled_from(["e", "E"]),
)
def test_property_scientific_notation_is_numeric(mant, frac, exp, e):
    token = f"{mant}.{frac}{e}{exp}"
    assert is_numeric(token) is True, token
    assert should_translate_cell(token) is False, token


# Whitespace padding must never change the classification (strip round-trip).
@given(
    st.sampled_from(CONVENTIONAL_NUMBERS + NON_FINITE_TOKENS + PROSE),
    st.text(alphabet=" \t\n", max_size=4),
    st.text(alphabet=" \t\n", max_size=4),
)
def test_property_surrounding_whitespace_is_invariant(token, left, right):
    base = token.strip()
    padded = f"{left}{base}{right}"
    assert is_numeric(padded) == is_numeric(base), repr(padded)
    assert is_machine_value(padded) == is_machine_value(base), repr(padded)
    assert should_translate_cell(padded) == should_translate_cell(base), repr(padded)


# Prose (ASCII letters + spaces + digits, containing at least one letter block)
# must stay translatable: it is neither numeric nor a machine value.
@given(
    st.lists(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789",
            min_size=1,
            max_size=8,
        ),
        min_size=1,
        max_size=4,
    )
)
def test_property_multiword_text_with_spaces_is_translatable(parts):
    token = " ".join(parts).strip()
    # Restrict to genuine multi-token prose: has a space and at least one letter.
    if " " not in token or not any(c.isalpha() for c in token):
        return
    assert is_numeric(token) is False, token
    # A space defeats every single-token machine pattern (_CODE, base64, uuid,
    # url, date, non-finite), and the alpha character defeats the numeric-only
    # fallback -> text stays translatable.
    assert is_machine_value(token) is False, token
    assert should_translate_cell(token) is True, token


# is_numeric is a strict subset of is_machine_value (the classifier relies on it).
@given(st.text(max_size=30))
def test_property_numeric_implies_machine(token):
    if is_numeric(token):
        assert is_machine_value(token) is True, token


# should_translate_cell is exactly "non-blank and not machine".
@given(st.text(max_size=30))
def test_property_should_translate_matches_definition(token):
    expected = bool(token.strip()) and not is_machine_value(token)
    assert should_translate_cell(token) is expected, token
