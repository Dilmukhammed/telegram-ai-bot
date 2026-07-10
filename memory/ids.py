from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any, Mapping

NAMESPACE = "telegram-ai-bot.memory.v1"
_DIGEST_CHARS = 32


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(prefix: str, *parts: Any) -> str:
    payload = canonical_json([NAMESPACE, *parts])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]
    return f"{prefix}_{digest}"


def normalize_source_ref(source_ref: str) -> str:
    text = source_ref.strip()
    if not text:
        raise ValueError("source_ref must be non-empty")
    return text


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def normalize_workspace_path(path: str) -> str:
    text = path.strip().replace("\\", "/")
    if not text:
        raise ValueError("workspace_path must be non-empty")
    if "\x00" in text:
        raise ValueError("workspace_path must not contain NUL bytes")
    if text.startswith("/") or _WINDOWS_DRIVE.match(text):
        raise ValueError("workspace_path must be user-relative")
    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("workspace_path must not contain parent segments")
        if ":" in part:
            raise ValueError("workspace_path must not contain Windows alternate streams")
        parts.append(part)
    if not parts:
        raise ValueError("workspace_path must be non-empty")
    return "/".join(parts)


def pointer_hash(pointer_payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(pointer_payload).encode("utf-8")).hexdigest()


def make_source_id(*, user_id: int, source_type: str, source_ref: str) -> str:
    return _digest("msrc", user_id, source_type, normalize_source_ref(source_ref))


def make_source_version_id(*, source_id: str, content_hash: str) -> str:
    return _digest("msv", source_id, content_hash)


def make_segment_id(
    *,
    source_version_id: str,
    segment_type: str,
    ordinal: int,
    pointer_payload_hash: str,
    normalizer_version: str,
) -> str:
    return _digest(
        "mseg",
        source_version_id,
        segment_type,
        ordinal,
        pointer_payload_hash,
        normalizer_version,
    )


def make_job_id(
    *,
    source_version_id: str,
    stage: str,
    processor_name: str,
    processor_version: str,
    prompt_version: str | None,
    input_hash: str,
    config_hash: str,
) -> str:
    return _digest(
        "mjob",
        source_version_id,
        stage,
        processor_name,
        processor_version,
        prompt_version or "",
        input_hash,
        config_hash,
    )


def make_lineage_id(
    *,
    user_id: int,
    parent_kind: str,
    parent_id: str,
    child_kind: str,
    child_id: str,
    relation: str,
) -> str:
    return _digest(
        "mlin",
        user_id,
        parent_kind,
        parent_id,
        child_kind,
        child_id,
        relation,
    )


def make_mention_id(
    *,
    user_id: int,
    pointer_payload: Mapping[str, Any],
    mention_type: str,
    surface_text: str,
    extractor_name: str,
    extractor_version: str,
    prompt_version: str,
) -> str:
    return _digest(
        "mmen",
        user_id,
        pointer_payload,
        mention_type,
        surface_text,
        extractor_name,
        extractor_version,
        prompt_version,
    )


def make_candidate_id(
    *,
    user_id: int,
    semantic_payload: Mapping[str, Any],
    extractor_name: str,
    extractor_version: str,
    prompt_version: str,
) -> str:
    return _digest(
        "mcand",
        user_id,
        semantic_payload,
        extractor_name,
        extractor_version,
        prompt_version,
    )


def make_run_id() -> str:
    return f"mrun_{secrets.token_hex(16)}"


def content_hash_from_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
