"""Lossless text segmentation used before provider requests."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(slots=True, frozen=True)
class TextSegment:
    """A source segment and whether it may be translated."""

    text: str
    translatable: bool = True


# Keep secrets out of provider prompts by protecting common machine-readable
# constructs.  This is intentionally conservative; explicit columns still win
# over column auto-detection, but placeholders and URLs remain byte-for-byte.
_PROTECTED = re.compile(
    r"(" 
    r"https?://[^\s<>]+|www\.[^\s<>]+|"
    r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"\{\{[^{}]+\}\}|\$\{[^{}]+\}|\{[^{}]+\}|"
    # Bound the mapping-key length: an unbounded ``[^)]+`` re-scans O(n^2) on
    # adversarial ``%(%(...`` runs, while a fixed {1,64} cap keeps it linear and
    # still protects normal keys, including the legal whitespace-bearing ones.
    r"%\([^)]{1,64}\)[#0 +\-]?[0-9]*(?:\.[0-9]+)?[diouxXeEfFgGcrs%]|"
    r"%[#0 +\-]?[0-9]*(?:\.[0-9]+)?[diouxXeEfFgGcrs%]|"
    r"<[^<>]+>"
    r")",
    re.IGNORECASE,
)


def split_text_lossless(text: str, max_chars: int) -> list[str]:
    """Split *text* without dropping or inventing a character.

    Whitespace boundaries are preferred near the end of each chunk.  Boundary
    whitespace belongs to the preceding chunk, which ensures that joining the
    chunks produced by an identity provider reconstructs the source exactly.
    """

    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    if not text:
        return [""]

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        hard_end = min(start + max_chars, length)
        if hard_end == length:
            chunks.append(text[start:])
            break

        # Prefer a boundary in the final third, but never emit an empty chunk.
        lower = start + max(1, max_chars * 2 // 3)
        boundary = -1
        for position in range(hard_end - 1, lower - 1, -1):
            if text[position].isspace():
                boundary = position + 1
                # Include an entire whitespace run where it fits.
                while boundary < hard_end and text[boundary].isspace():
                    boundary += 1
                break
        end = boundary if boundary > start else hard_end
        chunks.append(text[start:end])
        start = end
    return chunks


def segment_text(
    text: str, max_chars: int, *, preserve_placeholders: bool = True
) -> list[TextSegment]:
    """Return protected and size-bounded translation segments.

    Protected tokens never leave the process.  Leading and trailing whitespace
    are also protected locally so providers cannot silently strip CSV content.
    """

    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")

    coarse: list[TextSegment] = []
    # Cheap gate before the placeholder regex. It must never be False when a
    # real protected token exists; True with no actual match is harmless (the
    # regex finds nothing and the text stays one translatable segment).
    has_protected_marker = (
        "{" in text
        or "%" in text
        or "<" in text
        or "@" in text
        or "$" in text
        or "://" in text
        or "www." in text.casefold()
    )
    if preserve_placeholders and has_protected_marker:
        cursor = 0
        for match in _PROTECTED.finditer(text):
            if match.start() > cursor:
                coarse.append(TextSegment(text[cursor : match.start()], True))
            coarse.append(TextSegment(match.group(0), False))
            cursor = match.end()
        if cursor < len(text):
            coarse.append(TextSegment(text[cursor:], True))
    else:
        coarse.append(TextSegment(text, True))

    result: list[TextSegment] = []
    append = result.append
    for segment in coarse:
        if not segment.translatable:
            append(segment)
            continue
        segment_text_value = segment.text
        # A fitting segment needs no split; split_text_lossless would return
        # [text] unchanged.
        if len(segment_text_value) <= max_chars:
            chunks: tuple[str, ...] | list[str] = (segment_text_value,)
        else:
            chunks = split_text_lossless(segment_text_value, max_chars)
        for raw_chunk in chunks:
            # An all-whitespace chunk is simultaneously all leading and all
            # trailing whitespace. Treat it once as one protected segment;
            # slicing it through both paths below would duplicate it during
            # reconstruction (notably immediately before a protected token).
            if raw_chunk.isspace():
                append(TextSegment(raw_chunk, False))
                continue
            chunk_len = len(raw_chunk)
            leading_size = chunk_len - len(raw_chunk.lstrip())
            content_end = len(raw_chunk.rstrip())
            leading = raw_chunk[:leading_size]
            content = raw_chunk[leading_size:content_end]
            trailing = raw_chunk[content_end:]
            if leading:
                append(TextSegment(leading, False))
            if content:
                append(TextSegment(content, True))
            if trailing:
                append(TextSegment(trailing, False))
    return result or [TextSegment(text, False)]


def reconstruct_segments(
    segments: list[TextSegment], translations: dict[int, str]
) -> str:
    """Reassemble segments using translations keyed by segment index."""

    return "".join(
        [
            translations[index] if segment.translatable else segment.text
            for index, segment in enumerate(segments)
        ]
    )


__all__ = ["TextSegment", "reconstruct_segments", "segment_text", "split_text_lossless"]
