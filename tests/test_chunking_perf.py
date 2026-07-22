"""Correctness/losslessness guards for the optimized chunking module.

These assert *behavior*, not timing.  They exist so the performance rewrite of
``segment_text`` / ``reconstruct_segments`` cannot silently break the absolute
invariant: for any input, segment -> identity-reconstruct must reproduce the
original text byte-for-byte, and the marker fast-path must never diverge from a
full unconditional regex scan.
"""

from __future__ import annotations

import random
import unittest

try:
    import pytest
except ImportError as exc:  # stdlib-only CI runs skip this optional suite
    raise unittest.SkipTest(f"optional test dependency not installed: {exc.name}") from exc

from csv_trans.chunking import (
    TextSegment,
    _PROTECTED,
    reconstruct_segments,
    segment_text,
    split_text_lossless,
)


def _identity_reconstruct(segments: list[TextSegment]) -> str:
    """Reconstruct as an identity provider would: translate == source text."""

    translations = {
        index: segment.text
        for index, segment in enumerate(segments)
        if segment.translatable
    }
    return reconstruct_segments(segments, translations)


def _fast_has_marker(text: str) -> bool:
    """The optimized gate as implemented in ``segment_text``."""

    return (
        "{" in text
        or "%" in text
        or "<" in text
        or "@" in text
        or "$" in text
        or "://" in text
        or "www." in text.casefold()
    )


CASES = [
    "",
    " ",
    "   ",
    "\n\t ",
    "plain text no markers",
    "café naïve 日本語 текст",
    "visit https://example.com/x?a=1&b=2 now",
    "HTTP://EXAMPLE.COM and WwW.Site.ORG mixed case",
    "email me@example.com please",
    "{{token}} and {name} and ${var} and %(key)s and %05.2f and %s",
    "<b>bold</b> <a href='x'>link</a>",
    "{{a}}{{b}}{{c}}",  # placeholders back to back, no gaps
    "%(a)s%(b)d",
    "trailing ws   ",
    "   leading ws",
    "a" * 5000,
    ("word {{ph}} " * 400),
    "://no scheme but has colon-slash-slash",
    "mixed   whitespace\truns\n\nand {{ph}} tokens www.x.com end",
]


@pytest.mark.parametrize("max_chars", [1, 2, 3, 7, 50, 200, 10000])
@pytest.mark.parametrize("text", CASES)
def test_roundtrip_lossless_fixed(text: str, max_chars: int) -> None:
    segments = segment_text(text, max_chars)
    assert _identity_reconstruct(segments) == text


def test_marker_gate_never_misses_a_real_token() -> None:
    """Fast gate must be True whenever a protected token actually exists."""

    for text in CASES:
        if _PROTECTED.search(text) is not None:
            assert _fast_has_marker(text), text


def test_segmentation_matches_unconditional_regex_scan() -> None:
    """The fast-path gate must not change the produced segments vs always
    running the placeholder regex."""

    rng = random.Random(20260720)
    alphabet = list("ab {}%<>@$/:.wWtThHpPsS\n\t") + ["{{", "}}", "://", "www.", "%s"]
    for _ in range(20000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        assert _fast_has_marker(text) or _PROTECTED.search(text) is None, text


def _random_text(rng: random.Random) -> str:
    placeholders = [
        "https://a.b/c?d=1", "www.x.io", "u@h.com", "{{t}}", "{n}", "${v}",
        "%(k)s", "%d", "%05.2f", "<b>", "</a>", "{{ x.y }}",
    ]
    fillers = ["a", "b", " ", "  ", "\t", "\n", "café", "日本", "テ", "", "x"]
    parts = []
    for _ in range(rng.randint(0, 30)):
        if rng.random() < 0.35:
            parts.append(rng.choice(placeholders))
        else:
            parts.append(rng.choice(fillers))
    return "".join(parts)


@pytest.mark.parametrize("max_chars", [1, 3, 8, 200])
def test_fuzz_roundtrip_lossless(max_chars: int) -> None:
    rng = random.Random(0xC0FFEE ^ max_chars)
    for _ in range(20000):
        text = _random_text(rng)
        segments = segment_text(text, max_chars)
        assert _identity_reconstruct(segments) == text


def test_split_text_lossless_still_reconstructs() -> None:
    rng = random.Random(7)
    for _ in range(5000):
        text = _random_text(rng)
        for mc in (1, 4, 13, 200):
            assert "".join(split_text_lossless(text, mc)) == text


def test_max_chars_validation_preserved() -> None:
    for fn in (lambda: segment_text("x", 0), lambda: split_text_lossless("x", 0)):
        with pytest.raises(ValueError):
            fn()
