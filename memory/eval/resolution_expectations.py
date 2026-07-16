from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_PATH = FIXTURES_DIR / "resolution_v1.json"


@dataclass(frozen=True, slots=True)
class ResolutionCaseExpectation:
    expect_assertion: bool
    expect_root_self: bool
    expect_person_merge: bool
    expect_belief_status: str | None
    expect_utility: str | None
    non_ready_consumed: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolutionExpectationPack:
    pack_id: str
    reviewed: bool
    hard_gates: Mapping[str, Any]
    cases: Mapping[str, ResolutionCaseExpectation]

    def __post_init__(self) -> None:
        object.__setattr__(self, "hard_gates", MappingProxyType(dict(self.hard_gates)))
        object.__setattr__(self, "cases", MappingProxyType(dict(self.cases)))


def load_resolution_expectations(
    path: str | Path = DEFAULT_PATH,
) -> ResolutionExpectationPack:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("schema_version") != "1":
        raise ValueError("resolution expectation schema_version must be '1'")
    review = raw.get("review") or {}
    reviewed = review.get("status") == "reviewed"
    cases: dict[str, ResolutionCaseExpectation] = {}
    for fixture_id, value in (raw.get("cases") or {}).items():
        cases[fixture_id] = ResolutionCaseExpectation(
            expect_assertion=bool(value.get("expect_assertion", True)),
            expect_root_self=bool(value.get("expect_root_self", False)),
            expect_person_merge=bool(value.get("expect_person_merge", False)),
            expect_belief_status=value.get("expect_belief_status"),
            expect_utility=value.get("expect_utility"),
            non_ready_consumed=bool(value.get("non_ready_consumed", False)),
            notes=tuple(value.get("notes") or ()),
        )
    return ResolutionExpectationPack(
        pack_id=str(raw.get("pack_id") or "resolution_v1"),
        reviewed=reviewed,
        hard_gates=dict(raw.get("hard_gates") or {}),
        cases=cases,
    )


def check_hard_gates(
    *,
    eligible_assertion_recall: float,
    non_ready_consumed: int,
    false_person_merge: int,
    cross_user_leakage: int,
    critic_forbidden_merge: int,
    active_belief_without_support: int,
    graph_writes: int,
    gates: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return list of failed hard-gate names."""
    required = gates or {
        "eligible_assertion_recall": 1.0,
        "non_ready_consumed": 0,
        "false_person_merge": 0,
        "cross_user_leakage": 0,
        "critic_forbidden_merge": 0,
        "active_belief_without_support": 0,
        "graph_writes": 0,
    }
    failures: list[str] = []
    if eligible_assertion_recall < float(required.get("eligible_assertion_recall", 1.0)):
        failures.append("eligible_assertion_recall")
    if non_ready_consumed != int(required.get("non_ready_consumed", 0)):
        failures.append("non_ready_consumed")
    if false_person_merge != int(required.get("false_person_merge", 0)):
        failures.append("false_person_merge")
    if cross_user_leakage != int(required.get("cross_user_leakage", 0)):
        failures.append("cross_user_leakage")
    if critic_forbidden_merge != int(required.get("critic_forbidden_merge", 0)):
        failures.append("critic_forbidden_merge")
    if active_belief_without_support != int(
        required.get("active_belief_without_support", 0)
    ):
        failures.append("active_belief_without_support")
    if graph_writes != int(required.get("graph_writes", 0)):
        failures.append("graph_writes")
    return failures
