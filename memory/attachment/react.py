from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any, Mapping, Protocol, Sequence

from memory.attachment.context import AttachmentContextPack
from memory.attachment.react_tools import ALLOWED_REACT_TOOLS, AttachmentReactTools
from memory.attachment.schemas import ATTACH_OPS, DOMAIN_ALLOWED_OPS, AttachmentConfig, ShortlistCandidate
from memory.ids import canonical_json
from memory.structured_output import StructuredOutputModel

REACT_PROMPT_VERSION = "attachment_react_shadow_v1"


class AttachmentReactModel(Protocol):
    model_profile: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = None,
    ) -> str: ...


class LLMAttachmentReactModel:
    def __init__(self, client: Any, *, model_profile: str, max_tokens: int) -> None:
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
        schema = _react_schema(structured_schema) if structured_schema else None
        generated = await self._transport.generate(
            messages,
            schema_name=structured_schema,
            schema=schema,
        )
        return generated.text


def _react_schema(name: str) -> dict[str, Any]:
    if name == "attachment_react_action":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "kind",
                "tool",
                "arguments",
                "why",
                "decision",
                "recommendations",
                "confirmed_existing",
                "missing_information",
            ],
            "properties": {
                "kind": {"type": "string", "enum": ["tool", "final"]},
                "tool": {"type": "string"},
                "arguments": {"type": "object"},
                "why": {"type": "string"},
                "decision": {
                    "type": "string",
                    "enum": ["continue", "recommend_candidates", "abstain", "needs_review"],
                },
                "recommendations": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["target_id", "op", "why", "evidence_step_ids"],
                        "properties": {
                            "target_id": {"type": "string"},
                            "op": {"type": "string"},
                            "why": {"type": "string"},
                            "evidence_step_ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "maxItems": 12,
                            },
                        },
                    },
                },
                "confirmed_existing": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["target_id", "relation", "why", "evidence_step_ids"],
                        "properties": {
                            "target_id": {"type": "string"},
                            "relation": {"type": "string"},
                            "why": {"type": "string"},
                            "evidence_step_ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "maxItems": 12,
                            },
                        },
                    },
                },
                "missing_information": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 8,
                },
            },
        }
    if name == "attachment_react_report":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["report_markdown"],
            "properties": {"report_markdown": {"type": "string"}},
        }
    raise ValueError(f"unknown ReAct schema: {name}")


SYSTEM_PROMPT = """You are the read-only research phase of a graph attachment engine.
Investigate where the supplied source entity and relation may connect in the existing
user graph. Use exactly one provided tool per turn. You may inspect entities, edges,
bounded paths, communities, attachment history and conflicts. Never request a write.
Never invent an ID, relationship, score or graph fact. Recommendations may reference
only IDs actually returned by tools. Similarity is discovery, not proof. Prefer
abstain when evidence is insufficient. Existing relations must be reported in
confirmed_existing and must not be recommended again.

For a tool turn set kind=tool, choose an allowed tool, fill arguments and why, set
decision=continue, and leave final arrays empty. For completion set kind=final,
tool="", arguments={}, and return recommendations or abstain. This is shadow research:
your output cannot authorize a graph write."""

REPORT_PROMPT = """Write a concise Markdown research conclusion using only the supplied
read-only tool trace and validated final result. Cite factual claims as [step N].
Separate confirmed existing relations, plausible candidates, rejected/unsafe options,
and missing information. Do not introduce new IDs, scores, facts or user intent.
Return exactly {report_markdown: string} and do not add a top-level title."""


async def run_attachment_research(
    *,
    tools: AttachmentReactTools,
    model: AttachmentReactModel,
    config: AttachmentConfig,
    context: AttachmentContextPack,
    shortlist: Sequence[ShortlistCandidate],
) -> dict[str, Any]:
    snapshot_before = tools.graph_snapshot()
    input_payload = {
        "belief_id": context.belief_id,
        "statement": context.statement,
        "source_entity_id": context.source_entity_id,
        "source_label": context.source_label,
        "source_entity_type": context.source_entity_type,
        "schema_name": context.schema_name,
        "polarity": context.polarity,
        "attach_domains": list(context.attach_domains),
        "initial_candidates": [asdict(item) for item in shortlist],
        "existing_attachments": list(context.existing_attachments),
        "recent_corrections": list(context.recent_corrections),
        "graph_snapshot": snapshot_before,
    }
    trace: list[dict[str, Any]] = []
    observed_ids: set[str] = {
        str(item.target_id) for item in shortlist if item.target_id
    }
    if context.source_entity_id:
        observed_ids.add(str(context.source_entity_id))
    call_keys: set[str] = set()
    llm_calls = 0
    final = _empty_final("abstain")
    status = "completed"
    error: str | None = None

    for step_id in range(1, config.react_max_actions + 1):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "input": input_payload,
                        "allowed_tools": sorted(ALLOWED_REACT_TOOLS),
                        "limits": {
                            "actions": config.react_max_actions,
                            "hops": config.react_max_hops,
                            "results": config.react_max_results,
                            "nodes": config.react_max_nodes,
                        },
                        "trace": trace,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            raw = await model.generate(
                messages,
                structured_schema="attachment_react_action",
            )
            llm_calls += 1
            action = _parse_action(raw)
        except Exception as exc:  # provider and schema failures are shadow-only
            status = "model_error"
            error = str(exc)[:500]
            break

        if action["kind"] == "final":
            allowed_ops: set[str] = set()
            for domain in context.attach_domains:
                allowed_ops.update(DOMAIN_ALLOWED_OPS.get(domain, frozenset()))
            final = _validate_final(
                action,
                observed_ids=observed_ids,
                trace_size=len(trace),
                allowed_ops=allowed_ops,
            )
            break

        tool_name = str(action["tool"])
        arguments = dict(action["arguments"])
        call_key = hashlib.sha256(
            canonical_json({"tool": tool_name, "arguments": arguments}).encode("utf-8")
        ).hexdigest()
        if call_key in call_keys:
            result = {"error": "duplicate_tool_call"}
        elif tool_name not in ALLOWED_REACT_TOOLS:
            result = {"error": "tool_not_allowed"}
        else:
            call_keys.add(call_key)
            result = tools.execute(tool_name, arguments)
        _collect_ids(result, observed_ids)
        if len(observed_ids) > config.react_max_nodes:
            result = {
                "error": "node_budget_exceeded",
                "observed_node_count": len(observed_ids),
            }
            status = "budget_exceeded"
        trace.append(
            {
                "step_id": step_id,
                "tool": tool_name,
                "arguments": arguments,
                "why": str(action.get("why") or ""),
                "result": result,
            }
        )
        if status == "budget_exceeded":
            break
    else:
        status = "budget_exceeded"
        error = "action budget exhausted"

    snapshot_after = tools.graph_snapshot()
    stale = snapshot_after.get("graph_revision") != snapshot_before.get("graph_revision")
    if stale:
        final = _empty_final("needs_review")
        final["missing_information"] = ["Graph revision changed during research."]

    report_markdown = _fallback_report(final, status=status)
    report_error = None
    if trace and status == "completed":
        try:
            raw_report = await model.generate(
                [
                    {"role": "system", "content": REPORT_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"input": input_payload, "trace": trace, "final": final},
                            ensure_ascii=False,
                        ),
                    },
                ],
                structured_schema="attachment_react_report",
            )
            llm_calls += 1
            parsed_report = json.loads(raw_report)
            candidate = parsed_report.get("report_markdown")
            if isinstance(candidate, str) and candidate.strip():
                report_markdown = candidate.strip()
            else:
                report_error = "missing report_markdown"
        except Exception as exc:
            report_error = str(exc)[:500]

    return {
        "schema_version": "1",
        "prompt_version": REACT_PROMPT_VERSION,
        "mode": config.react_mode,
        "status": status,
        "model_profile": getattr(model, "model_profile", config.react_model_profile),
        "input_hash": hashlib.sha256(canonical_json(input_payload).encode("utf-8")).hexdigest(),
        "graph_revision_before": snapshot_before.get("graph_revision", 0),
        "graph_revision_after": snapshot_after.get("graph_revision", 0),
        "stale": stale,
        "trace": trace,
        "llm_calls": llm_calls,
        "final": final,
        "report_markdown": report_markdown,
        "report_error": report_error,
        "error": error,
        "write_performed": False,
    }


def _parse_action(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("kind") not in {"tool", "final"}:
        raise ValueError("invalid ReAct action")
    if not isinstance(data.get("arguments"), dict):
        raise ValueError("ReAct arguments must be an object")
    return data


def _validate_final(
    action: Mapping[str, Any],
    *,
    observed_ids: set[str],
    trace_size: int,
    allowed_ops: set[str],
) -> dict[str, Any]:
    recommendations = []
    for item in action.get("recommendations") or ():
        if not isinstance(item, Mapping):
            continue
        target_id = str(item.get("target_id") or "")
        op = str(item.get("op") or "")
        evidence = [
            int(value)
            for value in item.get("evidence_step_ids") or ()
            if isinstance(value, int) and 1 <= value <= trace_size
        ]
        if (
            target_id not in observed_ids
            or not evidence
            or op not in ATTACH_OPS
            or op not in allowed_ops
        ):
            continue
        recommendations.append(
            {
                "target_id": target_id,
                "op": op,
                "why": str(item.get("why") or ""),
                "evidence_step_ids": evidence,
            }
        )
    confirmed = []
    for item in action.get("confirmed_existing") or ():
        if not isinstance(item, Mapping):
            continue
        target_id = str(item.get("target_id") or "")
        evidence = [
            int(value)
            for value in item.get("evidence_step_ids") or ()
            if isinstance(value, int) and 1 <= value <= trace_size
        ]
        if target_id not in observed_ids or not evidence:
            continue
        confirmed.append(
            {
                "target_id": target_id,
                "relation": str(item.get("relation") or ""),
                "why": str(item.get("why") or ""),
                "evidence_step_ids": evidence,
            }
        )
    decision = str(action.get("decision") or "abstain")
    if decision == "recommend_candidates" and not recommendations:
        decision = "abstain"
    return {
        "decision": decision,
        "recommendations": recommendations,
        "confirmed_existing": confirmed,
        "missing_information": [
            str(item) for item in action.get("missing_information") or ()
        ][:8],
    }


def _collect_ids(value: Any, output: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {
                "entity_id",
                "target_id",
                "source_record_id",
                "community_id",
                "from_id",
                "to_id",
            } and item:
                output.add(str(item))
            _collect_ids(item, output)
    elif isinstance(value, list):
        for item in value:
            _collect_ids(item, output)


def _empty_final(decision: str) -> dict[str, Any]:
    return {
        "decision": decision,
        "recommendations": [],
        "confirmed_existing": [],
        "missing_information": [],
    }


def _fallback_report(final: Mapping[str, Any], *, status: str) -> str:
    return (
        f"Research status: {status}. Decision: {final.get('decision', 'abstain')}. "
        "Use the verified tool trace for factual details."
    )
