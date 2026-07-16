"""Read-only ReAct experiment over the hard-coded synthetic graph.

The agent has only bounded search and inspection tools. It cannot open SQLite,
call MemoryService, or modify a graph/belief.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_settings
from llm import LLMClient, LLMRequestTimeoutError
from scripts.plan_graph_search_queries import EXAMPLE_INPUT, SYNTHETIC_GRAPH, _entity_search, _group_search

MAX_ACTIONS = 12
MAX_HOPS = 3
TOP_K = 10


class AgentResponseError(RuntimeError):
    """The model replied but did not follow the ReAct JSON contract."""

SYSTEM_PROMPT = """You are a read-only graph attachment investigator. Select one tool per
turn to investigate possible existing entities, groups and paths for attachment.
Never invent facts, scores, nodes, edges or evidence. Never request a write.
Inspect neighbours and paths before recommending anything.

Return exactly JSON:
{"kind":"tool","tool":"search_entities|get_entity|get_neighbors|search_edges|traverse_graph|search_groups|get_group","arguments":{},"why":"short"}
or:
{"kind":"final","decision":"recommend_attachment|abstain|needs_human_review","recommendations":[{"target_id":"id","operation":"add_to_group|link_to_entity|link_to_edge","score":0.0,"why":"short","evidence_step_ids":[1]}],"rejected_candidates":[],"missing_information":[]}
At most 12 actions. Tool lists are Top-10 and paths max 3 hops. Copy scores only from tool results."""

REPORT_PROMPT = """You are writing the conclusion of a read-only graph investigation.
Write a concise Markdown report using ONLY the supplied tool trace and final decision.
Do not invent graph facts, scores, IDs, relationships, or user intent. Cite every factual
claim with its trace step in square brackets, for example [step 2]. State clearly whether
an attachment is needed, already exists, or cannot be decided. Return exactly JSON:
{"report_markdown":"markdown text"}
Do not include a Markdown title; the host will add it."""


class Tools:
    """Bounded, read-only synthetic graph tool surface."""

    def __init__(self) -> None:
        self.entities = {str(item["id"]): item for item in SYNTHETIC_GRAPH["entities"]}

    @staticmethod
    def _score(hops: int) -> float:
        return round(max(0.0, 0.90 - 0.15 * (hops - 1)), 4)

    def search_entities(self, *, query: str, channel: str = "hybrid", limit: int = TOP_K) -> dict[str, Any]:
        channels = ("lexical", "alias", "vector", "taxonomy") if channel == "hybrid" else (channel,)
        best: dict[str, dict[str, Any]] = {}
        for current in channels:
            for hit in _entity_search(query, current):
                previous = best.get(str(hit["entity_id"]))
                if previous is None or float(hit["score"]) > float(previous["score"]):
                    best[str(hit["entity_id"])] = hit
        hits = sorted(best.values(), key=lambda item: (-float(item["score"]), str(item["entity_id"])))
        return {"query": query, "channel": channel, "hits": hits[: min(limit, TOP_K)]}

    def get_entity(self, *, entity_id: str) -> dict[str, Any]:
        return {"entity": self.entities.get(entity_id), "error": None if entity_id in self.entities else "unknown_entity"}

    def get_neighbors(self, *, entity_id: str, direction: str = "both", limit: int = TOP_K) -> dict[str, Any]:
        if entity_id not in self.entities:
            return {"error": "unknown_entity", "hits": []}
        hits = []
        for edge in SYNTHETIC_GRAPH["edges"]:
            outgoing, incoming = edge["from"] == entity_id, edge["to"] == entity_id
            allowed = (outgoing and direction in {"both", "outgoing"}) or (incoming and direction in {"both", "incoming"})
            if not allowed:
                continue
            other_id = edge["to"] if outgoing else edge["from"]
            other = self.entities[other_id]
            hits.append({
                "edge_id": edge["id"], "edge_type": edge["type"],
                "direction": "outgoing" if outgoing else "incoming",
                "entity_id": other_id, "label": other["label"], "kind": other["kind"], "score": 0.9,
            })
        return {"entity_id": entity_id, "hits": sorted(hits, key=lambda item: (item["edge_type"], item["entity_id"]))[: min(limit, TOP_K)]}

    def search_edges(self, *, entity_id: str, edge_types: list[str], direction: str = "both", limit: int = TOP_K) -> dict[str, Any]:
        raw = self.get_neighbors(entity_id=entity_id, direction=direction, limit=100)["hits"]
        wanted = set(edge_types)
        return {"entity_id": entity_id, "edge_types": edge_types, "hits": [hit for hit in raw if not wanted or hit["edge_type"] in wanted][: min(limit, TOP_K)]}

    def traverse_graph(self, *, entity_id: str, edge_types: list[str] | None = None, max_hops: int = 2, limit: int = TOP_K) -> dict[str, Any]:
        if entity_id not in self.entities:
            return {"error": "unknown_entity", "paths": []}
        allowed = set(edge_types or [])
        queue: deque[tuple[str, list[dict[str, Any]], set[str]]] = deque([(entity_id, [], {entity_id})])
        paths = []
        while queue and len(paths) < min(limit, TOP_K):
            node_id, path, visited = queue.popleft()
            if len(path) >= min(max_hops, MAX_HOPS):
                continue
            for edge in SYNTHETIC_GRAPH["edges"]:
                if allowed and edge["type"] not in allowed:
                    continue
                if edge["from"] == node_id:
                    other_id, direction = edge["to"], "outgoing"
                elif edge["to"] == node_id:
                    other_id, direction = edge["from"], "incoming"
                else:
                    continue
                if other_id in visited:
                    continue
                next_path = [*path, {"edge_id": edge["id"], "edge_type": edge["type"], "direction": direction}]
                paths.append({
                    "target_id": other_id, "target_label": self.entities[other_id]["label"],
                    "target_kind": self.entities[other_id]["kind"], "hops": len(next_path),
                    "score": self._score(len(next_path)), "path": next_path,
                })
                queue.append((other_id, next_path, visited | {other_id}))
                if len(paths) >= min(limit, TOP_K):
                    break
        return {"entity_id": entity_id, "paths": paths}

    def search_groups(self, *, query: str, limit: int = TOP_K) -> dict[str, Any]:
        return {"query": query, "hits": _group_search(query)[: min(limit, TOP_K)]}

    def get_group(self, *, group_id: str) -> dict[str, Any]:
        for group in SYNTHETIC_GRAPH["groups"]:
            if group["id"] == group_id:
                return {
                    "group_id": group_id, "label": group["label"], "kind": group["kind"],
                    "members": [{"entity_id": item, "label": self.entities[item]["label"], "kind": self.entities[item]["kind"]} for item in group["members"][:TOP_K]],
                }
        return {"error": "unknown_group"}


def _offline_actions() -> list[dict[str, Any]]:
    return [
        {"kind": "tool", "tool": "search_entities", "arguments": {"query": "пицца", "channel": "hybrid"}, "why": "resolve entity"},
        {"kind": "tool", "tool": "get_neighbors", "arguments": {"entity_id": "e_pizza"}, "why": "inspect direct edges"},
        {"kind": "tool", "tool": "traverse_graph", "arguments": {"entity_id": "e_pizza", "max_hops": 3}, "why": "inspect multi-hop paths"},
        {"kind": "tool", "tool": "search_groups", "arguments": {"query": "Italian dishes"}, "why": "find existing group"},
        {"kind": "tool", "tool": "get_group", "arguments": {"group_id": "g_italian"}, "why": "verify group membership"},
        {"kind": "final", "decision": "abstain", "recommendations": [], "rejected_candidates": [{"target_id": "g_italian", "why": "Pizza is already a member; adding it again would duplicate an existing attachment."}], "missing_information": []},
    ]


def _decode_action(raw: str) -> dict[str, Any]:
    """Accept a JSON object even if a gateway wraps it in a code fence."""
    text = raw.strip().lstrip("\ufeff")
    if not text:
        raise AgentResponseError("model returned an empty action")
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise AgentResponseError("model action did not contain a JSON object")
        text = text[start : end + 1]
    try:
        action = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentResponseError(f"invalid action JSON: {exc.msg}") from exc
    if not isinstance(action, dict) or action.get("kind") not in {"tool", "final"}:
        raise AgentResponseError("action must be an object with kind tool or final")
    return action


def _decode_json_object(raw: str) -> dict[str, Any]:
    """Parse a single JSON object returned by either ReAct or the report writer."""
    text = raw.strip().lstrip("\ufeff")
    if not text:
        raise AgentResponseError("model returned an empty JSON response")
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise AgentResponseError("model response did not contain a JSON object")
        text = text[start : end + 1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentResponseError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise AgentResponseError("model response must be a JSON object")
    return value


async def _next_llm_action(client: LLMClient, trace: list[dict[str, Any]]) -> dict[str, Any]:
    last_error: AgentResponseError | None = None
    for attempt in range(1, 4):
        retry_note = "" if attempt == 1 else " Your previous response was invalid. Output one non-empty JSON object only."
        raw = await client.chat_structured(
            [{"role": "system", "content": SYSTEM_PROMPT + retry_note}, {"role": "user", "content": json.dumps({"input": EXAMPLE_INPUT, "trace": trace}, ensure_ascii=False)}],
            max_tokens=1000,
            response_format={"type": "json_object"},
        )
        try:
            return _decode_action(raw)
        except (AgentResponseError, LLMRequestTimeoutError) as exc:
            last_error = exc
    raise last_error or AgentResponseError("model did not return an action")


def _fallback_agent_report(final: dict[str, Any]) -> str:
    decision = str(final.get("decision", "abstain"))
    if decision == "abstain":
        return "The investigation stopped without proposing a write. See the verified tool trace below for the reason."
    return "The investigation completed. See the verified tool trace and structured decision below."


async def _write_agent_report(
    client: LLMClient,
    *,
    trace: list[dict[str, Any]],
    final: dict[str, Any],
) -> str:
    raw = await client.chat_structured(
        [
            {"role": "system", "content": REPORT_PROMPT},
            {"role": "user", "content": json.dumps({"input": EXAMPLE_INPUT, "trace": trace, "final": final}, ensure_ascii=False)},
        ],
        max_tokens=1400,
        response_format={"type": "json_object"},
    )
    report = _decode_json_object(raw)
    markdown = report.get("report_markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise AgentResponseError("report writer returned no report_markdown")
    return markdown.strip()


async def run_agent(*, offline_demo: bool) -> dict[str, Any]:
    tools = Tools()
    trace: list[dict[str, Any]] = []
    scripted = iter(_offline_actions()) if offline_demo else None
    # ReAct is an agent task, not an extraction/summarization task.  The
    # `agent` profile uses the project's primary model and its reasoning setup.
    client = None if offline_demo else LLMClient(get_settings(), profile="agent")
    final: dict[str, Any] = {"decision": "abstain", "recommendations": [], "rejected_candidates": [], "missing_information": ["action budget exhausted"]}
    for step_id in range(1, MAX_ACTIONS + 1):
        try:
            action = next(scripted) if scripted else await _next_llm_action(client, trace)  # type: ignore[arg-type]
        except (AgentResponseError, LLMRequestTimeoutError) as exc:
            trace.append({"step_id": step_id, "tool": "agent_protocol", "arguments": {}, "result": {"error": str(exc)}})
            final = {
                "decision": "abstain",
                "recommendations": [],
                "rejected_candidates": [],
                "missing_information": ["LLM did not return a usable structured ReAct action or the model endpoint was unavailable."],
            }
            break
        if action["kind"] == "final":
            final = action
            break
        tool_name, arguments = str(action.get("tool", "")), action.get("arguments", {})
        tool = getattr(tools, tool_name, None)
        if not callable(tool) or not isinstance(arguments, dict):
            result = {"error": "invalid_tool_or_arguments"}
        else:
            try:
                result = tool(**arguments)
            except (TypeError, ValueError) as exc:
                result = {"error": f"tool_error: {exc}"}
        trace.append({"step_id": step_id, "why": action.get("why", ""), "tool": tool_name, "arguments": arguments, "result": result})
    report_markdown = _fallback_agent_report(final)
    report_error = None
    if client is not None:
        try:
            report_markdown = await _write_agent_report(client, trace=trace, final=final)
        except (AgentResponseError, LLMRequestTimeoutError) as exc:
            report_error = str(exc)
    return {
        "input": EXAMPLE_INPUT,
        "mode": "offline_demo" if offline_demo else "llm_react",
        "model": None if client is None else client.model_name,
        "max_actions": MAX_ACTIONS,
        "trace": trace,
        "final": final,
        "agent_report": {"markdown": report_markdown, "error": report_error},
        "write_performed": False,
    }


def markdown_report(report: dict[str, Any]) -> str:
    anchor, edge = report["input"]["anchor_entity"], report["input"]["anchor_edge"]
    lines = ["# Graph ReAct Investigation", "", "## User input", "", f"Entity: {anchor['label']}; edge: {edge['edge_type']}.", "", "## Agent conclusion", "", str(report.get("agent_report", {}).get("markdown", "")), "", "## Verified tool trace", ""]
    report_error = report.get("agent_report", {}).get("error")
    if report_error:
        lines.extend([f"Agent report fallback used: {report_error}", ""])
    for item in report["trace"]:
        lines.extend([f"### {item['step_id']}. {item['tool']}", "", f"Searched: {json.dumps(item['arguments'], ensure_ascii=False)}", "", "~~~json", json.dumps(item["result"], ensure_ascii=False, indent=2), "~~~", ""])
    final = report["final"]
    lines.extend(["## Recommendation", "", f"Decision: {final.get('decision', 'abstain')}", ""])
    for item in final.get("recommendations", []):
        lines.append(f"- {item.get('operation')} -> {item.get('target_id')}; score {float(item.get('score', 0)):.4f} — {item.get('why', '')}")
    if final.get("rejected_candidates"):
        lines.extend(["", "Rejected candidates:"])
        lines.extend(f"- {item.get('target_id')}: {item.get('why', '')}" for item in final["rejected_candidates"])
    if final.get("missing_information"):
        lines.extend(["", "Missing information:"])
        lines.extend(f"- {item}" for item in final["missing_information"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-demo", action="store_true", help="Run deterministic trace without LLM.")
    parser.add_argument("--output-stem", default="synthetic_graph_react_report", help="Report filename stem under data/memory_eval.")
    args = parser.parse_args()
    if not args.output_stem.replace("_", "").replace("-", "").isalnum():
        parser.error("--output-stem may contain only letters, digits, underscores, and hyphens")
    report = asyncio.run(run_agent(offline_demo=args.offline_demo))
    output_dir = ROOT / "data" / "memory_eval"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{args.output_stem}.json"
    markdown_path = output_dir / f"{args.output_stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({"json_report": str(json_path), "markdown_report": str(markdown_path), "decision": report["final"]["decision"], "steps": len(report["trace"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
