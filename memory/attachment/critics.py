from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, Protocol, runtime_checkable

from memory.attachment.hypotheses import AttachmentParseError, parse_hypotheses
from memory.attachment.schemas import (
    ATTACHMENT_SCHEMA_VERSION,
    ATTACHMENT_PROMPT_VERSION,
    AttachmentHypothesis,
    LayerVerdict,
    ShortlistCandidate,
)
from memory.structured_output import StructuredOutputModel


@runtime_checkable
class AttachmentCommitteeModel(Protocol):
    model_profile: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = None,
    ) -> str: ...


class LLMAttachmentCommitteeModel:
    def __init__(self, client: Any, *, model_profile: str, max_tokens: int = 1536) -> None:
        self._transport = StructuredOutputModel(
            client,
            model_profile=model_profile,
            max_tokens=max_tokens,
        )
        self.model_profile = model_profile

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = None,
    ) -> str:
        generated = await self._transport.generate(
            messages,
            schema_name=structured_schema,
            schema=_attachment_output_schema(structured_schema) if structured_schema else None,
        )
        return generated.text


def _attachment_output_schema(name: str) -> dict[str, Any]:
    if name == "attachment_hypothesis":
        from memory.attachment.hypotheses import hypothesis_output_schema

        return hypothesis_output_schema()
    if name == "attachment_set_critic":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "verdicts"],
            "properties": {
                "schema_version": {"type": "string", "const": ATTACHMENT_SCHEMA_VERSION},
                "verdicts": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["op", "target_id", "verdict"],
                        "properties": {
                            "op": {"type": "string"},
                            "target_id": {"type": "string"},
                            "verdict": {
                                "type": "string",
                                "enum": ["supported", "contradicted", "insufficient", "malformed"],
                            },
                        },
                    },
                },
            },
        }
    if name == "attachment_alt":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "preferred", "op", "target_id"],
            "properties": {
                "schema_version": {"type": "string", "const": ATTACHMENT_SCHEMA_VERSION},
                "preferred": {"type": "boolean"},
                "op": {"type": "string"},
                "target_id": {"type": "string"},
            },
        }
    verdicts = {
        "attachment_support": ["supported", "insufficient", "malformed"],
        "attachment_adversarial": ["supported", "contradicted", "insufficient", "malformed"],
        "attachment_cluster": ["ok", "veto", "malformed"],
    }
    if name in verdicts:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "verdict"],
            "properties": {
                "schema_version": {"type": "string", "const": ATTACHMENT_SCHEMA_VERSION},
                "verdict": {"type": "string", "enum": verdicts[name]},
            },
        }
    raise ValueError(f"unknown attachment structured schema: {name}")


def _parse_verdict(raw: str | Mapping[str, Any]) -> dict[str, Any]:
    data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    if data.get("schema_version") != ATTACHMENT_SCHEMA_VERSION:
        raise AttachmentParseError("unsupported schema_version")
    return data


async def run_hypothesis_layer(
    model: AttachmentCommitteeModel | None,
    *,
    context_statement: str,
    shortlist: Sequence[ShortlistCandidate],
    attach_domains: Sequence[str],
    context_pack: Mapping[str, Any] | None = None,
) -> tuple[tuple[AttachmentHypothesis, ...], LayerVerdict, int]:
    from memory.attachment.hypotheses import build_hypothesis_messages

    if model is None:
        return (), LayerVerdict("L4", "malformed", {"error": "model_unavailable"}), 0
    try:
        raw = await model.generate(
            build_hypothesis_messages(
                context_statement=context_statement,
                shortlist=shortlist,
                attach_domains=attach_domains,
                context_pack=context_pack,
            ),
            structured_schema="attachment_hypothesis",
        )
        hyps = parse_hypotheses(
            raw, shortlist_ids=[c.target_id for c in shortlist]
        )
        return hyps, LayerVerdict("L4", "ok", {"count": len(hyps)}), 1
    except (AttachmentParseError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
        return (), LayerVerdict("L4", "malformed", {"error": str(exc)[:300]}), 1


async def run_support_critic(
    model: AttachmentCommitteeModel | None,
    *,
    hypothesis: AttachmentHypothesis,
    context_statement: str,
    context_pack: Mapping[str, Any] | None = None,
) -> tuple[LayerVerdict, int]:
    if model is None:
        return LayerVerdict("L5", "insufficient", {"error": "model_unavailable"}), 0
    messages = [
        {
            "role": "system",
            "content": (
                "Return JSON {schema_version, verdict} where verdict is "
                "supported|insufficient|malformed. Do not invent targets."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "statement": context_statement,
                    "hypothesis": asdict(hypothesis),
                    "evidence_context": dict(context_pack or {}),
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = await model.generate(messages, structured_schema="attachment_support")
        data = _parse_verdict(raw)
        verdict = str(data.get("verdict") or "malformed")
        if verdict not in {"supported", "insufficient", "malformed"}:
            verdict = "malformed"
        return LayerVerdict("L5", verdict), 1
    except Exception as exc:  # noqa: BLE001
        return LayerVerdict("L5", "malformed", {"error": str(exc)[:300]}), 1


async def run_adversarial_critic(
    model: AttachmentCommitteeModel | None,
    *,
    hypothesis: AttachmentHypothesis,
    context_statement: str,
    context_pack: Mapping[str, Any] | None = None,
) -> tuple[LayerVerdict, int]:
    """supported = attack failed / link ok; contradicted = reject (matches resolution critics)."""
    if model is None:
        return LayerVerdict("L6", "insufficient", {"error": "model_unavailable"}), 0
    messages = [
        {
            "role": "system",
            "content": (
                "Attack the proposed attachment. Return JSON {schema_version, verdict} "
                "where verdict is supported|contradicted|insufficient|malformed."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "statement": context_statement,
                    "hypothesis": asdict(hypothesis),
                    "evidence_context": dict(context_pack or {}),
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = await model.generate(messages, structured_schema="attachment_adversarial")
        data = _parse_verdict(raw)
        verdict = str(data.get("verdict") or "malformed")
        if verdict not in {"supported", "contradicted", "insufficient", "malformed"}:
            verdict = "malformed"
        return LayerVerdict("L6", verdict), 1
    except Exception as exc:  # noqa: BLE001
        return LayerVerdict("L6", "malformed", {"error": str(exc)[:300]}), 1


async def run_alt_hypothesis_critic(
    model: AttachmentCommitteeModel | None,
    *,
    hypothesis: AttachmentHypothesis,
    shortlist: Sequence[ShortlistCandidate],
    context_statement: str,
    context_pack: Mapping[str, Any] | None = None,
) -> tuple[LayerVerdict, int]:
    if model is None:
        return LayerVerdict("L7", "ok"), 0
    items = [{"target_id": c.target_id, "label": c.label} for c in shortlist]
    messages = [
        {
            "role": "system",
            "content": (
                "Pick best competing target/op from shortlist only. Return JSON "
                "{schema_version, preferred, op, target_id} where preferred is bool."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "statement": context_statement,
                    "current": asdict(hypothesis),
                    "shortlist": items,
                    "evidence_context": dict(context_pack or {}),
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = await model.generate(messages, structured_schema="attachment_alt")
        data = _parse_verdict(raw)
        if data.get("preferred") and (
            str(data.get("target_id")) != hypothesis.target_id
            or str(data.get("op")) != hypothesis.op
        ):
            return (
                LayerVerdict(
                    "L7",
                    "prefer_other",
                    {
                        "op": data.get("op"),
                        "target_id": data.get("target_id"),
                    },
                ),
                1,
            )
        return LayerVerdict("L7", "ok"), 1
    except Exception as exc:  # noqa: BLE001
        return LayerVerdict("L7", "malformed", {"error": str(exc)[:300]}), 1


async def run_cluster_critic(
    model: AttachmentCommitteeModel | None,
    *,
    hypothesis: AttachmentHypothesis,
    context_statement: str,
    context_pack: Mapping[str, Any] | None = None,
) -> tuple[LayerVerdict, int]:
    if model is None:
        return LayerVerdict("L8", "ok"), 0
    messages = [
        {
            "role": "system",
            "content": (
                "Taxonomy/consistency veto only. Return JSON {schema_version, verdict} "
                "where verdict is ok|veto|malformed."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "statement": context_statement,
                    "hypothesis": asdict(hypothesis),
                    "evidence_context": dict(context_pack or {}),
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = await model.generate(messages, structured_schema="attachment_cluster")
        data = _parse_verdict(raw)
        verdict = str(data.get("verdict") or "malformed")
        if verdict not in {"ok", "veto", "malformed"}:
            verdict = "malformed"
        return LayerVerdict("L8", verdict), 1
    except Exception as exc:  # noqa: BLE001
        return LayerVerdict("L8", "malformed", {"error": str(exc)[:300]}), 1


def accept_from_layers(
    *,
    winner: AttachmentHypothesis | None,
    layers: Sequence[LayerVerdict],
) -> tuple[bool, str | None]:
    if winner is None:
        return False, "no_unique_winner"
    by_layer = {layer.layer: layer for layer in layers}
    l5 = by_layer.get("L5")
    if l5 is None or l5.verdict != "supported":
        return False, f"support_{l5.verdict if l5 else 'missing'}"
    l6 = by_layer.get("L6")
    if l6 is not None and l6.verdict == "contradicted":
        return False, "adversarial_contradicted"
    if l6 is not None and l6.verdict not in {"supported", "ok"}:
        if l6.verdict in {"insufficient", "malformed"}:
            return False, f"adversarial_{l6.verdict}"
    l7 = by_layer.get("L7")
    if l7 is not None and l7.verdict == "prefer_other":
        return False, "alt_hypothesis_preferred"
    l8 = by_layer.get("L8")
    if l8 is not None and l8.verdict == "veto":
        return False, "cluster_veto"
    return True, None


async def run_set_critic(
    model: AttachmentCommitteeModel | None,
    *,
    layer: str,
    hypotheses: Sequence[AttachmentHypothesis],
    context_statement: str,
    context_pack: Mapping[str, Any] | None = None,
    adversarial: bool,
) -> tuple[dict[tuple[str, str], LayerVerdict], int]:
    """Critique a complete attachment set in one bounded LLM call."""
    keys = {(item.op, item.target_id) for item in hypotheses}
    if not hypotheses:
        return {}, 0
    if model is None:
        return {
            key: LayerVerdict(layer, "insufficient", {"error": "model_unavailable"})
            for key in keys
        }, 0
    allowed = (
        {"supported", "contradicted", "insufficient", "malformed"}
        if adversarial
        else {"supported", "insufficient", "malformed"}
    )
    messages = [
        {
            "role": "system",
            "content": (
                "Critique every attachment independently and also consider conflicts "
                "inside the complete set. Return JSON {schema_version, verdicts}; "
                "each verdict item must copy op and target_id exactly and use "
                + (
                    "supported|contradicted|insufficient|malformed. This is an "
                    "adversarial check: use supported when the attack fails and the "
                    "provided graph/community evidence is coherent; insufficient is "
                    "only for genuinely missing evidence."
                    if adversarial
                    else
                    "supported|insufficient|malformed. For add_to_group, strong semantic "
                    "community fit (for example high vector similarity plus compatible "
                    "domain/graph neighbors) is valid organizational evidence and does "
                    "not require the user to explicitly name the group."
                )
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "statement": context_statement,
                    "hypotheses": [asdict(item) for item in hypotheses],
                    "evidence_context": dict(context_pack or {}),
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = await model.generate(messages, structured_schema="attachment_set_critic")
        data = _parse_verdict(raw)
        items = data.get("verdicts")
        if not isinstance(items, list):
            raise AttachmentParseError("verdicts must be a list")
        verdicts: dict[tuple[str, str], LayerVerdict] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("op") or ""), str(item.get("target_id") or ""))
            if key not in keys:
                raise AttachmentParseError(f"critic returned unknown hypothesis: {key!r}")
            verdict = str(item.get("verdict") or "malformed")
            if verdict not in allowed:
                verdict = "malformed"
            verdicts[key] = LayerVerdict(layer, verdict, {"set_critic": True})
        for key in keys:
            verdicts.setdefault(
                key, LayerVerdict(layer, "malformed", {"error": "missing_verdict"})
            )
        return verdicts, 1
    except Exception as exc:  # noqa: BLE001
        return {
            key: LayerVerdict(layer, "malformed", {"error": str(exc)[:300]})
            for key in keys
        }, 1


def accepted_hypotheses_from_critics(
    hypotheses: Sequence[AttachmentHypothesis],
    *,
    support: Mapping[tuple[str, str], LayerVerdict],
    adversarial: Mapping[tuple[str, str], LayerVerdict],
    shortlist: Sequence[ShortlistCandidate] = (),
) -> tuple[AttachmentHypothesis, ...]:
    candidates = {item.target_id: item for item in shortlist}
    accepted: list[AttachmentHypothesis] = []
    for item in hypotheses:
        key = (item.op, item.target_id)
        candidate = candidates.get(item.target_id)
        low_risk_group_fit = bool(
            item.op == "add_to_group"
            and candidate is not None
            and candidate.metadata
            and (
                bool(candidate.metadata.get("membership_evidence"))
                or float(candidate.metadata.get("vector_similarity") or 0.0) >= 0.85
            )
        )
        support_verdict = support.get(
            key, LayerVerdict("L5", "missing")
        ).verdict
        adversarial_verdict = adversarial.get(
            key, LayerVerdict("L6", "missing")
        ).verdict
        strong_supported_evidence = bool(
            candidate is not None
            and candidate.metadata
            and (
                candidate.metadata.get("curated")
                or candidate.metadata.get("exact_term")
                or (
                    candidate.metadata.get("graph_distance") is not None
                    and int(candidate.metadata.get("graph_distance")) <= 1
                    and candidate.metadata.get("edge_status") != "historical"
                )
            )
        )
        reversible_group_fallback = bool(
            low_risk_group_fit
            and item.confidence >= 0.85
            and adversarial_verdict == "supported"
            and support_verdict in {"insufficient", "malformed"}
        )
        reversible_relation_fallback = bool(
            strong_supported_evidence
            and item.confidence >= 0.9
            and item.op not in {"same_as", "alias_of", "inferred_preference"}
            and adversarial_verdict == "supported"
            and support_verdict in {"insufficient", "malformed"}
        )
        if support_verdict != "supported" and not (
            reversible_group_fallback or reversible_relation_fallback
        ):
            continue
        high_confidence_non_identity = bool(
            item.confidence >= 0.9
            and item.op not in {"same_as", "alias_of", "inferred_preference"}
        )
        if adversarial_verdict != "supported" and not (
            adversarial_verdict == "insufficient"
            and (low_risk_group_fit or strong_supported_evidence or high_confidence_non_identity)
        ):
            continue
        accepted.append(item)
    return tuple(accepted)


CRITIC_PROMPT_VERSION = ATTACHMENT_PROMPT_VERSION
