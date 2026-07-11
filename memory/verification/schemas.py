from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


VERIFICATION_SCHEMA_VERSION = "1"


class VerifierRole(StrEnum):
    DETERMINISTIC = "deterministic"
    SUPPORT = "support"
    ADVERSARIAL = "adversarial"


class VerificationVerdict(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"
    MALFORMED = "malformed"


class EvidenceDirectness(StrEnum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    INFERRED = "inferred"


@dataclass(frozen=True, slots=True)
class ParsedVerdict:
    schema_version: str
    verdict: VerificationVerdict
    evidence_directness: EvidenceDirectness | None
    scope_errors: tuple[str, ...]
    ambiguities: tuple[str, ...]
    missing_context: tuple[str, ...]
    corrected_candidate: None = None

    def __post_init__(self) -> None:
        if self.schema_version != VERIFICATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported verification schema: {self.schema_version!r}")
        object.__setattr__(self, "scope_errors", tuple(self.scope_errors))
        object.__setattr__(self, "ambiguities", tuple(self.ambiguities))
        object.__setattr__(self, "missing_context", tuple(self.missing_context))


@dataclass(frozen=True, slots=True)
class VerificationVerdictInput:
    candidate_id: str
    role: VerifierRole
    verdict: VerificationVerdict
    evidence_directness: EvidenceDirectness | None
    scope_errors: tuple[str, ...]
    ambiguities: tuple[str, ...]
    missing_context: tuple[str, ...]
    verifier_name: str
    verifier_version: str
    prompt_version: str
    model_profile: str | None
    model_name: str | None
    input_hash: str
    raw_output: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_errors", tuple(self.scope_errors))
        object.__setattr__(self, "ambiguities", tuple(self.ambiguities))
        object.__setattr__(self, "missing_context", tuple(self.missing_context))
        object.__setattr__(self, "raw_output", MappingProxyType(dict(self.raw_output)))


@dataclass(frozen=True, slots=True)
class CandidateScoreInput:
    candidate_id: str
    policy_version: str
    verdict_set_hash: str
    components: Mapping[str, Any]
    route_status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))


@dataclass(frozen=True, slots=True)
class CandidateStatusUpdate:
    candidate_id: str
    from_statuses: tuple[str, ...]
    to_status: str
    acceptance_policy: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_statuses", tuple(self.from_statuses))
