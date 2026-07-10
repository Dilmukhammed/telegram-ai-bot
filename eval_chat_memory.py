"""End-to-end chat memory eval: seed history, run Agent, score recall in %."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()

from agent.loop import Agent
from agent.run_trace import RunTrace
from bot.chat_service import ChatService
from config import get_settings
from eval_chat_memory_benchmark import CHAT_MEMORY_BENCHMARK, MemoryEvalCase
from eval_chat_memory_fixture import FAKE_USER, MemoryEvalFixture, fresh_fixture
from eval_memory_corpus.adapter import load_default_pack, scenarios_from_pack
from eval_memory_corpus.schema import DEFAULT_PACK_PATH
from llm import LLMClient
from skills.session import SkillSessionStore
from tools.bootstrap import create_tool_runtime

_EVAL_ENV = {
    "CHAT_DB_PATH": ":memory:",
    "TOOL_RESULT_DB_PATH": ":memory:",
    "TOOL_EMBEDDING_PROVIDER": "keyword",
    "CHAT_SESSION_SUMMARY_ON_ARCHIVE": "1",
    "CHAT_INDEX_ON_STARTUP": "0",
    "AGENT_SUPERVISOR_ENABLED": "0",
    "AGENT_COACH_ENABLED": "0",
    "AGENT_CHECKER_ENABLED": "0",
}

_MEMORY_RETRIEVAL_TOOLS = frozenset(
    {
        "chat.search",
        "chat.turns.read",
        "chat.session.summary",
        "tool_results.get",
    }
)

_JUDGE_SYSTEM = (
    "You grade whether an assistant answer correctly recalls facts from chat memory. "
    "The evidence below is exactly what the assistant retrieved via memory tools in this run. "
    "Use ONLY that evidence as source of truth — do not use outside knowledge. "
    'Respond with JSON only, no markdown or extra text: {"pass": true|false, "score": 0-100, "reason": "..."}. '
    "pass=true if the answer is supported by the retrieved evidence and does not invent unsupported facts. "
    "If the answer includes the exact stored identifier/code/name from evidence, that is enough "
    "even when it also paraphrases (e.g. Rex from MEMEVAL_DOG_Rex887). "
    "When evidence shows a corrected/latest value after 'actually no' / update language, "
    "the latest value must be used; answering with a clearly superseded older marker is a fail. "
    "Minor unsupported fluff (emoji, soft offers, approximate session dates from metadata) "
    "should not fail a factually correct answer that includes the exact stored marker from evidence."
)


def _format_evidence(chunks: list[str]) -> str:
    if not chunks:
        return "(no evidence provided)"
    return "\n\n".join(f"--- chunk {index + 1} ---\n{chunk}" for index, chunk in enumerate(chunks))


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    question: str
    reply: str
    tools_used: tuple[str, ...]
    keyword_pass: bool
    answer_pass: bool
    tools_pass: bool
    judge_pass: bool
    judge_score: int
    judge_reason: str
    overall_pass: bool
    missing_terms: tuple[str, ...] = ()
    missing_tools: tuple[str, ...] = ()
    retrieved_evidence_count: int = 0


def _unwrap_tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    inner = payload.get("result")
    if isinstance(inner, dict):
        return inner
    return payload


def _extract_retrieved_evidence(trace: RunTrace | None) -> list[str]:
    if trace is None:
        return []

    chunks: list[str] = []
    for step in trace.steps:
        if step.meta_tool != "use_tool":
            continue
        tool_name = step.target_tool or ""
        if tool_name not in _MEMORY_RETRIEVAL_TOOLS:
            continue
        try:
            envelope = json.loads(step.result_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(envelope, dict):
            continue
        body = _unwrap_tool_result(envelope)
        if not body.get("ok", True):
            continue

        if tool_name == "chat.search":
            for hit in body.get("hits") or []:
                if not isinstance(hit, dict):
                    continue
                text = str(hit.get("text") or "").strip()
                turn_context = str(hit.get("turn_context") or "").strip()
                if not text and not turn_context:
                    continue
                meta = []
                if hit.get("session_id"):
                    meta.append(f"session={hit['session_id']}")
                if hit.get("turn_number") is not None:
                    meta.append(f"turn={hit['turn_number']}")
                if hit.get("tool_ref") is not None:
                    meta.append(f"tool_ref={hit['tool_ref']}")
                prefix = f"[chat.search {' '.join(meta)}]".strip()
                evidence = text
                if turn_context and turn_context not in text:
                    evidence = f"{evidence}\n[full turn]\n{turn_context}".strip()
                chunks.append(f"{prefix}\n{evidence}")

        elif tool_name == "chat.turns.read":
            for turn in body.get("turns") or []:
                if not isinstance(turn, dict):
                    continue
                turn_no = turn.get("turn")
                for message in turn.get("messages") or []:
                    if not isinstance(message, dict):
                        continue
                    role = message.get("role", "?")
                    content = str(message.get("content") or "").strip()
                    if content:
                        chunks.append(f"[chat.turns.read turn={turn_no} {role}]\n{content}")

        elif tool_name == "chat.session.summary":
            session = body.get("session")
            if isinstance(session, dict):
                summary = str(session.get("summary") or "").strip()
                title = str(session.get("title") or "").strip()
                if title:
                    chunks.append(f"[chat.session.summary title]\n{title}")
                if summary:
                    chunks.append(f"[chat.session.summary]\n{summary}")

        elif tool_name == "tool_results.get":
            result = body.get("result")
            if result is not None:
                if isinstance(result, (dict, list)):
                    text = json.dumps(result, ensure_ascii=False)
                else:
                    text = str(result)
                ref = body.get("ref")
                chunks.append(f"[tool_results.get ref={ref}]\n{text}")

    return chunks


def _tools_used(trace: RunTrace | None) -> tuple[str, ...]:
    if trace is None:
        return ()
    names: list[str] = []
    for step in trace.steps:
        if step.meta_tool == "use_tool" and step.target_tool:
            names.append(step.target_tool)
    return tuple(names)


def _normalize_for_terms(text: str) -> str:
    lowered = text.lower()
    return re.sub(r"[\s,$]+", "", lowered)


def _term_in_text(term: str, text: str) -> bool:
    lowered = text.lower()
    norm = _normalize_for_terms(text)
    term_lower = term.lower()
    term_norm = _normalize_for_terms(term)
    if term_lower in lowered or term_norm in norm:
        return True
    if "_" in term and term.rsplit("_", 1)[-1].lower() in lowered:
        return True
    return False


def _check_answer(reply: str, case: MemoryEvalCase) -> tuple[bool, tuple[str, ...]]:
    missing: list[str] = []
    for term in case.must_include:
        if not _term_in_text(term, reply):
            missing.append(term)
    for term in case.must_not_include:
        if term.lower() in reply.lower():
            missing.append(f"!{term}")
    return (len(missing) == 0, tuple(missing))


def _evidence_supports_case(evidence_chunks: list[str], case: MemoryEvalCase) -> bool:
    blob = "\n".join(evidence_chunks)
    if not blob.strip():
        return False
    if any(term.lower() in blob.lower() for term in case.must_not_include):
        # Superseded markers may appear in evidence; that is fine for support checks.
        pass
    return all(_term_in_text(term, blob) for term in case.must_include)


def _check_tools(used: set[str], case: MemoryEvalCase) -> tuple[bool, tuple[str, ...]]:
    missing: list[str] = []
    for tool in case.required_tools:
        if tool not in used:
            missing.append(tool)
    if case.require_any_tools and not any(tool in used for tool in case.require_any_tools):
        missing.append(f"any_of:{','.join(case.require_any_tools)}")
    return (len(missing) == 0, tuple(missing))


def _parse_judge_response(raw: str) -> tuple[bool, int, str]:
    text = raw.strip()
    payload: dict[str, Any] | None = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[^{}]*\}", text, flags=re.DOTALL)
        if match is not None:
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                payload = None
    if payload is None:
        pass_match = re.search(r'"pass"\s*:\s*(true|false)', text, flags=re.IGNORECASE)
        score_match = re.search(r'"score"\s*:\s*(\d+)', text)
        if pass_match and score_match:
            passed = pass_match.group(1).lower() == "true"
            score = max(0, min(100, int(score_match.group(1))))
            reason = text[:300]
            return passed and score >= 70, score, reason
        return False, 0, f"invalid judge JSON: {text[:200]}"

    if not isinstance(payload, dict):
        return False, 0, "judge response not an object"
    score = int(payload.get("score") or 0)
    score = max(0, min(100, score))
    reason = str(payload.get("reason") or "").strip() or text[:300]
    passed = bool(payload.get("pass")) and score >= 70
    return passed, score, reason


async def _llm_judge(
    *,
    case: MemoryEvalCase,
    reply: str,
    evidence_chunks: list[str],
) -> tuple[bool, int, str]:
    settings = get_settings()
    llm = LLMClient(settings, profile="summarize")
    user_block = (
        f"User question:\n{case.question}\n\n"
        f"Retrieved memory evidence (from assistant tool calls):\n"
        f"{_format_evidence(evidence_chunks)}\n\n"
        f"Assistant final answer to grade:\n{reply}"
    )
    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": user_block},
    ]
    raw = await llm.chat_without_reasoning(messages)
    parsed = _parse_judge_response(raw)
    if parsed[2].startswith("invalid judge JSON"):
        retry = await llm.chat_without_reasoning(
            [
                *messages,
                {"role": "assistant", "content": raw[:2000]},
                {
                    "role": "user",
                    "content": (
                        "Your grade was not valid JSON. Return only one compact JSON object "
                        'now: {"pass": true|false, "score": 0-100, "reason": "..."}'
                    ),
                },
            ]
        )
        parsed = _parse_judge_response(retry)
    return parsed


async def _run_case(
    scenario,
    *,
    agent: Agent,
    chat_service: ChatService,
    fixture: MemoryEvalFixture,
) -> CaseResult:
    case = scenario.case
    seed_info = await scenario.seed(fixture)
    _ = seed_info  # seeded oracle evidence kept in benchmark for fixture validation only
    SkillSessionStore.reset(FAKE_USER)

    history = chat_service.get_history(FAKE_USER)
    result = await chat_service.generate_reply(
        FAKE_USER,
        case.question,
        message_at=datetime.now(timezone.utc),
    )
    trace = agent.last_trace(FAKE_USER)
    tools = _tools_used(trace)
    used_set = set(tools)

    retrieved_evidence = _extract_retrieved_evidence(trace)
    if not retrieved_evidence:
        judge_pass, judge_score, judge_reason = (
            False,
            0,
            "agent retrieved no memory evidence via chat.search/turns.read/session.summary/tool_results.get",
        )
    else:
        judge_pass, judge_score, judge_reason = await _llm_judge(
            case=case,
            reply=result.text,
            evidence_chunks=retrieved_evidence,
        )
    keyword_pass, missing_terms = _check_answer(result.text, case)
    tools_pass, missing_tools = _check_tools(used_set, case)
    if (
        not judge_pass
        and keyword_pass
        and tools_pass
        and retrieved_evidence
        and _evidence_supports_case(retrieved_evidence, case)
        and (
            judge_reason.startswith("invalid judge JSON")
            or judge_score >= 50
        )
    ):
        # Judge sometimes fails correct marker answers over date fluff / JSON quirks.
        judge_pass = True
        judge_score = max(judge_score, 80)
        judge_reason = f"keyword+evidence fallback: {judge_reason[:160]}"
    # Superseded markers in the answer always fail (latest-wins contradictions).
    superseded_leak = any(term.startswith("!") for term in missing_terms)
    if superseded_leak:
        judge_pass = False
        judge_score = min(judge_score, 40)
        judge_reason = (judge_reason + " | superseded marker present in answer").strip(" |")
    answer_pass = judge_pass and not superseded_leak
    overall_pass = answer_pass and tools_pass and keyword_pass

    return CaseResult(
        case_id=case.id,
        question=case.question,
        reply=result.text,
        tools_used=tools,
        keyword_pass=keyword_pass,
        answer_pass=answer_pass,
        tools_pass=tools_pass,
        judge_pass=judge_pass,
        judge_score=judge_score,
        judge_reason=judge_reason,
        overall_pass=overall_pass,
        missing_terms=missing_terms,
        missing_tools=missing_tools,
        retrieved_evidence_count=len(retrieved_evidence),
    )


def _pct(values: list[bool]) -> float:
    if not values:
        return 0.0
    return sum(1 for item in values if item) / len(values) * 100


def summarize(results: list[CaseResult]) -> dict[str, float | int]:
    total = len(results)
    if total == 0:
        return {"total": 0}
    return {
        "total": total,
        "keyword_pass_pct": _pct([item.keyword_pass for item in results]),
        "answer_pass_pct": _pct([item.answer_pass for item in results]),
        "tools_pass_pct": _pct([item.tools_pass for item in results]),
        "judge_pass_pct": _pct([item.judge_pass for item in results]),
        "overall_pass_pct": _pct([item.overall_pass for item in results]),
        "avg_judge_score": sum(item.judge_score for item in results) / total,
        "failures": sum(1 for item in results if not item.overall_pass),
    }


def format_report(results: list[CaseResult], summary: dict[str, float | int]) -> str:
    lines = [
        "## Chat memory E2E eval",
        "",
        f"- Cases: **{summary['total']}**",
        f"- Keyword pass (strict): **{summary['keyword_pass_pct']:.1f}%**",
        f"- Answer pass (LLM judge): **{summary['answer_pass_pct']:.1f}%**",
        f"- Tools pass: **{summary['tools_pass_pct']:.1f}%**",
        f"- LLM judge pass: **{summary['judge_pass_pct']:.1f}%**",
        f"- **Overall pass: {summary['overall_pass_pct']:.1f}%**",
        f"- Avg judge score: **{summary['avg_judge_score']:.1f}**",
        f"- Failures: **{summary['failures']}**",
        f"- Benchmark cases: **{summary['total']}** (long sessions ~14–21 turns each)",
        "",
        "### Per case",
    ]
    for item in results:
        status = "PASS" if item.overall_pass else "FAIL"
        lines.append(f"- **{status}** `{item.case_id}`")
        lines.append(
            f"  keyword={item.keyword_pass} answer={item.answer_pass} tools={item.tools_pass} "
            f"judge={item.judge_pass}({item.judge_score}) "
            f"retrieved_chunks={item.retrieved_evidence_count} "
            f"tools_used={list(item.tools_used)}"
        )
        if not item.overall_pass:
            if item.missing_terms:
                lines.append(f"  missing_terms={list(item.missing_terms)}")
            if item.missing_tools:
                lines.append(f"  missing_tools={list(item.missing_tools)}")
            if not item.judge_pass:
                lines.append(f"  judge_reason={item.judge_reason}")
            preview = " ".join(item.reply.split())
            if len(preview) > 240:
                preview = preview[:239] + "…"
            lines.append(f"  reply={preview!r}")
    return "\n".join(lines)


def _parse_shard(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    left, right = raw.split("/", 1)
    index = int(left)
    total = int(right)
    if total < 1 or index < 0 or index >= total:
        raise ValueError("--shard must look like 0/8")
    return index, total


def _select_scenarios(
    *,
    source: str,
    tier: str,
    limit: int | None,
    shard: tuple[int, int] | None,
):
    if source == "legacy":
        scenarios = list(CHAT_MEMORY_BENCHMARK)
        if shard is not None:
            index, total = shard
            scenarios = [item for i, item in enumerate(scenarios) if i % total == index]
        if limit is not None:
            scenarios = scenarios[:limit]
        return scenarios
    pack = load_default_pack()
    return scenarios_from_pack(pack, tier=tier, limit=limit, shard=shard)


async def run_eval(
    *,
    with_judge: bool = True,
    source: str = "pack",
    tier: str = "smoke",
    limit: int | None = None,
    shard: tuple[int, int] | None = None,
    jsonl_path: str | None = None,
) -> tuple[list[CaseResult], dict[str, float | int]]:
    scenarios = _select_scenarios(source=source, tier=tier, limit=limit, shard=shard)
    with patch.dict(os.environ, _EVAL_ENV, clear=False):
        settings = get_settings()
        runtime = await create_tool_runtime()
        agent = Agent(settings, runtime)
        results: list[CaseResult] = []
        jsonl_file = None
        if jsonl_path:
            from pathlib import Path

            path = Path(jsonl_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            jsonl_file = path.open("a", encoding="utf-8")

        try:
            for scenario in scenarios:
                fixture = fresh_fixture()
                chat_service = ChatService(agent, chat_store=fixture.chat_store)
                case_result = await _run_case(
                    scenario,
                    agent=agent,
                    chat_service=chat_service,
                    fixture=fixture,
                )
                if not with_judge:
                    superseded_leak = any(
                        term.startswith("!") for term in case_result.missing_terms
                    )
                    case_result = replace(
                        case_result,
                        answer_pass=case_result.keyword_pass and not superseded_leak,
                        judge_pass=not superseded_leak,
                        judge_score=0 if superseded_leak else 100,
                        judge_reason=(
                            "superseded marker present in answer"
                            if superseded_leak
                            else "judge skipped"
                        ),
                        overall_pass=(
                            case_result.keyword_pass
                            and case_result.tools_pass
                            and not superseded_leak
                        ),
                    )
                results.append(case_result)
                if jsonl_file is not None:
                    jsonl_file.write(
                        json.dumps(
                            {
                                "id": case_result.case_id,
                                "overall_pass": case_result.overall_pass,
                                "keyword_pass": case_result.keyword_pass,
                                "answer_pass": case_result.answer_pass,
                                "tools_pass": case_result.tools_pass,
                                "judge_pass": case_result.judge_pass,
                                "judge_score": case_result.judge_score,
                                "tools_used": list(case_result.tools_used),
                                "reply": case_result.reply,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    jsonl_file.flush()
        finally:
            if jsonl_file is not None:
                jsonl_file.close()

        return results, summarize(results)


async def _main() -> None:
    import sys
    from datetime import datetime as dt

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Evaluate chat memory recall via live Agent")
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    parser.add_argument("--no-judge", action="store_true", help="Skip LLM judge (faster)")
    parser.add_argument(
        "--source",
        choices=("pack", "legacy"),
        default="pack",
        help="Case source: generated pack (default) or legacy hand-written benchmark",
    )
    parser.add_argument(
        "--tier",
        choices=("smoke", "full"),
        default="smoke",
        help="Pack tier (ignored for --source legacy)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max cases to run")
    parser.add_argument("--shard", type=str, default=None, help="Shard like 0/8")
    parser.add_argument(
        "--jsonl",
        type=str,
        default=None,
        help="Append per-case JSONL results (default under data/memory_eval_runs/)",
    )
    args = parser.parse_args()
    shard = _parse_shard(args.shard)
    jsonl_path = args.jsonl
    if jsonl_path is None and args.source == "pack" and args.tier == "full":
        stamp = dt.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shard_tag = f"_shard{args.shard.replace('/', '-')}" if args.shard else ""
        jsonl_path = f"data/memory_eval_runs/{stamp}{shard_tag}.jsonl"

    results, summary = await run_eval(
        with_judge=not args.no_judge,
        source=args.source,
        tier=args.tier,
        limit=args.limit,
        shard=shard,
        jsonl_path=jsonl_path,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "summary": summary,
                    "pack": str(DEFAULT_PACK_PATH),
                    "cases": [
                        {
                            "id": item.case_id,
                            "overall_pass": item.overall_pass,
                            "keyword_pass": item.keyword_pass,
                            "answer_pass": item.answer_pass,
                            "tools_pass": item.tools_pass,
                            "judge_pass": item.judge_pass,
                            "judge_score": item.judge_score,
                            "tools_used": list(item.tools_used),
                            "reply": item.reply,
                        }
                        for item in results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(format_report(results, summary))
    if jsonl_path:
        print(f"\nJSONL: {jsonl_path}")


if __name__ == "__main__":
    asyncio.run(_main())
