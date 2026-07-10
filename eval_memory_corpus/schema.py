"""Schema for generated memory corpus packs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

FactStatus = Literal["active", "superseded"]
Difficulty = Literal[
    "easy",
    "needle",
    "multi_fact",
    "contradiction",
    "cross_session",
    "tool_ref",
    "overview",
    "negative",
    "world",
]
Tier = Literal["smoke", "full"]


@dataclass(frozen=True)
class CorpusFact:
    id: str
    kind: str
    marker: str
    value: str
    turn: int
    status: FactStatus = "active"
    superseded_by: str | None = None
    question_templates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CorpusFact:
        return cls(
            id=str(payload["id"]),
            kind=str(payload["kind"]),
            marker=str(payload["marker"]),
            value=str(payload["value"]),
            turn=int(payload["turn"]),
            status=payload.get("status", "active"),  # type: ignore[arg-type]
            superseded_by=payload.get("superseded_by"),
            question_templates=tuple(payload.get("question_templates") or ()),
        )


@dataclass(frozen=True)
class CorpusTurn:
    user: str
    assistant: str
    fact_ids: tuple[str, ...] = ()
    tool_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user": self.user,
            "assistant": self.assistant,
            "fact_ids": list(self.fact_ids),
        }
        if self.tool_result is not None:
            payload["tool_result"] = self.tool_result
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CorpusTurn:
        return cls(
            user=str(payload["user"]),
            assistant=str(payload["assistant"]),
            fact_ids=tuple(payload.get("fact_ids") or ()),
            tool_result=payload.get("tool_result"),
        )


@dataclass(frozen=True)
class CorpusSession:
    slug: str
    topic_tags: tuple[str, ...]
    turns: tuple[CorpusTurn, ...]
    facts: tuple[CorpusFact, ...]
    summary: str
    title: str
    started_offset_hours: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "topic_tags": list(self.topic_tags),
            "turns": [turn.to_dict() for turn in self.turns],
            "facts": [fact.to_dict() for fact in self.facts],
            "summary": self.summary,
            "title": self.title,
            "started_offset_hours": self.started_offset_hours,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CorpusSession:
        return cls(
            slug=str(payload["slug"]),
            topic_tags=tuple(payload.get("topic_tags") or ()),
            turns=tuple(CorpusTurn.from_dict(item) for item in payload.get("turns") or ()),
            facts=tuple(CorpusFact.from_dict(item) for item in payload.get("facts") or ()),
            summary=str(payload.get("summary") or ""),
            title=str(payload.get("title") or payload["slug"]),
            started_offset_hours=int(payload.get("started_offset_hours") or 0),
        )


@dataclass(frozen=True)
class CorpusCase:
    id: str
    question: str
    must_include: tuple[str, ...]
    seed_sessions: tuple[str, ...]
    difficulty: Difficulty
    tier: Tier = "full"
    must_not_include: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    require_any_tools: tuple[str, ...] = ("chat.search", "chat.turns.read")
    expected_session_slug: str | None = None
    expected_tool_ref_fact: str | None = None
    world_seed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "must_include": list(self.must_include),
            "must_not_include": list(self.must_not_include),
            "required_tools": list(self.required_tools),
            "require_any_tools": list(self.require_any_tools),
            "seed_sessions": list(self.seed_sessions),
            "difficulty": self.difficulty,
            "tier": self.tier,
            "expected_session_slug": self.expected_session_slug,
            "expected_tool_ref_fact": self.expected_tool_ref_fact,
            "world_seed": self.world_seed,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CorpusCase:
        return cls(
            id=str(payload["id"]),
            question=str(payload["question"]),
            must_include=tuple(payload.get("must_include") or ()),
            must_not_include=tuple(payload.get("must_not_include") or ()),
            required_tools=tuple(payload.get("required_tools") or ()),
            require_any_tools=tuple(
                payload.get("require_any_tools")
                or ("chat.search", "chat.turns.read")
            ),
            seed_sessions=tuple(payload.get("seed_sessions") or ()),
            difficulty=payload.get("difficulty", "easy"),  # type: ignore[arg-type]
            tier=payload.get("tier", "full"),  # type: ignore[arg-type]
            expected_session_slug=payload.get("expected_session_slug"),
            expected_tool_ref_fact=payload.get("expected_tool_ref_fact"),
            world_seed=bool(payload.get("world_seed")),
        )


@dataclass(frozen=True)
class CorpusPack:
    version: str
    sessions: tuple[CorpusSession, ...]
    cases: tuple[CorpusCase, ...]
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "meta": self.meta,
            "sessions": [session.to_dict() for session in self.sessions],
            "cases": [case.to_dict() for case in self.cases],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CorpusPack:
        return cls(
            version=str(payload.get("version") or "1"),
            sessions=tuple(
                CorpusSession.from_dict(item) for item in payload.get("sessions") or ()
            ),
            cases=tuple(CorpusCase.from_dict(item) for item in payload.get("cases") or ()),
            meta=dict(payload.get("meta") or {}),
        )

    def session_by_slug(self) -> dict[str, CorpusSession]:
        return {session.slug: session for session in self.sessions}

    def cases_for_tier(self, tier: Tier | str) -> tuple[CorpusCase, ...]:
        if tier == "full":
            return self.cases
        return tuple(case for case in self.cases if case.tier == "smoke")


def save_pack(pack: CorpusPack, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(pack.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def load_pack(path: str | Path) -> CorpusPack:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return CorpusPack.from_dict(payload)


DEFAULT_PACK_PATH = Path("data/memory_corpus/pack_v1.json")
