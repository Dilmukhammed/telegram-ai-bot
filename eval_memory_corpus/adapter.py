"""Adapt corpus pack cases to the existing MemoryEvalCase / seed API."""

from __future__ import annotations

from typing import Any

from eval_chat_memory_benchmark import MemoryEvalCase, MemoryEvalScenario
from eval_memory_corpus.schema import CorpusCase, CorpusPack, DEFAULT_PACK_PATH, load_pack


def _seed_fn(pack: CorpusPack, case: CorpusCase):
    async def _seed(fixture) -> dict[str, Any]:
        mapping = fixture.seed_corpus_sessions(pack, case.seed_sessions)
        tool_ref = None
        if case.expected_tool_ref_fact:
            key = f"{case.expected_session_slug}:{case.expected_tool_ref_fact}"
            tool_ref = getattr(fixture, "corpus_tool_refs", {}).get(key)
            if tool_ref is None and case.seed_sessions:
                # fallback: any matching fact id suffix
                for stored_key, ref in getattr(fixture, "corpus_tool_refs", {}).items():
                    if stored_key.endswith(f":{case.expected_tool_ref_fact}"):
                        tool_ref = ref
                        break
        return {
            "archived_session_id": mapping.get(case.expected_session_slug or ""),
            "session_ids": mapping,
            "tool_ref": tool_ref,
        }

    return _seed


def corpus_case_to_memory_case(case: CorpusCase) -> MemoryEvalCase:
    return MemoryEvalCase(
        id=case.id,
        question=case.question,
        must_include=case.must_include,
        must_not_include=case.must_not_include,
        required_tools=case.required_tools,
        require_any_tools=case.require_any_tools,
    )


def scenarios_from_pack(
    pack: CorpusPack,
    *,
    tier: str = "full",
    limit: int | None = None,
    shard: tuple[int, int] | None = None,
) -> list[MemoryEvalScenario]:
    cases = list(pack.cases_for_tier(tier))  # type: ignore[arg-type]
    if shard is not None:
        index, total = shard
        cases = [case for i, case in enumerate(cases) if i % total == index]
    if limit is not None:
        cases = cases[: max(0, limit)]
    return [
        MemoryEvalScenario(
            case=corpus_case_to_memory_case(case),
            seed=_seed_fn(pack, case),
        )
        for case in cases
    ]


def load_default_pack() -> CorpusPack:
    return load_pack(DEFAULT_PACK_PATH)
