from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from memory.ids import canonical_json
from memory.ingestion.builders import (
    CHAT_TEXT_NORMALIZER,
    CHAT_TEXT_NORMALIZER_VERSION,
    NORMALIZE_TEXT_STAGE,
    TOOL_RESULT_TEXT_NORMALIZER,
    TOOL_RESULT_TEXT_NORMALIZER_VERSION,
    chat_content_hash,
    tool_content_hash,
)
from memory.ingestion.chunking import chunk_text
from memory.ingestion.protocols import ChatEvidenceReader, ToolEvidenceReader
from memory.models import ProcessorContext, ProcessorOutput, SegmentInput
from memory.pointers import POINTER_VERSION, EvidencePointer

if TYPE_CHECKING:
    from memory.config import MemoryConfig

logger = logging.getLogger(__name__)

_EMPTY_OUTPUT_HASH = hashlib.sha256(b"empty").hexdigest()


def _input_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _output_hash_from_segments(segments: list[SegmentInput]) -> str:
    payload = canonical_json([
        {
            "segment_type": s.segment_type,
            "ordinal": s.ordinal,
            "input_hash": s.input_hash,
        }
        for s in segments
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ChatTextNormalizer:
    name = CHAT_TEXT_NORMALIZER
    version = CHAT_TEXT_NORMALIZER_VERSION
    stages = frozenset({NORMALIZE_TEXT_STAGE})

    def __init__(self, *, chat_reader: ChatEvidenceReader, config: "MemoryConfig") -> None:
        self._reader = chat_reader
        self._config = config

    async def process(self, context: ProcessorContext) -> ProcessorOutput:
        import asyncio

        source = context.source
        source_version = context.source_version

        source_ref = source.source_ref
        if not source_ref.startswith("chat_message_id:"):
            raise ValueError(f"unexpected source_ref for chat normalizer: {source_ref!r}")
        try:
            message_id = int(source_ref.split(":", 1)[1])
        except (IndexError, ValueError) as exc:
            raise ValueError(f"cannot parse message_id from {source_ref!r}") from exc

        record = await asyncio.to_thread(
            self._reader.get_message_for_user, message_id, source.user_id
        )
        if record is None:
            raise RuntimeError(
                f"chat message {message_id} for user {source.user_id} not found during normalisation"
            )

        actual_hash = chat_content_hash(record)
        if actual_hash != source_version.content_hash:
            raise RuntimeError(
                f"content hash mismatch for chat message {message_id}: "
                f"expected {source_version.content_hash!r}, got {actual_hash!r}"
            )

        version_id = source_version.source_version_id
        segments: list[SegmentInput] = []
        chunk_size = self._config.text_segment_chars
        overlap = self._config.text_segment_overlap

        role = record.role
        content_type = record.content_type

        if content_type == "tool_calls":
            # Canonical JSON of tool_calls metadata from record.metadata
            raw = record.metadata.get("tool_calls")
            if raw is not None:
                tool_calls_text = canonical_json(raw)
                segments.extend(
                    _make_tool_calls_segments(
                        tool_calls_text,
                        version_id=version_id,
                        message_id=message_id,
                        chunk_size=chunk_size,
                        overlap=overlap,
                    )
                )
        elif content_type == "image_placeholder":
            # Image with no extractable text — produce a placeholder
            placeholder = f"[image message from {role}]"
            pointer = EvidencePointer(
                pointer_version=POINTER_VERSION,
                kind="chat_message",
                source_version_id=version_id,
                location={"chat_message_id": message_id},
            )
            segments.append(
                SegmentInput(
                    source_version_id=version_id,
                    segment_type="image_placeholder_text",
                    ordinal=0,
                    text=placeholder,
                    pointer=pointer,
                    normalizer_name=self.name,
                    normalizer_version=self.version,
                    input_hash=_input_hash(placeholder),
                )
            )
        elif role == "tool":
            content = record.content or ""
            if content:
                segments.extend(
                    _make_chat_tool_message_segments(
                        content,
                        version_id=version_id,
                        message_id=message_id,
                        chunk_size=chunk_size,
                        overlap=overlap,
                    )
                )
        else:
            content = record.content or ""
            if content:
                segments.extend(
                    _make_chat_text_segments(
                        content,
                        version_id=version_id,
                        message_id=message_id,
                        chunk_size=chunk_size,
                        overlap=overlap,
                    )
                )

        if not segments:
            output_json = {
                "source_version_id": version_id,
                "message_id": message_id,
                "segment_count": 0,
                "empty": True,
            }
            return ProcessorOutput(
                output_hash=_EMPTY_OUTPUT_HASH,
                output_json=output_json,
            )

        output_json = {
            "source_version_id": version_id,
            "message_id": message_id,
            "segment_count": len(segments),
        }
        output_hash = _output_hash_from_segments(segments)
        next_jobs = ()
        if (
            self._config.extraction_enabled
            and source.authority_class == "user_direct_statement"
            and any(segment.segment_type == "chat_text" for segment in segments)
        ):
            from memory.extraction.pipeline import extraction_job_request

            next_jobs = (
                extraction_job_request(
                    output_hash,
                    model_profile=self._config.extraction_model_profile,
                ),
            )
        return ProcessorOutput(
            output_hash=output_hash,
            output_json=output_json,
            new_segments=tuple(segments),
            next_jobs=next_jobs,
        )


class ToolResultTextNormalizer:
    name = TOOL_RESULT_TEXT_NORMALIZER
    version = TOOL_RESULT_TEXT_NORMALIZER_VERSION
    stages = frozenset({NORMALIZE_TEXT_STAGE})

    def __init__(self, *, tool_reader: ToolEvidenceReader, config: "MemoryConfig") -> None:
        self._reader = tool_reader
        self._config = config

    async def process(self, context: ProcessorContext) -> ProcessorOutput:
        import asyncio

        source = context.source
        source_version = context.source_version

        source_ref = source.source_ref
        # source_ref = "tool_result_ref:{user_id}:{tr_ref}"
        parts = source_ref.split(":", 2)
        if len(parts) != 3 or parts[0] != "tool_result_ref":
            raise ValueError(f"unexpected source_ref for tool normalizer: {source_ref!r}")
        tr_ref = parts[2]

        record = await asyncio.to_thread(
            self._reader.get_by_ref_for_user, tr_ref, source.user_id
        )
        if record is None:
            raise RuntimeError(
                f"tool result ref {tr_ref!r} for user {source.user_id} not found during normalisation"
            )

        actual_hash = tool_content_hash(record)
        if actual_hash != source_version.content_hash:
            raise RuntimeError(
                f"content hash mismatch for tool result {tr_ref!r}: "
                f"expected {source_version.content_hash!r}, got {actual_hash!r}"
            )

        version_id = source_version.source_version_id
        payload_text = record.payload_json
        chunk_size = self._config.text_segment_chars
        overlap = self._config.text_segment_overlap

        if not payload_text:
            output_json = {
                "source_version_id": version_id,
                "ref": tr_ref,
                "segment_count": 0,
                "empty": True,
            }
            return ProcessorOutput(output_hash=_EMPTY_OUTPUT_HASH, output_json=output_json)

        segments: list[SegmentInput] = []
        chunks = chunk_text(payload_text, chunk_size=chunk_size, overlap=overlap)

        for ordinal, chunk in enumerate(chunks):
            if len(chunks) == 1:
                pointer = EvidencePointer(
                    pointer_version=POINTER_VERSION,
                    kind="tool_result",
                    source_version_id=version_id,
                    location={"tool_result_ref": tr_ref},
                )
            else:
                pointer = EvidencePointer(
                    pointer_version=POINTER_VERSION,
                    kind="tool_result",
                    source_version_id=version_id,
                    location={
                        "tool_result_ref": tr_ref,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                    },
                )
            segments.append(
                SegmentInput(
                    source_version_id=version_id,
                    segment_type="tool_payload",
                    ordinal=ordinal,
                    text=chunk.text,
                    pointer=pointer,
                    normalizer_name=self.name,
                    normalizer_version=self.version,
                    input_hash=_input_hash(chunk.text),
                )
            )

        output_json = {
            "source_version_id": version_id,
            "ref": tr_ref,
            "segment_count": len(segments),
        }
        output_hash = _output_hash_from_segments(segments)
        next_jobs = ()
        if self._config.extraction_enabled and source.authority_class == "tool_api_result":
            from memory.extraction.pipeline import extraction_job_request

            next_jobs = (
                extraction_job_request(
                    output_hash,
                    model_profile=self._config.extraction_model_profile,
                ),
            )
        return ProcessorOutput(
            output_hash=output_hash,
            output_json=output_json,
            new_segments=tuple(segments),
            next_jobs=next_jobs,
        )


# ------------------------------------------------------------------
# Segment factory helpers

def _make_chat_text_segments(
    content: str,
    *,
    version_id: str,
    message_id: int,
    chunk_size: int,
    overlap: int,
) -> list[SegmentInput]:
    chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
    segments: list[SegmentInput] = []
    for ordinal, chunk in enumerate(chunks):
        if len(chunks) == 1:
            pointer = EvidencePointer(
                pointer_version=POINTER_VERSION,
                kind="chat_message",
                source_version_id=version_id,
                location={"chat_message_id": message_id},
            )
        else:
            pointer = EvidencePointer(
                pointer_version=POINTER_VERSION,
                kind="chat_span",
                source_version_id=version_id,
                location={
                    "chat_message_id": message_id,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                },
            )
        segments.append(
            SegmentInput(
                source_version_id=version_id,
                segment_type="chat_text",
                ordinal=ordinal,
                text=chunk.text,
                pointer=pointer,
                normalizer_name=CHAT_TEXT_NORMALIZER,
                normalizer_version=CHAT_TEXT_NORMALIZER_VERSION,
                input_hash=_input_hash(chunk.text),
            )
        )
    return segments


def _make_tool_calls_segments(
    tool_calls_text: str,
    *,
    version_id: str,
    message_id: int,
    chunk_size: int,
    overlap: int,
) -> list[SegmentInput]:
    chunks = chunk_text(tool_calls_text, chunk_size=chunk_size, overlap=overlap)
    segments: list[SegmentInput] = []
    for ordinal, chunk in enumerate(chunks):
        pointer = EvidencePointer(
            pointer_version=POINTER_VERSION,
            kind="chat_message",
            source_version_id=version_id,
            location={"chat_message_id": message_id},
        )
        segments.append(
            SegmentInput(
                source_version_id=version_id,
                segment_type="assistant_tool_calls",
                ordinal=ordinal,
                text=chunk.text,
                pointer=pointer,
                normalizer_name=CHAT_TEXT_NORMALIZER,
                normalizer_version=CHAT_TEXT_NORMALIZER_VERSION,
                input_hash=_input_hash(chunk.text),
            )
        )
    return segments


def _make_chat_tool_message_segments(
    content: str,
    *,
    version_id: str,
    message_id: int,
    chunk_size: int,
    overlap: int,
) -> list[SegmentInput]:
    chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
    segments: list[SegmentInput] = []
    for ordinal, chunk in enumerate(chunks):
        if len(chunks) == 1:
            pointer = EvidencePointer(
                pointer_version=POINTER_VERSION,
                kind="chat_message",
                source_version_id=version_id,
                location={"chat_message_id": message_id},
            )
        else:
            pointer = EvidencePointer(
                pointer_version=POINTER_VERSION,
                kind="chat_span",
                source_version_id=version_id,
                location={
                    "chat_message_id": message_id,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                },
            )
        segments.append(
            SegmentInput(
                source_version_id=version_id,
                segment_type="chat_tool_message",
                ordinal=ordinal,
                text=chunk.text,
                pointer=pointer,
                normalizer_name=CHAT_TEXT_NORMALIZER,
                normalizer_version=CHAT_TEXT_NORMALIZER_VERSION,
                input_hash=_input_hash(chunk.text),
            )
        )
    return segments
