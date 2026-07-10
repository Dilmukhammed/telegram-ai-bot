from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class SourceStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"
    INVALIDATED = "invalidated"


class SourceVersionStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"
    INVALIDATED = "invalidated"


class SegmentStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    INVALIDATED = "invalidated"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    DEAD = "dead"
    CANCELLED = "cancelled"


class LineageRelation(StrEnum):
    DERIVED_FROM = "derived_from"
    NORMALIZED_FROM = "normalized_from"
    SUPERSEDES = "supersedes"
    INVALIDATED_BY = "invalidated_by"


class ProcessorRunOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class SourceInput:
    user_id: int
    source_type: str
    source_ref: str
    authority_class: str
    content_hash: str
    pointer: "EvidencePointer"
    session_id: str | None = None
    mime_type: str | None = None
    occurred_at: datetime | None = None
    source_metadata: Mapping[str, Any] = field(default_factory=dict)
    version_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, int) or isinstance(self.user_id, bool) or self.user_id < 1:
            raise ValueError("user_id must be a positive integer")
        for field_name, value in (
            ("source_type", self.source_type),
            ("source_ref", self.source_ref),
            ("authority_class", self.authority_class),
            ("content_hash", self.content_hash),
        ):
            if not str(value).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.occurred_at is not None and self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        object.__setattr__(
            self,
            "source_metadata",
            MappingProxyType(dict(self.source_metadata)),
        )
        object.__setattr__(
            self,
            "version_metadata",
            MappingProxyType(dict(self.version_metadata)),
        )


@dataclass(frozen=True)
class IngestResult:
    source_id: str
    source_version_id: str
    source_created: bool
    version_created: bool
    superseded_version_id: str | None
    enqueued_job_ids: tuple[str, ...]


@dataclass(frozen=True)
class InvalidationResult:
    source_id: str
    invalidated_version_ids: tuple[str, ...]
    cancelled_job_count: int
    inactive_descendant_count: int


@dataclass(frozen=True)
class MemorySource:
    source_id: str
    user_id: int
    session_id: str | None
    source_type: str
    source_ref: str
    ingested_at: datetime
    status: SourceStatus
    authority_class: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class MemorySourceVersion:
    source_version_id: str
    source_id: str
    content_hash: str
    mime_type: str | None
    occurred_at: datetime | None
    ingested_at: datetime
    pointer: "EvidencePointer"
    metadata: Mapping[str, Any]
    status: SourceVersionStatus
    supersedes_version_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class MemoryJob:
    job_id: str
    user_id: int
    source_version_id: str
    stage: str
    status: JobStatus
    attempts: int
    max_attempts: int
    processor_name: str
    processor_version: str
    prompt_version: str | None
    input_hash: str
    priority: int
    not_before: datetime | None
    lease_owner: str | None
    lease_token: str | None
    lease_until: datetime | None
    model_profile: str | None = None


@dataclass(frozen=True)
class JobRequest:
    stage: str
    processor_name: str
    processor_version: str
    input_hash: str
    prompt_version: str | None = None
    model_profile: str | None = None
    priority: int = 0
    max_attempts: int | None = None
    config_hash: str = ""


@dataclass(frozen=True)
class EnqueueResult:
    job_id: str
    created: bool


@dataclass(frozen=True)
class SegmentInput:
    source_version_id: str
    segment_type: str
    ordinal: int
    text: str | None
    pointer: "EvidencePointer"
    normalizer_name: str
    normalizer_version: str
    input_hash: str
    parent_segment_id: str | None = None


@dataclass(frozen=True)
class MemorySegment:
    segment_id: str
    source_version_id: str
    parent_segment_id: str | None
    segment_type: str
    ordinal: int
    text: str | None
    pointer: "EvidencePointer"
    normalizer_name: str
    normalizer_version: str
    input_hash: str
    created_at: datetime
    status: SegmentStatus


@dataclass(frozen=True)
class LineageInput:
    parent_kind: str
    parent_id: str
    child_kind: str
    child_id: str
    relation: LineageRelation


@dataclass(frozen=True)
class LineageRecord:
    lineage_id: str
    user_id: int
    parent_kind: str
    parent_id: str
    child_kind: str
    child_id: str
    relation: LineageRelation
    created_at: datetime


@dataclass(frozen=True)
class ProcessorOutput:
    output_hash: str
    output_json: Mapping[str, Any]
    new_segments: tuple[SegmentInput, ...] = ()
    next_jobs: tuple[JobRequest, ...] = ()
    lineage: tuple[LineageInput, ...] = ()
    new_mentions: tuple[Any, ...] = ()
    new_candidates: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "output_json",
            MappingProxyType(dict(self.output_json)),
        )
        object.__setattr__(self, "new_segments", tuple(self.new_segments))
        object.__setattr__(self, "next_jobs", tuple(self.next_jobs))
        object.__setattr__(self, "lineage", tuple(self.lineage))
        object.__setattr__(self, "new_mentions", tuple(self.new_mentions))
        object.__setattr__(self, "new_candidates", tuple(self.new_candidates))


@dataclass(frozen=True)
class ProcessorContext:
    job: MemoryJob
    source: MemorySource
    source_version: MemorySourceVersion
    worker_id: str


@dataclass(frozen=True)
class MemoryStatus:
    schema_version: int
    source_count: int
    active_version_count: int
    jobs_by_status: Mapping[str, int]
    jobs_by_stage: Mapping[str, int]
    oldest_pending_age_seconds: float | None
    active_worker_count: int
    dead_job_count: int
    active_mention_count: int = 0
    candidates_by_status: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "jobs_by_status",
            MappingProxyType(dict(self.jobs_by_status)),
        )
        object.__setattr__(
            self,
            "jobs_by_stage",
            MappingProxyType(dict(self.jobs_by_stage)),
        )
        object.__setattr__(
            self,
            "candidates_by_status",
            MappingProxyType(dict(self.candidates_by_status)),
        )


from memory.pointers import EvidencePointer  # noqa: E402  — circular type hint
