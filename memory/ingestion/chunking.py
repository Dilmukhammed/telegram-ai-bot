from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    text: str
    char_start: int
    char_end: int


def chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[TextChunk]:
    """Split text into fixed code-point windows with overlap.

    Preserves the exact bytes of `text` — no trimming, collapsing, or
    unicode normalisation.  Short texts produce a single chunk.  Empty
    text returns an empty list so callers never fabricate prose.
    """
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be less than chunk_size")

    length = len(text)
    if length <= chunk_size:
        return [TextChunk(text=text, char_start=0, char_end=length)]

    chunks: list[TextChunk] = []
    step = chunk_size - overlap
    start = 0
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(TextChunk(text=text[start:end], char_start=start, char_end=end))
        if end == length:
            break
        start += step
    return chunks
