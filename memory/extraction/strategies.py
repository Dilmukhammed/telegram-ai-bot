from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from memory.extraction.generation import ModelGeneration
from memory.extraction.parser import ExtractionParseError, parse_extraction_output
from memory.extraction.prompts import build_extraction_messages
from memory.extraction.schemas import ExtractionResult
from memory.ids import canonical_json


@dataclass(frozen=True)
class ExtractionGeneration:
    result: ExtractionResult
    trace: dict[str, Any]


async def _model_generate(
    model: Any,
    messages: list[dict[str, str]],
) -> ModelGeneration:
    generate_with_trace = getattr(model, "generate_with_trace", None)
    if callable(generate_with_trace):
        generated = await generate_with_trace(messages, structured_schema="extraction")
        if isinstance(generated, ModelGeneration):
            return generated
    text = await model.generate(messages, structured_schema="extraction")
    return ModelGeneration(
        text=text,
        metadata={
            "model_profile": getattr(model, "model_profile", None),
            "response_format": "unknown",
        },
    )


async def _generate_valid(
    model: Any,
    *,
    messages: list[dict[str, str]],
    segment_text: str,
    timezone: str | None = None,
) -> ExtractionGeneration:
    generated = await _model_generate(model, messages)
    raw = generated.text
    trace: dict[str, Any] = {
        "prompt_hash": hashlib.sha256(
            canonical_json(messages).encode("utf-8")
        ).hexdigest(),
        "initial": {**dict(generated.metadata), "raw_response": raw},
        "repair": None,
    }
    try:
        result = parse_extraction_output(
            raw,
            segment_text=segment_text,
            allow_candidates=True,
            timezone=timezone,
        )
        return ExtractionGeneration(result=result, trace=trace)
    except ExtractionParseError as first_error:
        trace["initial"]["parse_error"] = str(first_error)
        repair_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Your JSON was rejected by the strict parser: "
                    f"{first_error}. Return the complete corrected JSON object only. "
                    "Keep every evidence quote grounded in segment_text."
                ),
            },
        ]
        repaired = await _model_generate(model, repair_messages)
        trace["repair"] = {
            **dict(repaired.metadata),
            "prompt_hash": hashlib.sha256(
                canonical_json(repair_messages).encode("utf-8")
            ).hexdigest(),
            "raw_response": repaired.text,
        }
        result = parse_extraction_output(
            repaired.text,
            segment_text=segment_text,
            allow_candidates=True,
            timezone=timezone,
        )
        return ExtractionGeneration(result=result, trace=trace)


async def generate_segment_extraction(
    model: Any,
    *,
    segment_text: str,
    source_type: str,
    authority_class: str,
    occurred_at: str | None,
    timezone: str,
    prior_segments: list[dict[str, str]] | None = None,
) -> ExtractionResult:
    generated = await generate_segment_extraction_with_trace(
        model,
        segment_text=segment_text,
        source_type=source_type,
        authority_class=authority_class,
        occurred_at=occurred_at,
        timezone=timezone,
        prior_segments=prior_segments,
    )
    return generated.result


async def generate_segment_extraction_with_trace(
    model: Any,
    *,
    segment_text: str,
    source_type: str,
    authority_class: str,
    occurred_at: str | None,
    timezone: str,
    prior_segments: list[dict[str, str]] | None = None,
) -> ExtractionGeneration:
    messages = build_extraction_messages(
        segment_text=segment_text,
        source_type=source_type,
        authority_class=authority_class,
        occurred_at=occurred_at,
        timezone=timezone,
        prior_segments=prior_segments or [],
    )
    return await _generate_valid(
        model,
        messages=messages,
        segment_text=segment_text,
        timezone=timezone,
    )
