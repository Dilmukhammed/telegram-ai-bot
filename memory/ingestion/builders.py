from __future__ import annotations

import hashlib

from memory.ids import canonical_json
from memory.ingestion.models import ChatEvidenceRecord, ToolEvidenceRecord
from memory.models import JobRequest, SourceInput
from memory.pointers import POINTER_VERSION, EvidencePointer

CHAT_TEXT_NORMALIZER = "chat_text_normalizer"
CHAT_TEXT_NORMALIZER_VERSION = "1"
TOOL_RESULT_TEXT_NORMALIZER = "tool_result_text_normalizer"
TOOL_RESULT_TEXT_NORMALIZER_VERSION = "1"
NORMALIZE_TEXT_STAGE = "normalize_text"

_SCHEMA_VERSION = 1


class UnsupportedRoleError(ValueError):
    pass


def chat_content_hash(record: ChatEvidenceRecord) -> str:
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "role": record.role,
        "content": record.content,
        "content_type": record.content_type,
        "tool_call_id": record.tool_call_id,
        "tool_name": record.tool_name,
        "metadata": dict(record.metadata),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _chat_authority(role: str, content_type: str) -> str:
    if role == "user":
        return "user_direct_statement"
    if role == "assistant":
        if content_type == "tool_calls":
            return "assistant_tool_invocation"
        return "assistant_generated"
    if role == "tool":
        return "conversation_tool_message"
    raise UnsupportedRoleError(f"unsupported role: {role!r}")


def _tool_authority(payload_kind: str) -> str:
    if payload_kind == "result":
        return "tool_api_result"
    if payload_kind == "arguments":
        return "assistant_tool_arguments"
    return "legacy_tool_archive_unknown"


def chat_source_input(record: ChatEvidenceRecord) -> SourceInput:
    authority = _chat_authority(record.role, record.content_type)
    content_hash = chat_content_hash(record)
    source_ref = f"chat_message_id:{record.message_id}"
    pointer = EvidencePointer(
        pointer_version=POINTER_VERSION,
        kind="chat_message",
        source_version_id="pending",
        location={"chat_message_id": record.message_id},
    )
    source_metadata: dict = {
        "session_id": record.session_id,
        "seq": record.seq,
        "role": record.role,
        "content_type": record.content_type,
        "tool_call_id": record.tool_call_id,
        "tool_name": record.tool_name,
    }
    if record.content_type == "image_placeholder":
        source_metadata["unresolved_media"] = True
    for key in ("telegram_message_id", "telegram_chat_id"):
        if key in record.metadata:
            source_metadata[key] = record.metadata[key]
    return SourceInput(
        user_id=record.user_id,
        source_type="chat_message",
        source_ref=source_ref,
        authority_class=authority,
        content_hash=content_hash,
        pointer=pointer,
        session_id=record.session_id,
        occurred_at=record.source_at,
        source_metadata=source_metadata,
    )


def chat_job_request(content_hash: str, *, config_hash: str = "") -> JobRequest:
    return JobRequest(
        stage=NORMALIZE_TEXT_STAGE,
        processor_name=CHAT_TEXT_NORMALIZER,
        processor_version=CHAT_TEXT_NORMALIZER_VERSION,
        input_hash=content_hash,
        config_hash=config_hash,
    )


def tool_content_hash(record: ToolEvidenceRecord) -> str:
    return hashlib.sha256(record.payload_json.encode("utf-8")).hexdigest()


def tool_source_input(record: ToolEvidenceRecord) -> SourceInput:
    authority = _tool_authority(record.payload_kind)
    content_hash = tool_content_hash(record)
    source_ref = f"tool_result_ref:{record.user_id}:{record.ref}"
    pointer = EvidencePointer(
        pointer_version=POINTER_VERSION,
        kind="tool_result",
        source_version_id="pending",
        location={"tool_result_ref": record.ref},
    )
    source_metadata: dict = {
        "display_ref": record.display_ref,
        "run_id": record.run_id,
        "tool_name": record.tool_name,
        "turn": record.turn,
        "kind": record.payload_kind,
        "ok": record.ok,
        "cached": record.cached,
        "untrusted_external_content": True,
    }
    return SourceInput(
        user_id=record.user_id,
        source_type="tool_result",
        source_ref=source_ref,
        authority_class=authority,
        content_hash=content_hash,
        pointer=pointer,
        occurred_at=record.created_at,
        source_metadata=source_metadata,
    )


def tool_job_request(content_hash: str, *, config_hash: str = "") -> JobRequest:
    return JobRequest(
        stage=NORMALIZE_TEXT_STAGE,
        processor_name=TOOL_RESULT_TEXT_NORMALIZER,
        processor_version=TOOL_RESULT_TEXT_NORMALIZER_VERSION,
        input_hash=content_hash,
        config_hash=config_hash,
    )
