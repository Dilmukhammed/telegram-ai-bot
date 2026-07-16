"""One-shot: re-apply PR7 correction winners on data/graph_lab."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from memory.config import MemoryConfig
from memory.graph.materializer import GraphMaterializer
from memory.resolution.jobs import resolution_job_request
from memory.resolution.pipeline import register_candidate_resolver
from memory.resolution.rebuild import rebuild_ready_candidates
from memory.service import MemoryService
from memory.verification.scoring import DEFAULT_POLICY_VERSION


POLICY = DEFAULT_POLICY_VERSION
DB = Path("data/graph_lab/memory.sqlite")


async def main() -> None:
    if not DB.exists():
        raise SystemExit(f"missing {DB}")
    config = MemoryConfig(
        ingest_enabled=False,
        db_path=str(DB),
        worker_enabled=True,
        worker_concurrency=1,
        worker_poll_seconds=0.02,
        job_lease_seconds=30,
        job_max_attempts=2,
        job_retry_base_seconds=0.05,
        job_retry_max_seconds=0.2,
        job_claim_batch_size=4,
        resolution_enabled=True,
        graph_enabled=True,
        required_verification_policy_version=POLICY,
    )
    service = MemoryService(config=config)
    register_candidate_resolver(
        service.registry,
        service=service,
        required_verification_policy=POLICY,
    )
    with service.db.transaction() as conn:
        corr = conn.execute(
            """
            SELECT candidate_id FROM memory_claim_candidates
            WHERE schema_name LIKE 'corrects%' OR candidate_kind='correction'
            ORDER BY created_at
            """
        ).fetchall()
        cand_ids = [str(r["candidate_id"]) for r in corr]
        # Also clear synthetic winners.
        winner_ids = [
            f"{cid}:winner" for cid in cand_ids
        ]
        all_ids = cand_ids + winner_ids
        if all_ids:
            placeholders = ",".join("?" for _ in all_ids)
            conn.execute(
                f"DELETE FROM memory_belief_support WHERE assertion_id IN "
                f"(SELECT assertion_id FROM memory_assertions WHERE candidate_id IN ({placeholders}))",
                all_ids,
            )
            conn.execute(
                f"DELETE FROM memory_assertions WHERE candidate_id IN ({placeholders})",
                all_ids,
            )
            # Drop synthetic winner candidates so ensure can recreate.
            winners = [cid for cid in all_ids if cid.endswith(":winner")]
            if winners:
                wp = ",".join("?" for _ in winners)
                conn.execute(
                    f"DELETE FROM memory_claim_candidates WHERE candidate_id IN ({wp})",
                    winners,
                )
        print("cleared correction assertions:", cand_ids)

    rebuilt = rebuild_ready_candidates(
        service,
        user_id=1,
        limit=50,
        required_verification_policy=POLICY,
    )
    print("rebuild", rebuilt)
    # Force reopen if assertion-less correction still has a done job.
    with service.db.connection() as conn:
        for row in conn.execute(
            """
            SELECT c.candidate_id, score.score_id, score.verdict_set_hash,
                   j.job_id, j.source_version_id, j.status
            FROM memory_claim_candidates c
            JOIN memory_candidate_scores score
              ON score.candidate_id=c.candidate_id AND score.status='active'
            JOIN memory_processor_runs er ON er.run_id=c.extraction_run_id
            JOIN memory_jobs ej ON ej.job_id=er.job_id
            LEFT JOIN memory_jobs j
              ON j.user_id=c.user_id AND j.stage='candidate_resolve'
             AND j.target_id=c.candidate_id
            WHERE c.user_id=1 AND (c.schema_name LIKE 'corrects%' OR c.candidate_kind='correction')
            """
        ).fetchall():
            print("corr job", dict(row))
            if row["job_id"] and str(row["status"]) in {"done", "failed", "dead"}:
                service.jobs.reopen_terminal_job(
                    str(row["job_id"]), user_id=1, reason="pr7_lab_reapply"
                )
            elif row["job_id"] is None:
                service.jobs.enqueue(
                    1,
                    str(row["source_version_id"]),
                    resolution_job_request(
                        str(row["candidate_id"]),
                        score_id=str(row["score_id"]),
                        verdict_set_hash=str(row["verdict_set_hash"]),
                        required_verification_policy=POLICY,
                    ),
                )
    await service.start_worker()
    # Wait for resolution jobs + assertion materialization.
    for _ in range(400):
        with service.db.connection() as conn:
            pending = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM memory_jobs
                    WHERE stage='candidate_resolve'
                      AND status IN ('queued','leased','running','pending')
                    """
                ).fetchone()["c"]
            )
            corr_assertions = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM memory_assertions
                    WHERE schema_name LIKE 'corrects%' OR candidate_id LIKE '%:winner'
                    """
                ).fetchone()["c"]
            )
        if pending == 0 and corr_assertions > 0:
            break
        service.wake_worker()
        await asyncio.sleep(0.05)
    else:
        with service.db.connection() as conn:
            errs = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT job_id, status, last_error FROM memory_jobs
                    WHERE stage='candidate_resolve'
                    ORDER BY created_at DESC LIMIT 5
                    """
                )
            ]
        print("timeout waiting for resolve", errs)
    GraphMaterializer(
        service.db, store=service.graph, outbox=service.graph_outbox
    ).drain_once(limit=100)

    with service.db.connection() as conn:
        heads = [
            dict(r)
            for r in conn.execute(
                """
                SELECT b.schema_name, r.belief_status, r.utility_class,
                       r.resolved_arguments_json
                FROM memory_belief_heads h
                JOIN memory_belief_revisions r ON r.belief_revision_id=h.belief_revision_id
                JOIN memory_beliefs b ON b.belief_id=h.belief_id
                WHERE b.schema_name IN ('prefers_food','likes','corrects_preference')
                   OR b.schema_name LIKE 'corrects%'
                ORDER BY b.schema_name, b.created_at
                """
            ).fetchall()
        ]
        edges = [
            dict(r)
            for r in conn.execute(
                """
                SELECT e.edge_type, e.status, n.label AS to_label
                FROM graph_edges e
                JOIN graph_nodes n ON n.node_id=e.to_node_id
                WHERE e.status='active'
                ORDER BY e.edge_type
                """
            ).fetchall()
        ]
    print("beliefs:")
    Path("data/graph_lab/_pr7_apply_out.json").write_text(
        json.dumps({"beliefs": heads, "edges": edges}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote data/graph_lab/_pr7_apply_out.json")
    await service.stop_worker(grace_seconds=0.5)


if __name__ == "__main__":
    asyncio.run(main())
