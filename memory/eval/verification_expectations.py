from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_PATH = FIXTURES_DIR / "verification_v1.json"

VERIFICATION_EVAL_PACKS: dict[str, str] = {
    "verification_v1": "verification_v1.json",
    "verification_v2": "verification_v2.json",
    "verification_v3": "verification_v3.json",
}

VERIFICATION_FIXTURE_PACKS: dict[str, str] = {
    "verification_v1": "text_v1",
    "verification_v2": "text_v1_verification_v2",
    "verification_v3": "text_v1_verification_v3",
}


def resolve_verification_expectations_path(eval_pack: str | None = None) -> Path:
    if eval_pack and eval_pack in VERIFICATION_EVAL_PACKS:
        return FIXTURES_DIR / VERIFICATION_EVAL_PACKS[eval_pack]
    return DEFAULT_PATH


def resolve_verification_fixture_pack(eval_pack: str) -> str:
    return VERIFICATION_FIXTURE_PACKS.get(eval_pack, eval_pack)


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    candidate_ref: str
    status: str
    verdict: str
    adversarial: bool


@dataclass(frozen=True, slots=True)
class VerificationCaseExpectation:
    outcomes: tuple[VerificationOutcome, ...]
    forbid_unexpected_advancement: bool


@dataclass(frozen=True, slots=True)
class VerificationExpectationPack:
    pack_id: str
    base_pack_id: str
    reviewed: bool
    cases: Mapping[str, VerificationCaseExpectation]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", MappingProxyType(dict(self.cases)))


def load_verification_expectations(
    path: str | Path = DEFAULT_PATH,
) -> VerificationExpectationPack:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        raw = json.load(handle, object_pairs_hook=_no_duplicates)
    _strict(raw, {"schema_version", "pack_id", "base_pack_id", "review", "cases"}, "$")
    if raw["schema_version"] != "1":
        raise ValueError("verification expectation schema_version must be '1'")
    review = raw["review"]
    _strict(review, {"status", "reviewed_by", "reviewed_at", "notes"}, "$.review")
    reviewed = review["status"] == "reviewed"
    if reviewed and (not review["reviewed_by"] or not review["reviewed_at"]):
        raise ValueError("reviewed verification pack requires reviewer and timestamp")
    cases: dict[str, VerificationCaseExpectation] = {}
    for fixture_id, value in raw["cases"].items():
        _strict(value, {"outcomes", "forbid_unexpected_advancement"}, fixture_id)
        outcomes: list[VerificationOutcome] = []
        refs: set[str] = set()
        for index, item in enumerate(value["outcomes"]):
            _strict(
                item,
                {"candidate_ref", "status", "verdict", "adversarial"},
                f"{fixture_id}.outcomes[{index}]",
            )
            ref = str(item["candidate_ref"])
            if ref in refs:
                raise ValueError(f"duplicate verification candidate ref: {fixture_id}:{ref}")
            refs.add(ref)
            if item["status"] not in {
                "ready_for_resolution",
                "needs_confirmation",
                "insufficient",
                "contradicted",
                "rejected",
            }:
                raise ValueError(f"unsupported verification status: {item['status']!r}")
            if item["verdict"] not in {
                "supported",
                "contradicted",
                "insufficient",
                "malformed",
            }:
                raise ValueError(f"unsupported verification verdict: {item['verdict']!r}")
            outcomes.append(
                VerificationOutcome(
                    candidate_ref=ref,
                    status=str(item["status"]),
                    verdict=str(item["verdict"]),
                    adversarial=bool(item["adversarial"]),
                )
            )
        cases[str(fixture_id)] = VerificationCaseExpectation(
            outcomes=tuple(outcomes),
            forbid_unexpected_advancement=bool(value["forbid_unexpected_advancement"]),
        )
    return VerificationExpectationPack(
        pack_id=str(raw["pack_id"]),
        base_pack_id=str(raw["base_pack_id"]),
        reviewed=reviewed,
        cases=cases,
    )


def _strict(value: object, expected: set[str], path: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{path} fields mismatch: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _no_duplicates(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result
