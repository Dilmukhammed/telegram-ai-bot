from __future__ import annotations

from typing import Any, Mapping, Sequence

from memory.ids import canonical_json, make_assertion_id
from memory.resolution.schemas import (
    ASSERTION_SCHEMA_VERSION,
    PROPOSITION_KEY_VERSION,
    RESOLVER_VERSION,
    AssertionRecord,
    ResolvedArgument,
)
from memory.verification.adversarial import looks_like_correction


def is_correction_candidate(candidate: Mapping[str, Any]) -> bool:
    evidence = candidate.get("evidence") or ()
    payload = {
        "candidate_kind": candidate.get("candidate_kind") or candidate.get("kind") or "",
        "arguments": candidate.get("arguments") or (),
        "evidence": [
            {"relation": item.get("relation")}
            for item in evidence
            if isinstance(item, Mapping)
        ],
    }
    # kind may be stored as candidate_kind
    if "kind" not in payload and candidate.get("kind"):
        payload["candidate_kind"] = candidate["kind"]
    return looks_like_correction(
        {
            "candidate_kind": str(
                candidate.get("candidate_kind") or candidate.get("kind") or ""
            ),
            "arguments": list(candidate.get("arguments") or ()),
            "evidence": payload["evidence"],
        }
    )


def proposition_key(
    *,
    candidate_kind: str,
    schema_name: str,
    schema_version: str,
    resolved_arguments: Sequence[ResolvedArgument],
    attributes: Mapping[str, Any],
) -> str:
    payload = {
        "version": PROPOSITION_KEY_VERSION,
        "kind": candidate_kind,
        "schema_name": schema_name,
        "schema_version": schema_version,
        "arguments": [item.to_mapping() for item in sorted(resolved_arguments, key=lambda a: a.role)],
        "attributes": dict(attributes or {}),
    }
    return f"prop_{canonical_json(payload)}"


def cluster_key(*, schema_name: str) -> str:
    return f"cluster:{schema_name}"


def build_assertion(
    *,
    candidate: Mapping[str, Any],
    resolved_arguments: Sequence[ResolvedArgument],
    recorded_at: str,
) -> AssertionRecord:
    candidate_id = str(candidate["candidate_id"])
    kind = str(candidate.get("candidate_kind") or candidate.get("kind") or "")
    schema_name = str(candidate.get("schema_name") or "")
    schema_version = str(candidate.get("schema_version") or "1")
    attributes = dict(candidate.get("attributes") or {})
    prop = proposition_key(
        candidate_kind=kind,
        schema_name=schema_name,
        schema_version=schema_version,
        resolved_arguments=resolved_arguments,
        attributes=attributes,
    )
    return AssertionRecord(
        assertion_id=make_assertion_id(
            candidate_id=candidate_id,
            assertion_schema_version=ASSERTION_SCHEMA_VERSION,
            resolver_version=RESOLVER_VERSION,
        ),
        candidate_id=candidate_id,
        proposition_key=prop,
        cluster_key=cluster_key(schema_name=schema_name),
        candidate_kind=kind,
        schema_name=schema_name,
        schema_version=schema_version,
        resolved_arguments=tuple(resolved_arguments),
        attributes=attributes,
        polarity=str(candidate.get("polarity") or "unknown"),
        epistemic=dict(candidate.get("epistemic") or {}),
        temporal=dict(candidate["temporal"]) if isinstance(candidate.get("temporal"), Mapping) else None,
        observed_at=(
            str(candidate["temporal"].get("event_time"))
            if isinstance(candidate.get("temporal"), Mapping)
            and candidate["temporal"].get("event_time")
            else None
        ),
        status="active",
    )
