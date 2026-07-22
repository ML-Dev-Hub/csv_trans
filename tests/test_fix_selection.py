"""Regression tests for two selection correctness bugs.

Bug A: numeric columns using ``NaN``/``inf`` as missing-value markers were
misclassified as text and their non-finite tokens were sent to the provider.
Bug B: ambiguous natural-language header terms (signature/salt/hash/checksum)
caused legitimate prose columns to be silently dropped as "credential-like".
"""

from csv_trans.selection import (
    _classify_column,
    is_machine_value,
    should_translate_cell,
)


# --- Bug A: non-finite numeric tokens are machine-like, not translatable ---


def test_numeric_column_with_nan_inf_markers_not_selected():
    selected, reason = _classify_column(
        "measurement", ["1.5", "2.3", "NaN", "4.1", "NaN"]
    )
    assert selected is False, reason
    assert reason != "text-like values"


def test_non_finite_tokens_not_translatable():
    for token in ("NaN", "nan", "inf", "Inf", "-inf", "+Infinity", "Infinity"):
        assert should_translate_cell(token) is False, token
        assert is_machine_value(token) is True, token


def test_genuine_prose_words_still_translatable():
    # Words that merely *contain* nan/inf substrings must be unaffected.
    for word in ("information", "finished", "infamous", "banana", "significant"):
        assert is_machine_value(word) is False, word
        assert should_translate_cell(word) is True, word


# --- Bug B: ambiguous header terms no longer drop prose columns ---


def test_signature_column_of_prose_is_selectable():
    selected, reason = _classify_column(
        "signature",
        ["Best regards, John — Sales", "Cheers, Mary from Support"],
    )
    assert selected is True, reason
    assert reason == "text-like values"


def test_salt_hash_checksum_columns_of_prose_are_selectable():
    for header, values in (
        ("salt", ["a pinch of salt", "sea salt to taste"]),
        ("hash", ["hash browns", "corned beef hash"]),
        ("checksum", ["please checksum the report", "checksum passed review"]),
    ):
        selected, reason = _classify_column(header, values)
        assert selected is True, f"{header}: {reason}"


# --- Credential headers must STILL be skipped ---


def test_credential_headers_still_skipped():
    for header in (
        "password",
        "api_key",
        "apikey",
        "client_secret",
        "secret",
        "access_token",
        "private_key",
        "signing_key",
    ):
        selected, reason = _classify_column(header, ["alpha value", "beta value"])
        assert selected is False, header
        assert reason == "credential-like header", f"{header}: {reason}"


# --- Value-based safeguard: opaque hash/salt VALUES still preserved ---


def test_opaque_hash_and_salt_values_still_skipped_by_value():
    # 32-char md5-style hex and a base64-shaped salt blob.
    assert is_machine_value("5f4dcc3b5aa765d61d8327deb882cf99") is True
    assert is_machine_value("d41d8cd98f00b204e9800998ecf8427e") is True
    assert is_machine_value("YWJjZGVmZ2hpamtsbW5vcHFy+/=") is True


def test_hash_valued_column_skipped_even_with_benign_header():
    selected, reason = _classify_column(
        "digest",
        [
            "5f4dcc3b5aa765d61d8327deb882cf99",
            "d41d8cd98f00b204e9800998ecf8427e",
            "e99a18c428cb38d5f260853678922e03",
        ],
    )
    assert selected is False, reason
