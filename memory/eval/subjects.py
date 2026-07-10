from __future__ import annotations

import asyncio
import hashlib
import json
import math
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


CAPTURED_OUTPUT_SCHEMA_VERSION = "1"
SUBJECT_OUTPUT_SCHEMA_VERSION = "1"


class SubjectOutputError(ValueError):
    """Raised when a captured subject output is not strict schema-versioned JSON."""


@dataclass(frozen=True)
class EvalContext:
    """Execution controls shared by evaluation subjects.

    Resolved fixtures intentionally remain outside this type.  The harness may
    pass either mappings or loader-owned dataclasses without coupling subjects
    to a particular loader implementation.
    """

    timeout_seconds: float = 10.0
    poll_interval_seconds: float = 0.02
    captured_output_dir: str | Path | None = None
    temp_root: str | Path | None = None
    text_segment_chars: int = 4000
    text_segment_overlap: int = 200
    seed: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and > 0")
        if not math.isfinite(self.poll_interval_seconds) or self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be finite and > 0")
        if self.text_segment_chars < 1:
            raise ValueError("text_segment_chars must be >= 1")
        if self.text_segment_overlap < 0:
            raise ValueError("text_segment_overlap must be >= 0")
        if self.text_segment_overlap >= self.text_segment_chars:
            raise ValueError("text_segment_overlap must be smaller than text_segment_chars")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class SubjectOutput:
    schema_version: str = SUBJECT_OUTPUT_SCHEMA_VERSION
    fixture_id: str = ""
    sources: tuple[Mapping[str, Any], ...] = ()
    source_versions: tuple[Mapping[str, Any], ...] = ()
    jobs: tuple[Mapping[str, Any], ...] = ()
    segments: tuple[Mapping[str, Any], ...] = ()
    pointer_checks: tuple[Mapping[str, Any], ...] = ()
    mentions: tuple[Mapping[str, Any], ...] = ()
    candidates: tuple[Mapping[str, Any], ...] = ()
    usage: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SUBJECT_OUTPUT_SCHEMA_VERSION:
            raise ValueError(f"unsupported subject output schema_version: {self.schema_version!r}")
        if not self.fixture_id.strip():
            raise ValueError("fixture_id must be non-empty")
        for name in (
            "sources",
            "source_versions",
            "jobs",
            "segments",
            "pointer_checks",
            "mentions",
            "candidates",
        ):
            values = getattr(self, name)
            object.__setattr__(self, name, tuple(dict(value) for value in values))
        object.__setattr__(self, "usage", dict(self.usage))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def versions(self) -> tuple[Mapping[str, Any], ...]:
        return self.source_versions

    @property
    def actual_sources(self) -> tuple[Mapping[str, Any], ...]:
        return self.sources

    @property
    def actual_source_versions(self) -> tuple[Mapping[str, Any], ...]:
        return self.source_versions

    @property
    def actual_jobs(self) -> tuple[Mapping[str, Any], ...]:
        return self.jobs

    @property
    def actual_segments(self) -> tuple[Mapping[str, Any], ...]:
        return self.segments

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "sources": [dict(item) for item in self.sources],
            "source_versions": [dict(item) for item in self.source_versions],
            "jobs": [dict(item) for item in self.jobs],
            "segments": [dict(item) for item in self.segments],
            "pointer_checks": [dict(item) for item in self.pointer_checks],
            "mentions": [dict(item) for item in self.mentions],
            "candidates": [dict(item) for item in self.candidates],
            "usage": dict(self.usage),
            "metadata": dict(self.metadata),
        }


@runtime_checkable
class EvalSubject(Protocol):
    subject_id: str
    pipeline_id: str

    async def run(self, case: Any, context: EvalContext) -> SubjectOutput:
        ...


_CAPTURED_REQUIRED = frozenset({"schema_version", "fixture_id", "mentions", "candidates"})
_CAPTURED_OPTIONAL = frozenset(
    {
        "subject_id",
        "pipeline_id",
        "sources",
        "source_versions",
        "jobs",
        "segments",
        "pointer_checks",
        "usage",
        "metadata",
    }
)
_OUTPUT_LIST_FIELDS = (
    "sources",
    "source_versions",
    "jobs",
    "segments",
    "pointer_checks",
    "mentions",
    "candidates",
)


class CapturedOutputSubject:
    """Offline subject backed by strict, versioned JSON files."""

    subject_id = "captured_output"

    def __init__(
        self,
        actual_dir: str | Path | Mapping[str, Any] | None = None,
        *,
        pipeline_id: str = "captured_json_v1",
    ) -> None:
        if not pipeline_id.strip():
            raise ValueError("pipeline_id must be non-empty")
        self.pipeline_id = pipeline_id
        self._source = actual_dir

    async def run(self, case: Any, context: EvalContext) -> SubjectOutput:
        fixture_id = _fixture_id(case)
        payload = await asyncio.to_thread(self._load_payload, fixture_id, context)
        return _captured_to_output(payload, expected_fixture_id=fixture_id)

    def _load_payload(self, fixture_id: str, context: EvalContext) -> Mapping[str, Any]:
        source = self._source
        if isinstance(source, Mapping):
            selected = source.get(fixture_id, source)
            if isinstance(selected, Mapping):
                return dict(selected)
            source = selected

        path_value = source if source is not None else context.captured_output_dir
        if path_value is None:
            raise SubjectOutputError("captured output directory was not configured")
        path = Path(path_value)
        if path.is_dir():
            path = path / f"{fixture_id}.json"
        if not path.is_file():
            raise SubjectOutputError(f"captured output not found for fixture {fixture_id!r}")
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_non_finite_json_number,
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SubjectOutputError(f"invalid captured output {path.name!r}: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise SubjectOutputError("captured output root must be an object")
        return payload


def _captured_to_output(
    payload: Mapping[str, Any],
    *,
    expected_fixture_id: str,
) -> SubjectOutput:
    keys = frozenset(payload)
    missing = _CAPTURED_REQUIRED - keys
    unknown = keys - _CAPTURED_REQUIRED - _CAPTURED_OPTIONAL
    if missing:
        raise SubjectOutputError(f"captured output is missing fields: {sorted(missing)}")
    if unknown:
        raise SubjectOutputError(f"captured output has unknown fields: {sorted(unknown)}")
    if payload["schema_version"] != CAPTURED_OUTPUT_SCHEMA_VERSION:
        raise SubjectOutputError(
            f"unsupported captured output schema_version: {payload['schema_version']!r}"
        )
    fixture_id = payload["fixture_id"]
    if not isinstance(fixture_id, str) or fixture_id != expected_fixture_id:
        raise SubjectOutputError(
            f"captured output fixture_id {fixture_id!r} does not match {expected_fixture_id!r}"
        )

    values: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for name in _OUTPUT_LIST_FIELDS:
        raw = payload.get(name, [])
        if not isinstance(raw, list):
            raise SubjectOutputError(f"captured output {name} must be an array")
        if any(not isinstance(item, Mapping) for item in raw):
            raise SubjectOutputError(f"captured output {name} entries must be objects")
        values[name] = tuple(dict(item) for item in raw)
    usage = payload.get("usage", {})
    metadata = payload.get("metadata", {})
    if not isinstance(usage, Mapping) or not isinstance(metadata, Mapping):
        raise SubjectOutputError("captured output usage and metadata must be objects")
    _validate_json_value(payload)
    return SubjectOutput(
        fixture_id=fixture_id,
        usage=dict(usage),
        metadata=dict(metadata),
        **values,
    )


# The production stores expose process-wide compatibility singletons.  A lock
# prevents concurrent eval cases from observing each other's temporary stores.
_ISOLATION_LOCK = asyncio.Lock()


class PR1IngestionSubject:
    """Run a resolved fixture through the real PR 1 ingestion pipeline."""

    subject_id = "pr1_ingestion"
    pipeline_id = "text_ingestion_v1"

    def __init__(self, *, extraction_model: Any | None = None, timezone: str = "Asia/Tashkent") -> None:
        self._extraction_model = extraction_model
        self._timezone = timezone

    async def run(self, case: Any, context: EvalContext) -> SubjectOutput:
        async with _ISOLATION_LOCK:
            return await self._run_isolated(case, context)

    async def _run_isolated(self, case: Any, context: EvalContext) -> SubjectOutput:
        from bot import chat_store as chat_store_module
        from bot import memory_chat_adapter
        from bot.chat_store.store import ChatStore
        from bot.memory_chat_adapter import ChatEvidenceAdapter, set_text_ingest_sink
        from memory.ingestion.runtime import TextIngestionRuntime
        from memory.service import MemoryService
        from memory import service as memory_service_module
        from tools.tool_results import store as tool_store_module
        from tools.tool_results.memory_adapter import ToolEvidenceAdapter, ToolMemoryLifecycleObserver
        from tools.tool_results.store import ToolResultStore

        fixture_id = _fixture_id(case)
        prior_chat_store = chat_store_module._store
        prior_tool_store = tool_store_module._store
        prior_memory_service = memory_service_module._service
        prior_sink = memory_chat_adapter._sink
        runtime: TextIngestionRuntime | None = None
        service: MemoryService | None = None
        tool_store: ToolResultStore | None = None
        started = time.monotonic()

        temp_root = str(context.temp_root) if context.temp_root is not None else None
        with tempfile.TemporaryDirectory(
            prefix=f"memory-eval-{_safe_name(fixture_id)}-",
            dir=temp_root,
            ignore_cleanup_errors=True,
        ) as tmp:
            root = Path(tmp)
            chat_path = root / "chat.sqlite"
            tool_path = root / "tool_results.sqlite"
            memory_path = root / "memory.sqlite"
            try:
                config = _eval_memory_config(
                    memory_path,
                    context,
                    case,
                    extraction_enabled=self._extraction_model is not None,
                    extraction_model_profile=(
                        str(getattr(self._extraction_model, "model_profile", "eval"))
                        if self._extraction_model is not None
                        else "summarize"
                    ),
                )
                chat_store = ChatStore(str(chat_path))
                tool_store = ToolResultStore(str(tool_path))
                service = MemoryService(db_path=str(memory_path), config=config)
                chat_reader = ChatEvidenceAdapter(chat_store)
                tool_reader = ToolEvidenceAdapter(tool_store)
                runtime = TextIngestionRuntime(
                    service=service,
                    config=config,
                    chat_reader=chat_reader,
                    tool_reader=tool_reader,
                )

                chat_store_module.reset_chat_store(chat_store)
                tool_store_module.reset_tool_result_store(tool_store)
                memory_service_module.reset_memory_service(service)

                aliases: dict[str, dict[str, Any]] = {}
                users = _resolved_users(case)
                baseline, live = _partition_events(case)
                sessions: dict[tuple[int, str], str] = {}

                # Baseline rows exist before first enable.  The scanner records
                # their heads and therefore does not ingest historical data.
                for event in baseline:
                    self._seed_event(
                        event,
                        users=users,
                        chat_store=chat_store,
                        tool_store=tool_store,
                        sessions=sessions,
                        aliases=aliases,
                        notify=False,
                        runtime=None,
                    )

                await runtime.start()
                if self._extraction_model is not None:
                    from memory.extraction.pipeline import register_text_extractor

                    register_text_extractor(
                        service.registry,
                        service=service,
                        model=self._extraction_model,
                        timezone=self._timezone,
                    )
                set_text_ingest_sink(runtime.sink)
                observer = ToolMemoryLifecycleObserver(runtime.sink)
                tool_store.set_lifecycle_observer(observer)
                await service.start_worker()

                catchup_needed = False
                expected_sources = 0
                for event in live:
                    delivery = _event_delivery(event, context)
                    notify = delivery == "live"
                    if delivery == "catchup":
                        catchup_needed = True
                    kind = str(_value(event, "kind", "")).strip()
                    if kind in {"chat_message", "tool_result"}:
                        expected_sources += 1
                    self._seed_event(
                        event,
                        users=users,
                        chat_store=chat_store,
                        tool_store=tool_store,
                        sessions=sessions,
                        aliases=aliases,
                        notify=notify,
                        runtime=runtime,
                    )
                if catchup_needed:
                    runtime.wake_scanner()

                await _wait_for_ingestion(
                    service,
                    runtime,
                    expected_sources=expected_sources,
                    timeout_seconds=context.timeout_seconds,
                    poll_interval_seconds=context.poll_interval_seconds,
                )
                collected = _collect_ingestion_output(
                    service=service,
                    chat_reader=chat_reader,
                    tool_reader=tool_reader,
                    fixture_id=fixture_id,
                    aliases=aliases,
                    elapsed_seconds=time.monotonic() - started,
                    subject_type=(
                        "extraction" if self._extraction_model is not None else "ingestion"
                    ),
                )
                return collected
            finally:
                try:
                    if tool_store is not None:
                        tool_store.set_lifecycle_observer(None)
                    set_text_ingest_sink(None)
                    try:
                        if runtime is not None:
                            await runtime.stop(
                                grace_seconds=min(1.0, context.timeout_seconds)
                            )
                    finally:
                        if service is not None:
                            await service.stop_worker(
                                grace_seconds=min(1.0, context.timeout_seconds)
                            )
                finally:
                    chat_store_module.reset_chat_store(prior_chat_store)
                    tool_store_module.reset_tool_result_store(prior_tool_store)
                    memory_service_module.reset_memory_service(prior_memory_service)
                    set_text_ingest_sink(prior_sink)

    @staticmethod
    def _seed_event(
        event: Any,
        *,
        users: Mapping[str, int],
        chat_store: Any,
        tool_store: Any,
        sessions: dict[tuple[int, str], str],
        aliases: dict[str, dict[str, Any]],
        notify: bool,
        runtime: Any | None,
    ) -> None:
        kind = str(_value(event, "kind", "")).strip()
        alias = str(_value(event, "event_id", _value(event, "id", ""))).strip()
        if not alias:
            raise ValueError("resolved fixture event is missing event_id")
        user_id = _event_user_id(event, users)

        if kind == "chat_message":
            occurred_at = _aware_datetime(_value(event, "occurred_at", None), "occurred_at")
            session_alias = str(_value(event, "session_alias", "default"))
            session_key = (user_id, session_alias)
            session_id = sessions.get(session_key)
            if session_id is None:
                session = chat_store.get_or_create_active_session(
                    user_id,
                    metadata={"eval_session_alias": session_alias},
                )
                session_id = session.session_id
                sessions[session_key] = session_id
            message = {
                "role": _value(event, "role", "user"),
                "content": _value(event, "content", None),
            }
            metadata = _plain_json(_value(event, "metadata", {}) or {})
            if not isinstance(metadata, dict):
                raise ValueError("chat event metadata must be a JSON object")
            tool_calls = _value(event, "tool_calls", metadata.get("tool_calls"))
            if tool_calls is not None:
                message["tool_calls"] = tool_calls
            tool_call_id = _value(event, "tool_call_id", metadata.get("tool_call_id"))
            if tool_call_id is not None:
                message["tool_call_id"] = tool_call_id
            ids = chat_store.append_messages(
                session_id,
                user_id,
                [message],
                default_source_at=occurred_at,
                metadata_for_message=[metadata],
            )
            message_id = ids[0]
            content_type = _value(event, "content_type", None)
            tool_name = _value(event, "tool_name", metadata.get("tool_name"))
            if content_type is not None or tool_name is not None:
                with chat_store._connect() as conn:
                    conn.execute(
                        """
                        UPDATE chat_messages
                        SET content_type = COALESCE(?, content_type),
                            tool_name = COALESCE(?, tool_name)
                        WHERE message_id = ?
                        """,
                        (content_type, tool_name, message_id),
                    )
                    conn.commit()
            aliases[alias] = {
                "kind": kind,
                "user_id": user_id,
                "message_id": message_id,
                "source_ref": f"chat_message_id:{message_id}",
            }
            if notify and runtime is not None:
                runtime.sink.notify_chat_messages(user_id=user_id, message_ids=ids)
            return

        if kind == "tool_result":
            # Suppress the store observer while inserting so omitted
            # notifications genuinely exercise scanner catch-up.
            observer = tool_store._lifecycle_observer
            tool_store.set_lifecycle_observer(None)
            try:
                ref = tool_store.insert(
                    user_id=user_id,
                    run_id=_optional_str(_value(event, "run_id", None)),
                    tool_name=str(_value(event, "tool_name", "")),
                    turn=int(_value(event, "turn", 0)),
                    args_json=_optional_str(_value(event, "args_json", None)),
                    payload_json=str(_value(event, "payload_json", "")),
                    ok=bool(_value(event, "ok", True)),
                    cached=bool(_value(event, "cached", False)),
                    payload_kind=str(_value(event, "payload_kind", "result")),
                )
                occurred_at = _aware_datetime(_value(event, "occurred_at", None), "occurred_at")
                with tool_store._connect() as conn:
                    conn.execute(
                        "UPDATE tool_results SET created_at = ?, expires_at = ? WHERE ref = ?",
                        (
                            occurred_at.isoformat(),
                            (occurred_at + timedelta(days=30)).isoformat(),
                            ref,
                        ),
                    )
                    conn.commit()
            finally:
                tool_store.set_lifecycle_observer(observer)
            aliases[alias] = {
                "kind": kind,
                "user_id": user_id,
                "tool_result_ref": ref,
                "source_ref": f"tool_result_ref:{user_id}:{ref}",
            }
            if notify and runtime is not None:
                runtime.sink.notify_tool_inserted(user_id=user_id, ref=ref)
            return

        raise ValueError(f"unsupported resolved fixture event kind: {kind!r}")


class PR3ExtractionSubject(PR1IngestionSubject):
    """Run fixtures through real PR 1 ingestion and the production PR 3 processor."""

    subject_id = "pr3_extraction"
    pipeline_id = "text_candidates_v1"

    def __init__(self, model: Any, *, timezone: str = "Asia/Tashkent") -> None:
        super().__init__(extraction_model=model, timezone=timezone)


def create_subject(
    subject: str,
    *,
    actual_dir: str | Path | None = None,
    allow_network: bool = False,
) -> EvalSubject:
    if subject in {"ingestion", "pr1_ingestion"}:
        return PR1IngestionSubject()
    if subject in {"captured", "captured_output"}:
        if actual_dir is None:
            raise ValueError("actual_dir is required for captured output evaluation")
        return CapturedOutputSubject(actual_dir)
    if subject in {"extraction", "pr3_extraction"}:
        if not allow_network:
            raise ValueError("live extraction evaluation requires --allow-network")
        from config import get_settings
        from llm import LLMClient
        from memory.extraction.pipeline import LLMExtractionModel

        settings = get_settings()
        profile = settings.memory_extraction_model_profile
        client = LLMClient(settings, profile=profile)
        model = LLMExtractionModel(
            client,
            model_profile=profile,
            max_tokens=settings.memory_extraction_max_tokens,
        )
        return PR3ExtractionSubject(model, timezone=settings.bot_timezone)
    raise ValueError(f"unknown evaluation subject: {subject}")


def _eval_memory_config(
    memory_path: Path,
    context: EvalContext,
    case: Any,
    *,
    extraction_enabled: bool = False,
    extraction_model_profile: str = "summarize",
) -> Any:
    from memory.config import MemoryConfig

    segment_chars = context.text_segment_chars
    segment_overlap = context.text_segment_overlap
    nested = _value(case, "fixture", None)
    owner = nested if nested is not None else case
    for event in _value(owner, "events", ()) or ():
        metadata = _value(event, "metadata", {}) or {}
        if "eval_segment_chars" in metadata:
            segment_chars = int(metadata["eval_segment_chars"])
        if "eval_segment_overlap" in metadata:
            segment_overlap = int(metadata["eval_segment_overlap"])
    if segment_chars < 1 or segment_overlap < 0 or segment_overlap >= segment_chars:
        raise ValueError("fixture segment settings are invalid")

    return MemoryConfig(
        ingest_enabled=True,
        db_path=str(memory_path),
        worker_enabled=True,
        worker_concurrency=1,
        worker_poll_seconds=max(0.01, min(0.05, context.poll_interval_seconds)),
        job_lease_seconds=max(2, math.ceil(context.timeout_seconds) + 1),
        job_max_attempts=2,
        job_retry_base_seconds=0.01,
        job_retry_max_seconds=0.1,
        job_claim_batch_size=20,
        ingest_queue_maxsize=100,
        ingest_scan_interval_seconds=max(0.05, min(0.2, context.poll_interval_seconds * 2)),
        ingest_scan_batch_size=100,
        ingest_failure_max_attempts=2,
        ingest_retry_base_seconds=0.01,
        ingest_retry_max_seconds=0.1,
        text_segment_chars=segment_chars,
        text_segment_overlap=segment_overlap,
        tool_reconcile_batch_size=100,
        ingest_shutdown_grace_seconds=1.0,
        extraction_enabled=extraction_enabled,
        extraction_model_profile=extraction_model_profile,
        extraction_max_tokens=4096,
    )


async def _wait_for_ingestion(
    service: Any,
    runtime: Any,
    *,
    expected_sources: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        with service.db.connection() as conn:
            source_count = int(
                conn.execute("SELECT COUNT(*) AS count FROM memory_sources").fetchone()["count"]
            )
            job_rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM memory_jobs GROUP BY status"
            ).fetchall()
        jobs = {str(row["status"]): int(row["count"]) for row in job_rows}
        in_flight = jobs.get("pending", 0) + jobs.get("running", 0)
        job_count = sum(jobs.values())
        queue_empty = runtime.status().queue_size == 0
        if (
            source_count >= expected_sources
            and job_count >= expected_sources
            and in_flight == 0
            and queue_empty
        ):
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(
                "PR1 ingestion did not settle before timeout "
                f"(sources={source_count}/{expected_sources}, jobs={jobs}, "
                f"queue={runtime.status().queue_size})"
            )
        service.wake_worker()
        await asyncio.sleep(poll_interval_seconds)


def _collect_ingestion_output(
    *,
    service: Any,
    chat_reader: Any,
    tool_reader: Any,
    fixture_id: str,
    aliases: Mapping[str, Mapping[str, Any]],
    elapsed_seconds: float,
    subject_type: str = "ingestion",
) -> SubjectOutput:
    with service.db.connection() as conn:
        source_rows = conn.execute("SELECT * FROM memory_sources ORDER BY source_id").fetchall()
        version_rows = conn.execute(
            "SELECT * FROM memory_source_versions ORDER BY source_id, source_version_id"
        ).fetchall()
        job_rows = conn.execute(
            "SELECT * FROM memory_jobs ORDER BY source_version_id, job_id"
        ).fetchall()
        segment_rows = conn.execute(
            "SELECT * FROM memory_segments ORDER BY source_version_id, ordinal, segment_id"
        ).fetchall()
        mention_rows = conn.execute(
            "SELECT * FROM memory_mentions ORDER BY segment_id, mention_id"
        ).fetchall()
        candidate_rows = conn.execute(
            "SELECT * FROM memory_claim_candidates ORDER BY candidate_id"
        ).fetchall()
        evidence_rows = conn.execute(
            "SELECT * FROM memory_candidate_evidence ORDER BY candidate_id, segment_id, pointer_json"
        ).fetchall()

    sources = tuple(
        {
            "source_id": str(row["source_id"]),
            "user_id": int(row["user_id"]),
            "session_id": row["session_id"],
            "source_type": str(row["source_type"]),
            "source_ref": str(row["source_ref"]),
            "status": str(row["status"]),
            "authority_class": str(row["authority_class"]),
            "metadata": _json_object(row["metadata_json"]),
        }
        for row in source_rows
    )
    source_by_id = {item["source_id"]: item for item in sources}
    versions = tuple(
        {
            "source_version_id": str(row["source_version_id"]),
            "source_id": str(row["source_id"]),
            "content_hash": str(row["content_hash"]),
            "mime_type": row["mime_type"],
            "occurred_at": row["occurred_at"],
            "status": str(row["status"]),
            "supersedes_version_id": row["supersedes_version_id"],
            "pointer": _json_object(row["pointer_json"]),
            "metadata": _json_object(row["metadata_json"]),
        }
        for row in version_rows
    )
    jobs = tuple(
        {
            "job_id": str(row["job_id"]),
            "user_id": int(row["user_id"]),
            "source_version_id": str(row["source_version_id"]),
            "stage": str(row["stage"]),
            "status": str(row["status"]),
            "attempts": int(row["attempts"]),
            "max_attempts": int(row["max_attempts"]),
            "processor_name": str(row["processor_name"]),
            "processor_version": str(row["processor_version"]),
            "prompt_version": row["prompt_version"],
            "model_profile": row["model_profile"],
            "input_hash": str(row["input_hash"]),
            "output": _json_object(row["output_json"]),
        }
        for row in job_rows
    )
    segments = tuple(
        {
            "segment_id": str(row["segment_id"]),
            "source_version_id": str(row["source_version_id"]),
            "parent_segment_id": row["parent_segment_id"],
            "segment_type": str(row["segment_type"]),
            "ordinal": int(row["ordinal"]),
            "text": row["text"],
            "pointer": _json_object(row["pointer_json"]),
            "normalizer_name": str(row["normalizer_name"]),
            "normalizer_version": str(row["normalizer_version"]),
            "input_hash": str(row["input_hash"]),
            "status": str(row["status"]),
        }
        for row in segment_rows
    )
    version_by_id = {item["source_version_id"]: item for item in versions}
    source_event_by_ref = {
        str(value.get("source_ref")): str(key)
        for key, value in aliases.items()
        if value.get("source_ref") is not None
    }
    segment_by_id = {item["segment_id"]: item for item in segments}
    mention_output: list[dict[str, Any]] = []
    for row in mention_rows:
        segment = segment_by_id[str(row["segment_id"])]
        version = version_by_id[segment["source_version_id"]]
        source = source_by_id[version["source_id"]]
        pointer = _json_object(row["pointer_json"])
        location = pointer.get("location", {})
        mention_output.append(
            {
                "mention_id": str(row["mention_id"]),
                "source_event": source_event_by_ref.get(str(source["source_ref"]), ""),
                "mention_type": str(row["mention_type"]),
                "surface_text": str(row["surface_text"]),
                "char_start": int(location.get("char_start", 0)),
                "char_end": int(location.get("char_end", 0)),
                "normalized_hint": row["normalized_hint"],
                "pointer": pointer,
            }
        )
    evidence_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for row in evidence_rows:
        segment = segment_by_id[str(row["segment_id"])]
        version = version_by_id[segment["source_version_id"]]
        source = source_by_id[version["source_id"]]
        pointer = _json_object(row["pointer_json"])
        location = pointer.get("location", {})
        evidence_by_candidate.setdefault(str(row["candidate_id"]), []).append(
            {
                "source_event": source_event_by_ref.get(str(source["source_ref"]), ""),
                "relation": str(row["evidence_relation"]),
                "exact_quote": row["exact_quote"],
                "char_start": int(location.get("char_start", 0)),
                "char_end": int(location.get("char_end", 0)),
            }
        )
    candidate_output: list[dict[str, Any]] = []
    for row in candidate_rows:
        arguments = json.loads(str(row["arguments_json"]))
        normalized_arguments = []
        for argument in arguments:
            if "mention_id" in argument:
                normalized_arguments.append(
                    {
                        "role": argument["role"],
                        "mention_ref": argument["mention_id"],
                        "literal": None,
                        "has_literal": False,
                    }
                )
            else:
                normalized_arguments.append(
                    {
                        "role": argument["role"],
                        "mention_ref": None,
                        "literal": argument.get("literal"),
                        "has_literal": True,
                    }
                )
        candidate_output.append(
            {
                "candidate_ref": str(row["candidate_id"]),
                "kind": str(row["candidate_kind"]),
                "schema_name": str(row["schema_name"]),
                "schema_version": str(row["schema_version"]),
                "arguments": normalized_arguments,
                "attributes": _json_object(row["attributes_json"]),
                "polarity": str(row["polarity"]),
                "epistemic": _json_object(row["epistemic_json"]),
                "temporal": _json_object(row["temporal_json"]) if row["temporal_json"] else None,
                "status": str(row["status"]),
                "evidence": evidence_by_candidate.get(str(row["candidate_id"]), []),
            }
        )
    pointer_checks: list[dict[str, Any]] = []
    for version in versions:
        source = source_by_id[version["source_id"]]
        pointer_checks.append(
            _check_pointer(
                target_kind="source_version",
                target_id=version["source_version_id"],
                source_version_id=version["source_version_id"],
                pointer=version["pointer"],
                expected_text=None,
                source=source,
                chat_reader=chat_reader,
                tool_reader=tool_reader,
            )
        )
    for segment in segments:
        version = version_by_id[segment["source_version_id"]]
        source = source_by_id[version["source_id"]]
        extractive_segment = segment["segment_type"] in {
            "chat_text",
            "chat_tool_message",
            "tool_payload",
        }
        pointer_checks.append(
            _check_pointer(
                target_kind="segment",
                target_id=segment["segment_id"],
                source_version_id=segment["source_version_id"],
                pointer=segment["pointer"],
                expected_text=segment["text"] if extractive_segment else None,
                source=source,
                chat_reader=chat_reader,
                tool_reader=tool_reader,
            )
        )
    return SubjectOutput(
        fixture_id=fixture_id,
        sources=sources,
        source_versions=versions,
        jobs=jobs,
        segments=segments,
        pointer_checks=tuple(pointer_checks),
        mentions=tuple(mention_output),
        candidates=tuple(candidate_output),
        metadata={
            "event_aliases": {key: dict(value) for key, value in sorted(aliases.items())},
            "elapsed_seconds": elapsed_seconds,
            "file_backed": True,
            "subject_type": subject_type,
        },
    )


def _check_pointer(
    *,
    target_kind: str,
    target_id: str,
    source_version_id: str,
    pointer: Mapping[str, Any],
    expected_text: str | None,
    source: Mapping[str, Any],
    chat_reader: Any,
    tool_reader: Any,
) -> dict[str, Any]:
    from memory.pointers import pointer_from_mapping, verify_pointer_ownership

    result: dict[str, Any] = {
        "target_kind": target_kind,
        "target_id": target_id,
        "pointer": dict(pointer),
        "owner_ok": False,
        "dereference_ok": False,
        "text_ok": None if expected_text is None else False,
    }
    try:
        parsed = pointer_from_mapping(pointer)
        verify_pointer_ownership(
            parsed,
            user_id=int(source["user_id"]),
            source_version_id=source_version_id,
            source_user_id=int(source["user_id"]),
        )
        result["owner_ok"] = True
        text = _dereference_pointer(
            parsed,
            user_id=int(source["user_id"]),
            chat_reader=chat_reader,
            tool_reader=tool_reader,
        )
        result["dereference_ok"] = text is not None
        if expected_text is not None:
            result["text_ok"] = text == expected_text
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _dereference_pointer(
    pointer: Any,
    *,
    user_id: int,
    chat_reader: Any,
    tool_reader: Any,
) -> str | None:
    location = pointer.location
    if pointer.kind in {"chat_message", "chat_span"}:
        record = chat_reader.get_message_for_user(int(location["chat_message_id"]), user_id)
        if record is None:
            return None
        if record.content_type == "tool_calls":
            from memory.ids import canonical_json

            raw = record.metadata.get("tool_calls")
            text = canonical_json(raw) if raw is not None else ""
        elif record.content_type == "image" and not record.content:
            text = f"[image message from {record.role}]"
        else:
            text = record.content or ""
        if pointer.kind == "chat_span":
            return text[int(location["char_start"]) : int(location["char_end"])]
        return text
    if pointer.kind == "tool_result":
        record = tool_reader.get_by_ref_for_user(str(location["tool_result_ref"]), user_id)
        if record is None:
            return None
        text = record.payload_json
        if "char_start" in location:
            return text[int(location["char_start"]) : int(location["char_end"])]
        return text
    return None


def _partition_events(case: Any) -> tuple[list[Any], list[Any]]:
    nested = _value(case, "fixture", None)
    owner = nested if nested is not None else case
    baseline = list(_value(owner, "baseline_events", ()) or ())
    live: list[Any] = []
    for event in list(_value(owner, "events", ()) or ()):
        metadata = _value(event, "metadata", {}) or {}
        phase = str(
            _value(event, "phase", metadata.get("eval_phase", ""))
        ).lower()
        if phase in {"baseline", "historical", "before_enable"}:
            baseline.append(event)
        else:
            live.append(event)
    return baseline, live


def _resolved_users(case: Any) -> dict[str, int]:
    nested = _value(case, "fixture", None)
    owner = nested if nested is not None else case
    raw_map = (
        _value(case, "user_ids", None)
        or _value(case, "user_id_by_alias", None)
        or _value(owner, "user_ids", None)
        or {}
    )
    result: dict[str, int] = {}
    if isinstance(raw_map, Mapping):
        for alias, value in raw_map.items():
            if isinstance(value, Mapping) or hasattr(value, "user_id"):
                value = _value(value, "user_id", _value(value, "id", None))
            result[str(alias)] = _positive_user_id(value)
    for user in list(_value(owner, "users", ()) or ()):
        alias = _value(user, "user_alias", _value(user, "alias", None))
        user_id = _value(user, "user_id", _value(user, "id", None))
        if alias is not None and user_id is not None:
            result[str(alias)] = _positive_user_id(user_id)
    return result


def _event_user_id(event: Any, users: Mapping[str, int]) -> int:
    direct = _value(event, "user_id", None)
    if direct is not None:
        return _positive_user_id(direct)
    alias = str(_value(event, "user_alias", "")).strip()
    if alias not in users:
        raise ValueError(f"resolved fixture does not provide user_id for alias {alias!r}")
    return users[alias]


def _event_delivery(event: Any, context: EvalContext) -> str:
    metadata = _value(event, "metadata", {}) or {}
    raw = _value(
        event,
        "delivery",
        _value(event, "ingestion_mode", metadata.get("eval_delivery")),
    )
    if raw is None:
        notify = _value(event, "notify", None)
        if notify is False:
            raw = "catchup"
    if raw is None:
        per_event = context.metadata.get("delivery_by_event", {})
        if isinstance(per_event, Mapping):
            raw = per_event.get(str(_value(event, "event_id", "")))
    delivery = str(raw or "live").lower().replace("-", "_")
    if delivery in {"live", "notify", "notification"}:
        return "live"
    if delivery in {"catchup", "catch_up", "scanner", "omit_notification", "no_notify"}:
        return "catchup"
    raise ValueError(f"unsupported fixture event delivery mode: {raw!r}")


def _fixture_id(case: Any) -> str:
    value = _value(case, "fixture_id", None)
    if value is None:
        nested = _value(case, "fixture", None)
        value = _value(nested, "fixture_id", None) if nested is not None else None
    fixture_id = str(value or "").strip()
    if not fixture_id:
        raise ValueError("resolved fixture is missing fixture_id")
    return fixture_id


def _value(value: Any, name: str, default: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _positive_user_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("user_id must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("user_id must be a positive integer") from exc
    if result < 1:
        raise ValueError("user_id must be a positive integer")
    return result


def _aware_datetime(value: Any, field_name: str) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO datetime") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _json_object(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    decoded = json.loads(str(value))
    if not isinstance(decoded, dict):
        raise ValueError("database JSON field must contain an object")
    return decoded


def _plain_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _safe_name(value: str) -> str:
    clean = "".join(char if char.isalnum() or char in "-_" else "-" for char in value)
    if clean:
        return clean[:40]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _reject_duplicate_json_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SubjectOutputError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_non_finite_json_number(value: str) -> Any:
    raise SubjectOutputError(f"non-finite JSON number is forbidden: {value}")


def _validate_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SubjectOutputError(f"non-finite number at {path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SubjectOutputError(f"non-string object key at {path}")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise SubjectOutputError(f"non-JSON value at {path}: {type(value).__name__}")
