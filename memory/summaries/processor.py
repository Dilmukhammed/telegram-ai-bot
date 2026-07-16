from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from memory.ids import canonical_json
from memory.models import ProcessorContext, ProcessorOutput
from memory.summaries.eligibility import eligible_for_summary_type
from memory.summaries.generation.generator import (
    SummaryGeneratorModel,
    generate_summary_draft,
    summary_input_hash,
)
from memory.summaries.jobs import (
    SUMMARY_GENERATE_STAGE,
    decode_summary_target,
    summary_job_input_hash,
)
from memory.summaries.loaders import load_belief_snapshots, load_graph_snapshot
from memory.summaries.schemas import (
    GENERATOR_NAME,
    GENERATOR_VERSION,
    STATUS_ACTIVE,
    STATUS_REJECTED,
    SUMMARY_TYPE_COMMUNITY,
    SummaryConfig,
)
from memory.summaries.store import CommunityStore, SummaryStore
from memory.summaries.telemetry import log_summary_generated, log_summary_rejected
from memory.summaries.verification.pipeline import (
    SummaryVerifierModel,
    verify_summary_draft,
)

if TYPE_CHECKING:
    from memory.processors import ProcessorRegistry
    from memory.service import MemoryService


class SummaryGenerateProcessor:
    name = GENERATOR_NAME
    version = GENERATOR_VERSION
    stages = frozenset({SUMMARY_GENERATE_STAGE})

    def __init__(
        self,
        *,
        service: "MemoryService",
        config: SummaryConfig,
        generator_model: SummaryGeneratorModel | None = None,
        verifier_model: SummaryVerifierModel | None = None,
        summaries: SummaryStore | None = None,
        communities: CommunityStore | None = None,
    ) -> None:
        self._service = service
        self._config = config
        self._generator = generator_model
        self._verifier = verifier_model
        self._summaries = summaries or SummaryStore(service.db)
        self._communities = communities or CommunityStore(service.db)

    async def process(self, context: ProcessorContext) -> ProcessorOutput:
        if not self._config.summaries_enabled:
            raise RuntimeError("summaries are disabled")
        if not self._config.generation_enabled:
            raise RuntimeError("summary generation is disabled")
        job = context.job
        if job.target_kind != "summary" or not job.target_id:
            raise ValueError("summary job requires summary target")
        summary_type, target_id = decode_summary_target(job.target_id)
        with self._service.db.connection() as conn:
            beliefs = load_belief_snapshots(conn, user_id=job.user_id)
            _, _, graph_revision = load_graph_snapshot(conn, user_id=job.user_id)
            member_ids: frozenset[str] | None = None
            if summary_type == SUMMARY_TYPE_COMMUNITY:
                row = conn.execute(
                    """
                    SELECT member_belief_ids_json
                    FROM graph_communities
                    WHERE community_id = ? AND user_id = ?
                    """,
                    (target_id, job.user_id),
                ).fetchone()
                if row is None:
                    raise ValueError(f"unknown community target: {target_id!r}")
                import json

                member_ids = frozenset(
                    str(x) for x in json.loads(row["member_belief_ids_json"] or "[]")
                )
        eligible = eligible_for_summary_type(
            beliefs,
            summary_type=summary_type,
            target_id=target_id,
            member_belief_ids=member_ids,
        )
        belief_hash = summary_input_hash(
            user_id=job.user_id,
            summary_type=summary_type,
            target_id=target_id,
            beliefs=eligible,
        )
        expected_hash = summary_job_input_hash(
            user_id=job.user_id,
            summary_type=summary_type,
            target_id=target_id,
            input_hash=belief_hash,
            generation_enabled=self._config.generation_enabled,
            verify_enabled=self._config.verify_enabled,
            model_profile=self._config.model_profile,
            verify_model_profile=self._config.verify_model_profile,
        )
        if expected_hash != job.input_hash:
            raise RuntimeError("summary job input hash mismatch")
        if self._generator is None:
            raise RuntimeError("summary generator model is not configured")
        draft = await generate_summary_draft(
            user_id=job.user_id,
            summary_type=summary_type,
            target_id=target_id,
            beliefs=beliefs,
            model=self._generator,
            member_belief_ids=member_ids,
        )
        verification = await verify_summary_draft(
            draft,
            input_beliefs=eligible,
            model=self._verifier,
            verify_enabled=self._config.verify_enabled,
        )
        status = STATUS_ACTIVE if verification.accepted else STATUS_REJECTED
        summary_id = ""
        with self._service.db.transaction(immediate=True) as conn:
            if verification.accepted:
                self._summaries.supersede_active_in_txn(
                    conn,
                    user_id=job.user_id,
                    summary_type=summary_type,
                    target_id=target_id,
                )
            summary_id = self._summaries.insert_in_txn(
                conn,
                user_id=job.user_id,
                summary_type=summary_type,
                target_id=target_id,
                draft=draft,
                input_hash=belief_hash,
                status=status,
                graph_revision=graph_revision,
                model_profile=self._config.model_profile,
            )
        if verification.accepted:
            log_summary_generated(
                user_id=job.user_id,
                summary_type=summary_type,
                target_id=target_id,
                status=status,
                summary_id=summary_id,
            )
        else:
            log_summary_rejected(
                user_id=job.user_id,
                summary_type=summary_type,
                target_id=target_id,
                reason=verification.reject_reason,
            )
        payload = {
            "summary_id": summary_id,
            "summary_type": summary_type,
            "target_id": target_id,
            "status": status,
            "accepted": verification.accepted,
            "reject_reason": verification.reject_reason,
        }
        return ProcessorOutput(
            output_hash=_hash_payload(payload),
            output_json={
                "schema_version": "1",
                "generator_name": GENERATOR_NAME,
                "generator_version": GENERATOR_VERSION,
                **payload,
            },
        )


def register_summary_generator(
    registry: "ProcessorRegistry",
    *,
    service: "MemoryService",
    config: SummaryConfig,
    generator_model: SummaryGeneratorModel | None = None,
    verifier_model: SummaryVerifierModel | None = None,
) -> SummaryGenerateProcessor:
    processor = SummaryGenerateProcessor(
        service=service,
        config=config,
        generator_model=generator_model,
        verifier_model=verifier_model,
    )
    registry.register(processor)
    return processor


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
