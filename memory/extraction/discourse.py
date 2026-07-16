from __future__ import annotations

from typing import Any

from memory.extraction.schemas import ExtractionResult


def normalize_discourse(
    result: ExtractionResult,
    *,
    segment_text: str,
    prior_segments: Any = (),
) -> ExtractionResult:
    """Pass-through: schema-specific discourse heuristics removed."""
    del segment_text, prior_segments
    return result


def cross_segment_ref(segment_id: str, mention_type: str) -> str:
    return f"$seg:{segment_id}:{mention_type}"


def parse_cross_segment_ref(value: str) -> tuple[str, str] | None:
    if not value.startswith("$seg:"):
        return None
    body = value[len("$seg:") :]
    segment_id, separator, mention_type = body.rpartition(":")
    if not separator or not segment_id or not mention_type:
        return None
    return segment_id, mention_type
