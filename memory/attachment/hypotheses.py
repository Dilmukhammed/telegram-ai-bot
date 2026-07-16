from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from memory.attachment.schemas import (
    ATTACHMENT_SCHEMA_VERSION,
    ATTACH_OPS,
    AttachmentHypothesis,
    ShortlistCandidate,
    DOMAIN_ALLOWED_OPS,
)


class AttachmentParseError(ValueError):
    pass


def parse_hypotheses(
    raw: str | Mapping[str, Any],
    *,
    shortlist_ids: Sequence[str],
) -> tuple[AttachmentHypothesis, ...]:
    data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    if data.get("schema_version") != ATTACHMENT_SCHEMA_VERSION:
        raise AttachmentParseError("unsupported schema_version")
    items = data.get("hypotheses")
    if not isinstance(items, list):
        raise AttachmentParseError("hypotheses must be a list")
    allowed = set(shortlist_ids)
    out: list[AttachmentHypothesis] = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op") or "")
        target_id = str(item.get("target_id") or "")
        if op not in ATTACH_OPS or op == "abstain":
            raise AttachmentParseError(f"invalid op: {op!r}")
        if target_id not in allowed:
            raise AttachmentParseError(f"target_id not in shortlist: {target_id!r}")
        out.append(
            AttachmentHypothesis(
                op=op,
                target_id=target_id,
                promote_preference=bool(item.get("promote_preference")),
                confidence=max(0.0, min(1.0, float(item.get("confidence") or 0.0))),
                reason_codes=tuple(
                    str(value) for value in (item.get("reason_codes") or [])[:8]
                    if str(value)
                ),
                evidence_ids=tuple(
                    str(value) for value in (item.get("evidence_ids") or [])[:12]
                    if str(value)
                ),
            )
        )
    return tuple(out)


def pick_unique_winner(
    hypotheses: Sequence[AttachmentHypothesis],
) -> AttachmentHypothesis | None:
    if not hypotheses:
        return None
    keys = {(h.op, h.target_id) for h in hypotheses}
    if len(keys) != 1:
        return None
    return hypotheses[0]


def select_compatible_hypotheses(
    hypotheses: Sequence[AttachmentHypothesis],
    *,
    max_items: int = 3,
) -> tuple[AttachmentHypothesis, ...]:
    """Select a deterministic, non-conflicting attachment set.

    Most semantic relations are functional for one analysis pass: competing
    targets for ``cuisine_of``/``instance_of`` are alternatives, not multiple
    facts. Group membership and corroboration may legitimately fan out.
    """
    fanout_ops = {"add_to_group", "corroborates"}
    ranked = sorted(
        hypotheses,
        key=lambda item: (-item.confidence, item.op, item.target_id),
    )
    selected: list[AttachmentHypothesis] = []
    seen_pairs: set[tuple[str, str]] = set()
    claimed_ops: set[str] = set()
    for item in ranked:
        pair = (item.op, item.target_id)
        if pair in seen_pairs:
            continue
        if item.op not in fanout_ops and item.op in claimed_ops:
            continue
        seen_pairs.add(pair)
        claimed_ops.add(item.op)
        selected.append(item)
        if len(selected) >= max(0, max_items):
            break
    return tuple(selected)


def filter_policy_compatible_hypotheses(
    hypotheses: Sequence[AttachmentHypothesis],
    *,
    shortlist: Sequence[ShortlistCandidate],
    attach_domains: Sequence[str],
) -> tuple[AttachmentHypothesis, ...]:
    """Enforce closed-world operation and domain compatibility before critics."""
    candidates = {item.target_id: item for item in shortlist}
    allowed_ops: set[str] = set()
    for domain in attach_domains:
        allowed_ops.update(DOMAIN_ALLOWED_OPS.get(str(domain), frozenset()))
    kept: list[AttachmentHypothesis] = []
    for hypothesis in hypotheses:
        candidate = candidates.get(hypothesis.target_id)
        if candidate is None:
            continue
        if allowed_ops and hypothesis.op not in allowed_ops:
            continue
        if candidate.op_hint and hypothesis.op != candidate.op_hint:
            continue
        kept.append(hypothesis)
    return tuple(kept)


def seed_hypotheses_from_shortlist(
    shortlist: Sequence[ShortlistCandidate],
) -> tuple[AttachmentHypothesis, ...]:
    """Generate recall-safe hypotheses from strong deterministic evidence."""
    seeded: list[AttachmentHypothesis] = []
    for candidate in shortlist:
        if not candidate.op_hint or candidate.entity_type == "person":
            continue
        metadata = dict(candidate.metadata or {})
        if metadata.get("edge_status") == "historical":
            continue
        graph_distance = metadata.get("graph_distance")
        vector_similarity = float(metadata.get("vector_similarity") or 0.0)
        strong = bool(
            metadata.get("curated")
            or metadata.get("exact_alias")
            or metadata.get("exact_term")
            or metadata.get("membership_evidence")
            or (graph_distance is not None and int(graph_distance) <= 1)
            or vector_similarity >= 0.85
            or candidate.score >= 0.85
        )
        if not strong:
            continue
        confidence = max(candidate.score, vector_similarity, 0.85)
        seeded.append(
            AttachmentHypothesis(
                op=candidate.op_hint,
                target_id=candidate.target_id,
                confidence=min(1.0, confidence),
                reason_codes=("deterministic_candidate_seed",),
                evidence_ids=tuple(
                    str(step.get("edge_id"))
                    for step in (metadata.get("graph_path") or ())
                    if isinstance(step, dict) and step.get("edge_id")
                ),
            )
        )
    return tuple(seeded)


def merge_hypothesis_sources(
    *sources: Sequence[AttachmentHypothesis],
) -> tuple[AttachmentHypothesis, ...]:
    by_key: dict[tuple[str, str], AttachmentHypothesis] = {}
    for source in sources:
        for item in source:
            key = (item.op, item.target_id)
            prior = by_key.get(key)
            if prior is None or item.confidence > prior.confidence:
                by_key[key] = item
    return tuple(by_key[key] for key in sorted(by_key))


def build_hypothesis_messages(
    *,
    context_statement: str,
    shortlist: Sequence[ShortlistCandidate],
    attach_domains: Sequence[str],
    context_pack: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    items = [
        {
            "target_id": c.target_id,
            "label": c.label,
            "entity_type": c.entity_type,
            "op_hint": c.op_hint,
            "score": c.score,
            "channel": c.channel,
            "evidence": dict(c.metadata or {}),
        }
        for c in shortlist
    ]
    return [
        {
            "role": "system",
            "content": (
                "You are the semantic analysis stage of a graph attachment engine. "
                "Evaluate taxonomy, groups, incoming/outgoing graph paths, polarity, "
                "and existing attachments. Propose graph attachment ops using ONLY "
                "target_id values from the shortlist. Embedding or lexical similarity "
                "is candidate discovery, never proof. When a shortlist item has op_hint, "
                "that operation is mandatory for that target: copy it exactly and never "
                "replace cuisine_of with inferred_preference. Return JSON with schema_version, "
                "hypotheses (1-5). Each hypothesis must include confidence, "
                "reason_codes and evidence_ids from the supplied context."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "statement": context_statement,
                    "domains": list(attach_domains),
                    "shortlist": items,
                    "context": dict(context_pack or {}),
                },
                ensure_ascii=False,
            ),
        },
    ]


def hypothesis_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "hypotheses"],
        "properties": {
            "schema_version": {"type": "string", "const": ATTACHMENT_SCHEMA_VERSION},
            "hypotheses": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "op",
                        "target_id",
                        "promote_preference",
                        "confidence",
                        "reason_codes",
                        "evidence_ids",
                    ],
                    "properties": {
                            "op": {"type": "string", "enum": sorted(ATTACH_OPS - {"abstain"})},
                        "target_id": {"type": "string"},
                        "promote_preference": {"type": "boolean"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "reason_codes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 8,
                        },
                        "evidence_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 12,
                        },
                    },
                },
            },
        },
    }
