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
    target_kind: str | None = None,
    target_id: str | None = None,
) -> str:
    parts: list[Any] = [
        "mjob",
        source_version_id,
        stage,
        processor_name,
        processor_version,
        prompt_version or "",
        input_hash,
        config_hash,
    ]
    if target_kind is not None or target_id is not None:
        parts.extend((target_kind or "", target_id or ""))
    return _digest(*parts)


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


def make_verdict_id(
    *,
    candidate_id: str,
    role: str,
    verifier_name: str,
    verifier_version: str,
    prompt_version: str,
    input_hash: str,
) -> str:
    return _digest(
        "mver",
        candidate_id,
        role,
        verifier_name,
        verifier_version,
        prompt_version,
        input_hash,
    )


def make_score_id(
    *,
    candidate_id: str,
    policy_version: str,
    verdict_set_hash: str,
) -> str:
    return _digest("mscore", candidate_id, policy_version, verdict_set_hash)


def make_entity_id(
    *,
    user_id: int,
    entity_type: str,
    identity_key: str,
    resolver_version: str,
) -> str:
    return _digest("ment", user_id, entity_type, identity_key, resolver_version)


def make_alias_id(
    *,
    user_id: int,
    entity_id: str,
    normalized_alias: str,
    source_mention_id: str | None,
) -> str:
    return _digest(
        "malias",
        user_id,
        entity_id,
        normalized_alias,
        source_mention_id or "",
    )


def make_mention_link_id(
    *,
    mention_id: str,
    entity_id: str,
    resolver_version: str,
) -> str:
    return _digest("mlink", mention_id, entity_id, resolver_version)


def make_assertion_id(
    *,
    candidate_id: str,
    assertion_schema_version: str,
    resolver_version: str,
) -> str:
    return _digest("ma", candidate_id, assertion_schema_version, resolver_version)


def make_belief_id(*, user_id: int, proposition_key: str) -> str:
    return _digest("mb", user_id, proposition_key)


def make_belief_revision_id(
    *,
    belief_id: str,
    input_set_hash: str,
    reconciliation_policy_version: str,
    utility_policy_version: str,
) -> str:
    return _digest(
        "mbr",
        belief_id,
        input_set_hash,
        reconciliation_policy_version,
        utility_policy_version,
    )


def make_resolution_verdict_id(
    *,
    mention_id: str,
    proposed_entity_id: str,
    role: str,
    critic_name: str,
    critic_version: str,
    prompt_version: str,
    input_hash: str,
) -> str:
    return _digest(
        "mrver",
        mention_id,
        proposed_entity_id,
        role,
        critic_name,
        critic_version,
        prompt_version,
        input_hash,
    )


def make_resolution_event_id(
    *,
    user_id: int,
    op: str,
    winner_entity_id: str,
    loser_entity_id: str,
    evidence_hash: str,
    resolver_version: str,
) -> str:
    return _digest(
        "mres",
        user_id,
        op,
        winner_entity_id,
        loser_entity_id,
        evidence_hash,
        resolver_version,
    )


def make_alias_equivalence_id(
    *,
    user_id: int,
    entity_type: str,
    normalized_alias_a: str,
    normalized_alias_b: str,
    source: str,
) -> str:
    left, right = sorted((normalized_alias_a, normalized_alias_b))
    return _digest("mequiv", user_id, entity_type, left, right, source)


def make_graph_node_id(
    *,
    user_id: int,
    node_type: str,
    source_record_id: str,
) -> str:
    return _digest("gn", user_id, node_type, source_record_id)


def make_graph_edge_id(
    *,
    user_id: int,
    belief_id: str,
    from_node_id: str,
    to_node_id: str,
    edge_type: str,
) -> str:
    return _digest("ge", user_id, belief_id, from_node_id, to_node_id, edge_type)


def make_graph_outbox_event_id(
    *,
    user_id: int,
    belief_id: str,
    operation: str,
    payload_hash: str,
) -> str:
    return _digest("go", user_id, belief_id, operation, payload_hash)


def make_summary_id(
    *,
    user_id: int,
    summary_type: str,
    target_id: str,
    input_hash: str,
    prompt_version: str,
) -> str:
    return _digest(
        "gsum",
        user_id,
        summary_type,
        target_id,
        input_hash,
        prompt_version,
    )


def make_community_id(
    *,
    user_id: int,
    community_type: str,
    seed_node_id: str,
    detector_version: str,
    input_hash: str,
) -> str:
    return _digest(
        "gcomm",
        user_id,
        community_type,
        seed_node_id,
        detector_version,
        input_hash,
    )


def make_summary_dirty_id(
    *,
    user_id: int,
    summary_type: str,
    target_id: str,
) -> str:
    return _digest("gsdirty", user_id, summary_type, target_id)


def make_attachment_event_id(
    *,
    user_id: int,
    op: str,
    source_entity_id: str,
    target_entity_id: str,
    evidence_hash: str,
    attachment_version: str,
) -> str:
    return _digest(
        "matt",
        user_id,
        op,
        source_entity_id,
        target_entity_id,
        evidence_hash,
        attachment_version,
    )


def make_attachment_negative_id(
    *,
    user_id: int,
    source_entity_id: str,
    op: str,
    target_entity_id: str,
) -> str:
    return _digest("mattneg", user_id, source_entity_id, op, target_entity_id)


def make_attachment_dirty_id(
    *,
    user_id: int,
    belief_id: str,
) -> str:
    return _digest("mattdirty", user_id, belief_id)


def make_run_id() -> str:
    return f"mrun_{secrets.token_hex(16)}"


def content_hash_from_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
