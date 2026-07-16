from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from memory.attachment.events_store import AttachmentEventsStore
from memory.attachment.jobs import ATTACH_ANALYZE_STAGE, attach_job_input_hash
from memory.attachment.materializer import AttachmentMaterializer
from memory.attachment.pipeline import analyze_attachment
from memory.attachment.schemas import (
    PROCESSOR_NAME,
    PROCESSOR_VERSION,
    attachment_config_from_memory_config,
)
from memory.ids import canonical_json
from memory.models import ProcessorContext, ProcessorOutput

if TYPE_CHECKING:
    from memory.processors import ProcessorRegistry
    from memory.service import MemoryService


class AttachmentAnalyzeProcessor:
    name = PROCESSOR_NAME
    version = PROCESSOR_VERSION
    stages = frozenset({ATTACH_ANALYZE_STAGE})

    def __init__(
        self,
        *,
        service: "MemoryService",
        hypothesis_model: Any = None,
        support_model: Any = None,
        adversarial_model: Any = None,
        alt_model: Any = None,
        cluster_model: Any = None,
        research_model: Any = None,
        events: AttachmentEventsStore | None = None,
        materializer: AttachmentMaterializer | None = None,
    ) -> None:
        self._service = service
        self._config = attachment_config_from_memory_config(service.config)
        self._hypothesis_model = hypothesis_model
        self._support_model = support_model
        self._adversarial_model = adversarial_model
        self._alt_model = alt_model
        self._cluster_model = cluster_model
        self._research_model = research_model
        self._events = events or AttachmentEventsStore(service.db)
        self._materializer = materializer or AttachmentMaterializer(service.db)

    async def process(self, context: ProcessorContext) -> ProcessorOutput:
        if not self._config.enabled:
            raise RuntimeError("attachment engine is disabled")
        if not self._config.generation_enabled:
            raise RuntimeError("attachment generation is disabled")
        job = context.job
        if job.target_kind != "belief" or not job.target_id:
            raise ValueError("attach job requires belief target")
        belief_id = str(job.target_id)
        expected = attach_job_input_hash(
            user_id=job.user_id,
            belief_id=belief_id,
            generation_enabled=self._config.generation_enabled,
            verify_enabled=self._config.verify_enabled,
            model_profile=self._config.model_profile,
            react_enabled=self._config.react_enabled,
            react_mode=self._config.react_mode,
            react_model_profile=self._config.react_model_profile,
        )
        if expected != job.input_hash:
            raise RuntimeError("attachment job input hash mismatch")

        # LLM calls can take minutes. A deferred connection keeps the read
        # context available without acquiring SQLite's global write lock;
        # writes begin only after the committee has returned. Never wrap this
        # await in BEGIN IMMEDIATE.
        with self._service.db.connection() as conn:
            research: dict[str, Any] = {}
            try:
                result = await analyze_attachment(
                    conn,
                    user_id=job.user_id,
                    belief_id=belief_id,
                    config=self._config,
                    hypothesis_model=self._hypothesis_model,
                    support_model=self._support_model,
                    adversarial_model=self._adversarial_model,
                    alt_model=self._alt_model,
                    cluster_model=self._cluster_model,
                    research_model=self._research_model,
                    research_sink=research,
                    commit=True,
                    events_store=self._events,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        # Separate txn — nested immediate write deadlocks SQLite.
        if self._config.write_graph_edges:
            self._materializer.reconcile_events(user_id=job.user_id)

        payload = {
            "belief_id": belief_id,
            "accepted": result.accepted,
            "abstain_reason": result.abstain_reason,
            "hypothesis": asdict(result.hypothesis) if result.hypothesis else None,
            "accepted_hypotheses": [
                asdict(item) for item in result.accepted_hypotheses
            ],
            "utility_class": result.utility_class,
            "llm_calls": result.llm_calls,
            "research": research or None,
        }
        return ProcessorOutput(
            output_hash=_hash_payload(payload),
            output_json={
                "schema_version": "1",
                "processor_name": PROCESSOR_NAME,
                "processor_version": PROCESSOR_VERSION,
                **payload,
            },
        )


def register_attachment_analyzer(
    registry: "ProcessorRegistry",
    *,
    service: "MemoryService",
    hypothesis_model: Any = None,
    support_model: Any = None,
    adversarial_model: Any = None,
    alt_model: Any = None,
    cluster_model: Any = None,
    research_model: Any = None,
) -> AttachmentAnalyzeProcessor:
    processor = AttachmentAnalyzeProcessor(
        service=service,
        hypothesis_model=hypothesis_model,
        support_model=support_model,
        adversarial_model=adversarial_model,
        alt_model=alt_model,
        cluster_model=cluster_model,
        research_model=research_model,
    )
    registry.register(processor)
    return processor


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
