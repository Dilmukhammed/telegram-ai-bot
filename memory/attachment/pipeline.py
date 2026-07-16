from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from typing import Any

from memory.attachment.context import load_context_pack
from memory.attachment.constraints import (
    apply_negative_preference_constraint_in_txn,
    blocks_inferred_preference,
    release_negative_preference_constraints_in_txn,
)
from memory.attachment.critics import (
    accepted_hypotheses_from_critics,
    accept_from_layers,
    run_adversarial_critic,
    run_alt_hypothesis_critic,
    run_cluster_critic,
    run_hypothesis_layer,
    run_support_critic,
    run_set_critic,
)
from memory.attachment.events_store import AttachmentEventsStore
from memory.attachment.firewall import apply_firewall
from memory.attachment.hypotheses import (
    filter_policy_compatible_hypotheses,
    merge_hypothesis_sources,
    seed_hypotheses_from_shortlist,
    select_compatible_hypotheses,
)
from memory.attachment.negative import is_negative_blocked
from memory.attachment.policy import (
    classify_risk,
    decide_utility_class,
    infer_tier,
    insert_negative,
    layers_for_risk,
    should_defer_inferred_preference,
)
from memory.attachment.retrieve import ensure_taxonomy_targets, retrieve_candidates
from memory.attachment.react import run_attachment_research
from memory.attachment.react_tools import AttachmentReactTools
from memory.attachment.schemas import (
    ATTACHMENT_VERSION,
    STATUS_ACTIVE,
    STATUS_POSSIBLE,
    TIER_CURATED,
    AttachmentAnalyzeResult,
    AttachmentConfig,
    AttachmentHypothesis,
    LayerVerdict,
    ShortlistCandidate,
    UTILITY_DEFERRED,
)
from memory.attachment.taxonomy import match_taxonomy
from memory.attachment.trigger import (
    enrich_subject_from_entities,
    run_trigger_gate,
    subject_from_belief_head,
)
from memory.db import utc_now_iso
from memory.ids import canonical_json, make_entity_id
from memory.resolution.schemas import RESOLVER_VERSION


async def analyze_attachment(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    belief_id: str,
    config: AttachmentConfig,
    hypothesis_model: Any = None,
    support_model: Any = None,
    adversarial_model: Any = None,
    alt_model: Any = None,
    cluster_model: Any = None,
    research_model: Any = None,
    research_sink: dict[str, Any] | None = None,
    commit: bool = False,
    events_store: AttachmentEventsStore | None = None,
) -> AttachmentAnalyzeResult:
    head = _load_head(conn, user_id=user_id, belief_id=belief_id)
    if head is None:
        return AttachmentAnalyzeResult(
            accepted=False,
            abstain_reason="missing_belief_head",
            hypothesis=None,
            utility_class=None,
            tier=None,
            domain_pack=None,
            shortlist=(),
            layer_trace=(),
            llm_calls=0,
            source_entity_id=None,
            source_belief_id=belief_id,
        )

    entity_id, label, entity_type = subject_from_belief_head(head)
    entity_id, label, entity_type = enrich_subject_from_entities(
        conn,
        user_id=user_id,
        entity_id=entity_id,
        label=label,
        entity_type=entity_type,
    )
    if not label:
        return AttachmentAnalyzeResult(
            accepted=False,
            abstain_reason="no_subject_label",
            hypothesis=None,
            utility_class=None,
            tier=None,
            domain_pack=None,
            shortlist=(),
            layer_trace=(),
            llm_calls=0,
            source_entity_id=entity_id,
            source_belief_id=belief_id,
        )

    if entity_id is None:
        entity_id = _ensure_subject_entity(
            conn,
            user_id=user_id,
            label=label,
            entity_type=entity_type,
            persist=commit,
        )

    schema_name = str(head.get("schema_name") or "")
    polarity = str(head.get("polarity") or "unknown")
    is_negative_preference = polarity == "negative" and (
        schema_name == "preference"
        or schema_name.startswith("likes_")
        or schema_name.startswith("prefer")
    )
    is_positive_preference = polarity == "positive" and (
        schema_name == "preference"
        or schema_name.startswith("likes_")
        or schema_name.startswith("prefer")
    )
    if commit and is_positive_preference:
        release_negative_preference_constraints_in_txn(
            conn,
            user_id=user_id,
            target_entity_id=entity_id,
        )
    if is_negative_preference:
        if commit:
            apply_negative_preference_constraint_in_txn(
                conn,
                user_id=user_id,
                target_entity_id=entity_id,
                source_belief_id=belief_id,
                scope="category" if entity_type == "concept" else "entity",
                reason={
                    "polarity": polarity,
                    "schema_name": schema_name,
                    "explicit": True,
                },
            )
        return AttachmentAnalyzeResult(
            accepted=False,
            abstain_reason="negative_constraint_applied" if commit else "negative_constraint_proposed",
            hypothesis=None,
            utility_class=None,
            tier=None,
            domain_pack="food",
            shortlist=(),
            layer_trace=(
                LayerVerdict(
                    "L0",
                    "constraint",
                    {"type": "negative_preference", "target_entity_id": entity_id},
                ),
            ),
            llm_calls=0,
            source_entity_id=entity_id,
            source_belief_id=belief_id,
            risk_class="low",
        )

    trigger = run_trigger_gate(
        schema_name=str(head.get("schema_name") or "preference"),
        entity_type=entity_type,
        mention_type=None,
        label=label,
        belief_status=str(head.get("belief_status") or "active"),
        utility_class=str(head.get("utility_class") or "durable"),
        curated_taxonomy_enabled=config.curated_taxonomy_enabled,
        candidate_kind=head.get("candidate_kind"),
    )
    if not trigger.should_run:
        return AttachmentAnalyzeResult(
            accepted=False,
            abstain_reason=trigger.skip_reason,
            hypothesis=None,
            utility_class=None,
            tier=None,
            domain_pack=None,
            shortlist=(),
            layer_trace=(),
            llm_calls=0,
            source_entity_id=entity_id,
            source_belief_id=belief_id,
        )

    pack = load_context_pack(
        conn,
        user_id=user_id,
        belief_id=belief_id,
        attach_domains=trigger.attach_domains,
        source_entity_id=entity_id,
        source_label=label,
        source_entity_type=entity_type,
    )
    if pack is None:
        return AttachmentAnalyzeResult(
            accepted=False,
            abstain_reason="context_unavailable",
            hypothesis=None,
            utility_class=None,
            tier=None,
            domain_pack=None,
            shortlist=(),
            layer_trace=(),
            llm_calls=0,
            source_entity_id=entity_id,
            source_belief_id=belief_id,
        )

    raw_candidates = retrieve_candidates(
        conn,
        user_id=user_id,
        source_entity_id=entity_id,
        source_label=label,
        attach_domains=trigger.attach_domains,
        curated_taxonomy_enabled=config.curated_taxonomy_enabled,
        vector_enabled=config.vector_enabled,
    )

    # L2.5 shadow research: the ReAct agent may inspect the bounded graph but
    # cannot alter candidates, policy, events, or graph rows. Its trace is
    # returned through research_sink for durable processor output and evals.
    if config.react_enabled:
        if research_model is None:
            if research_sink is not None:
                research_sink.update(
                    {
                        "schema_version": "1",
                        "mode": config.react_mode,
                        "status": "model_unavailable",
                        "trace": [],
                        "write_performed": False,
                    }
                )
        else:
            try:
                research = await run_attachment_research(
                    tools=AttachmentReactTools(
                        conn,
                        user_id=user_id,
                        max_results=config.react_max_results,
                        max_hops=config.react_max_hops,
                    ),
                    model=research_model,
                    config=config,
                    context=pack,
                    shortlist=raw_candidates[: config.max_candidates],
                )
            except Exception as exc:  # shadow research must never block PR14
                research = {
                    "schema_version": "1",
                    "mode": config.react_mode,
                    "status": "internal_error",
                    "error": str(exc)[:500],
                    "trace": [],
                    "write_performed": False,
                }
            if research_sink is not None:
                research_sink.update(research)

    def _neg_check(**kwargs: Any) -> bool:
        return is_negative_blocked(conn, **kwargs)

    shortlist = apply_firewall(
        raw_candidates,
        user_id=user_id,
        source_entity_id=entity_id,
        source_entity_type=entity_type,
        attach_domains=trigger.attach_domains,
        existing_attachments=pack.existing_attachments,
        negatives_check=_neg_check,
        max_candidates=config.max_candidates,
    )
    critic_context = {
        **asdict(pack),
        "shortlist_evidence": [asdict(candidate) for candidate in shortlist],
    }

    # Entity/constraint preflight may write, while the committee below can
    # await several LLM calls. Never retain SQLite's single writer lock across
    # those awaits: the ingestion scanner, heartbeats and HTTP status endpoint
    # must remain able to commit. Final attachment events start a fresh
    # transaction after the committee returns.
    if commit and conn.in_transaction:
        conn.commit()

    taxonomy_match = match_taxonomy(label, enabled=config.curated_taxonomy_enabled)
    curated = taxonomy_match is not None

    layers: list[LayerVerdict] = []
    llm_calls = 0
    winner: AttachmentHypothesis | None = None
    proposed: tuple[AttachmentHypothesis, ...] = ()
    hybrid_score = shortlist[0].score if shortlist else 0.0

    if not shortlist:
        return AttachmentAnalyzeResult(
            accepted=False,
            abstain_reason="empty_shortlist",
            hypothesis=None,
            utility_class=None,
            tier=None,
            domain_pack=trigger.attach_domains[0] if trigger.attach_domains else None,
            shortlist=(),
            layer_trace=tuple(layers),
            llm_calls=0,
            source_entity_id=entity_id,
            source_belief_id=belief_id,
        )

    if curated and taxonomy_match is not None:
        from memory.attachment.retrieve import taxonomy_parent_entity_id

        parent_id = taxonomy_parent_entity_id(
            user_id=user_id, parent_key=taxonomy_match.parent
        )
        winner = AttachmentHypothesis(
            op=taxonomy_match.op,
            target_id=parent_id,
        )
        proposed = (winner,)
        layers.append(LayerVerdict("L4", "curated", {"parent": taxonomy_match.parent}))
        risk = "low"
    elif config.generation_enabled:
        # A non-curated shortlist is exactly where semantic generation is
        # required. classify_risk(None) means "no hypothesis exists yet", not
        # that the engine should abstain and silently take shortlist[0].
        risk = "mid" if hybrid_score >= 0.5 else "high"
        needed = layers_for_risk(risk, verify_enabled=config.verify_enabled)
        if "L4" in needed:
            hyps, l4, calls = await run_hypothesis_layer(
                hypothesis_model,
                context_statement=pack.statement,
                shortlist=shortlist,
                attach_domains=trigger.attach_domains,
                context_pack=critic_context,
            )
            layers.append(l4)
            llm_calls += calls
            hyps = filter_policy_compatible_hypotheses(
                hyps,
                shortlist=shortlist,
                attach_domains=trigger.attach_domains,
            )
            seeded = seed_hypotheses_from_shortlist(shortlist)
            combined = merge_hypothesis_sources(seeded, hyps)
            combined = filter_policy_compatible_hypotheses(
                combined,
                shortlist=shortlist,
                attach_domains=trigger.attach_domains,
            )
            proposed = select_compatible_hypotheses(combined, max_items=3)
            winner = proposed[0] if proposed else None
        else:
            if shortlist:
                top = shortlist[0]
                winner = AttachmentHypothesis(
                    op=str(top.op_hint or "cuisine_of"),
                    target_id=top.target_id,
                )
                proposed = (winner,)
    else:
        return AttachmentAnalyzeResult(
            accepted=False,
            abstain_reason="generation_disabled",
            hypothesis=None,
            utility_class=None,
            tier=None,
            domain_pack=trigger.attach_domains[0] if trigger.attach_domains else None,
            shortlist=shortlist,
            layer_trace=tuple(layers),
            llm_calls=0,
            source_entity_id=entity_id,
            source_belief_id=belief_id,
        )

    if winner is None:
        return AttachmentAnalyzeResult(
            accepted=False,
            abstain_reason="no_unique_winner",
            hypothesis=None,
            utility_class=None,
            tier=None,
            domain_pack=trigger.attach_domains[0] if trigger.attach_domains else None,
            shortlist=shortlist,
            layer_trace=tuple(layers),
            llm_calls=llm_calls,
            source_entity_id=entity_id,
            source_belief_id=belief_id,
        )

    risk = classify_risk(hypothesis=winner, curated=curated, hybrid_score=hybrid_score)
    needed = layers_for_risk(risk, verify_enabled=config.verify_enabled)

    if len(proposed) > 1:
        return await _analyze_hypothesis_set(
            conn,
            user_id=user_id,
            belief_id=belief_id,
            source_entity_id=entity_id,
            source_label=label,
            domain_pack=trigger.attach_domains[0] if trigger.attach_domains else "food",
            proposed=proposed,
            shortlist=shortlist,
            context_pack=critic_context,
            context_statement=pack.statement,
            config=config,
            support_model=support_model,
            adversarial_model=adversarial_model,
            events_store=events_store,
            commit=commit,
            initial_layers=tuple(layers),
            initial_llm_calls=llm_calls,
            risk=risk,
        )

    if llm_calls >= config.max_llm_calls:
        return AttachmentAnalyzeResult(
            accepted=False,
            abstain_reason="budget_exceeded",
            hypothesis=winner,
            utility_class=None,
            tier=None,
            domain_pack=trigger.attach_domains[0] if trigger.attach_domains else None,
            shortlist=shortlist,
            layer_trace=tuple(layers),
            llm_calls=llm_calls,
            source_entity_id=entity_id,
            source_belief_id=belief_id,
            risk_class=risk,
        )

    if "L5" in needed and llm_calls < config.max_llm_calls:
        if curated:
            layers.append(
                LayerVerdict("L5", "supported", {"reason": "curated_taxonomy"})
            )
        else:
            l5, calls = await run_support_critic(
                support_model,
                hypothesis=winner,
                context_statement=pack.statement,
                context_pack=critic_context,
            )
            layers.append(l5)
            llm_calls += calls

    if "L6" in needed and llm_calls < config.max_llm_calls:
        l6, calls = await run_adversarial_critic(
            adversarial_model,
            hypothesis=winner,
            context_statement=pack.statement,
            context_pack=critic_context,
        )
        layers.append(l6)
        llm_calls += calls

    if "L7" in needed and llm_calls < config.max_llm_calls:
        l7, calls = await run_alt_hypothesis_critic(
            alt_model or hypothesis_model,
            hypothesis=winner,
            shortlist=shortlist,
            context_statement=pack.statement,
            context_pack=critic_context,
        )
        layers.append(l7)
        llm_calls += calls

    if "L8" in needed and llm_calls < config.max_llm_calls:
        l8, calls = await run_cluster_critic(
            cluster_model,
            hypothesis=winner,
            context_statement=pack.statement,
            context_pack=critic_context,
        )
        layers.append(l8)
        llm_calls += calls

    if curated and config.verify_enabled and not any(l.layer == "L5" for l in layers):
        l5, calls = await run_support_critic(
            support_model,
            hypothesis=winner,
            context_statement=pack.statement,
            context_pack=asdict(pack),
        )
        layers.append(l5)
        llm_calls += calls

    accepted, reject_reason = accept_from_layers(winner=winner, layers=layers)
    domain_pack = trigger.attach_domains[0] if trigger.attach_domains else "food"

    if winner.op == "inferred_preference" and not config.inferred_preference_enabled:
        accepted = False
        reject_reason = "inferred_preference_disabled"
    if winner.op == "inferred_preference" and blocks_inferred_preference(
        conn,
        user_id=user_id,
        target_entity_id=winner.target_id,
    ):
        accepted = False
        reject_reason = "negative_preference_constraint"

    utility = None
    tier = infer_tier(curated=curated, llm_calls=llm_calls)
    if accepted:
        if winner.op == "inferred_preference" and should_defer_inferred_preference(
            conn,
            user_id=user_id,
            target_entity_id=winner.target_id,
        ):
            utility = UTILITY_DEFERRED
        else:
            utility = decide_utility_class(
                conn,
                user_id=user_id,
                source_entity_id=entity_id,
                op=winner.op,
                target_entity_id=winner.target_id,
                explicit_cuisine=curated,
            )
    elif reject_reason:
        if reject_reason.startswith("adversarial") or reject_reason == "alt_hypothesis_preferred":
            insert_negative(
                conn,
                user_id=user_id,
                source_entity_id=entity_id,
                op=winner.op,
                target_entity_id=winner.target_id,
                reason=reject_reason,
                layer=reject_reason.split("_")[0],
            )

    if commit and accepted and events_store is not None:
        now = utc_now_iso()
        ensure_taxonomy_targets(conn, user_id=user_id, candidates=shortlist, now=now)
        evidence = {
            "belief_id": belief_id,
            "shortlist": [c.target_id for c in shortlist],
            "label": label,
        }
        evidence_hash = hashlib.sha256(
            canonical_json(evidence).encode("utf-8")
        ).hexdigest()
        input_hash = hashlib.sha256(
            canonical_json(
                {
                    "belief_id": belief_id,
                    "winner": asdict(winner),
                    "attachment_version": ATTACHMENT_VERSION,
                }
            ).encode("utf-8")
        ).hexdigest()
        event_id = events_store.insert_in_txn(
            conn,
            user_id=user_id,
            op=winner.op,
            source_belief_id=belief_id,
            source_entity_id=entity_id,
            target_entity_id=winner.target_id,
            domain_pack=domain_pack,
            tier=tier or TIER_CURATED,
            status=STATUS_ACTIVE,
            utility_class=utility or UTILITY_DEFERRED,
            evidence=evidence,
            evidence_hash=evidence_hash,
            critic_report={"layers": [asdict(l) for l in layers]},
            layer_trace={"layers": [asdict(l) for l in layers]},
            input_hash=input_hash,
            resolver_version=RESOLVER_VERSION,
        )
        dependencies: list[dict[str, Any]] = [
            {
                "dependency_type": "belief",
                "dependency_id": belief_id,
            }
        ]
        selected = next((c for c in shortlist if c.target_id == winner.target_id), None)
        if selected is not None and selected.metadata:
            for step in selected.metadata.get("graph_path") or ():
                if isinstance(step, dict) and step.get("edge_id"):
                    dependencies.append(
                        {
                            "dependency_type": "graph_edge",
                            "dependency_id": str(step["edge_id"]),
                            "path": list(selected.metadata.get("graph_path") or ()),
                        }
                    )
        events_store.insert_dependencies_in_txn(
            conn,
            event_id=event_id,
            user_id=user_id,
            dependencies=dependencies,
        )
    elif commit and not accepted and config.write_possible_events and events_store is not None:
        now = utc_now_iso()
        evidence = {"belief_id": belief_id, "reason": reject_reason}
        evidence_hash = hashlib.sha256(
            canonical_json(evidence).encode("utf-8")
        ).hexdigest()
        input_hash = evidence_hash
        events_store.insert_in_txn(
            conn,
            user_id=user_id,
            op=winner.op,
            source_belief_id=belief_id,
            source_entity_id=entity_id,
            target_entity_id=winner.target_id,
            domain_pack=domain_pack,
            tier=tier or TIER_CURATED,
            status=STATUS_POSSIBLE,
            utility_class=UTILITY_DEFERRED,
            evidence=evidence,
            evidence_hash=evidence_hash,
            critic_report=None,
            layer_trace={"layers": [asdict(l) for l in layers]},
            input_hash=input_hash,
            resolver_version=RESOLVER_VERSION,
        )

    return AttachmentAnalyzeResult(
        accepted=accepted,
        abstain_reason=reject_reason,
        hypothesis=winner,
        utility_class=utility,
        tier=tier,
        domain_pack=domain_pack,
        shortlist=shortlist,
        layer_trace=tuple(layers),
        llm_calls=llm_calls,
        source_entity_id=entity_id,
        source_belief_id=belief_id,
        risk_class=risk,
        accepted_hypotheses=(winner,) if accepted else (),
    )


async def _analyze_hypothesis_set(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    belief_id: str,
    source_entity_id: str,
    source_label: str,
    domain_pack: str,
    proposed: tuple[AttachmentHypothesis, ...],
    shortlist: tuple[ShortlistCandidate, ...],
    context_pack: dict[str, Any],
    context_statement: str,
    config: AttachmentConfig,
    support_model: Any,
    adversarial_model: Any,
    events_store: AttachmentEventsStore | None,
    commit: bool,
    initial_layers: tuple[LayerVerdict, ...],
    initial_llm_calls: int,
    risk: str,
) -> AttachmentAnalyzeResult:
    support, support_calls = await run_set_critic(
        support_model,
        layer="L5",
        hypotheses=proposed,
        context_statement=context_statement,
        context_pack=context_pack,
        adversarial=False,
    )
    adversarial, adversarial_calls = await run_set_critic(
        adversarial_model,
        layer="L6",
        hypotheses=proposed,
        context_statement=context_statement,
        context_pack=context_pack,
        adversarial=True,
    )
    llm_calls = initial_llm_calls + support_calls + adversarial_calls
    layers = list(initial_layers)
    layers.extend(
        (
            LayerVerdict(
                "L5-set",
                "complete",
                {f"{op}:{target}": item.verdict for (op, target), item in support.items()},
            ),
            LayerVerdict(
                "L6-set",
                "complete",
                {f"{op}:{target}": item.verdict for (op, target), item in adversarial.items()},
            ),
        )
    )
    accepted = list(
        accepted_hypotheses_from_critics(
            proposed, support=support, adversarial=adversarial, shortlist=shortlist
        )
    )
    if llm_calls > config.max_llm_calls:
        accepted = []
        reject_reason = "budget_exceeded"
    else:
        accepted = [
            hypothesis
            for hypothesis in accepted
            if not (
                hypothesis.op == "inferred_preference"
                and (
                    not config.inferred_preference_enabled
                    or blocks_inferred_preference(
                        conn,
                        user_id=user_id,
                        target_entity_id=hypothesis.target_id,
                    )
                )
            )
        ]
        reject_reason = None if accepted else "set_not_supported"

    accepted_set = tuple(accepted)
    primary = accepted_set[0] if accepted_set else proposed[0]
    primary_utility: str | None = None
    tier = infer_tier(curated=False, llm_calls=llm_calls)
    if commit and accepted_set and events_store is not None:
        ensure_taxonomy_targets(
            conn, user_id=user_id, candidates=shortlist, now=utc_now_iso()
        )
        for hypothesis in accepted_set:
            if hypothesis.op == "inferred_preference" and should_defer_inferred_preference(
                conn, user_id=user_id, target_entity_id=hypothesis.target_id
            ):
                utility = UTILITY_DEFERRED
            else:
                utility = decide_utility_class(
                    conn,
                    user_id=user_id,
                    source_entity_id=source_entity_id,
                    op=hypothesis.op,
                    target_entity_id=hypothesis.target_id,
                )
            if hypothesis == primary:
                primary_utility = utility
            selected = next(
                (item for item in shortlist if item.target_id == hypothesis.target_id),
                None,
            )
            evidence = {
                "belief_id": belief_id,
                "label": source_label,
                "hypothesis": asdict(hypothesis),
                "candidate": asdict(selected) if selected is not None else None,
            }
            evidence_hash = hashlib.sha256(
                canonical_json(evidence).encode("utf-8")
            ).hexdigest()
            input_hash = hashlib.sha256(
                canonical_json(
                    {
                        "belief_id": belief_id,
                        "hypothesis": asdict(hypothesis),
                        "attachment_version": ATTACHMENT_VERSION,
                    }
                ).encode("utf-8")
            ).hexdigest()
            event_id = events_store.insert_in_txn(
                conn,
                user_id=user_id,
                op=hypothesis.op,
                source_belief_id=belief_id,
                source_entity_id=source_entity_id,
                target_entity_id=hypothesis.target_id,
                domain_pack=domain_pack,
                tier=tier,
                status=STATUS_ACTIVE,
                utility_class=utility,
                evidence=evidence,
                evidence_hash=evidence_hash,
                critic_report={"layers": [asdict(layer) for layer in layers]},
                layer_trace={"layers": [asdict(layer) for layer in layers]},
                input_hash=input_hash,
                resolver_version=RESOLVER_VERSION,
            )
            dependencies: list[dict[str, Any]] = [
                {"dependency_type": "belief", "dependency_id": belief_id}
            ]
            if selected is not None and selected.metadata:
                path = list(selected.metadata.get("graph_path") or ())
                for step in path:
                    if isinstance(step, dict) and step.get("edge_id"):
                        dependencies.append(
                            {
                                "dependency_type": "graph_edge",
                                "dependency_id": str(step["edge_id"]),
                                "path": path,
                            }
                        )
            events_store.insert_dependencies_in_txn(
                conn,
                event_id=event_id,
                user_id=user_id,
                dependencies=dependencies,
            )

    return AttachmentAnalyzeResult(
        accepted=bool(accepted_set),
        abstain_reason=reject_reason,
        hypothesis=primary,
        utility_class=primary_utility,
        tier=tier,
        domain_pack=domain_pack,
        shortlist=shortlist,
        layer_trace=tuple(layers),
        llm_calls=llm_calls,
        source_entity_id=source_entity_id,
        source_belief_id=belief_id,
        risk_class=risk,
        accepted_hypotheses=accepted_set,
    )


def _load_head(
    conn: sqlite3.Connection, *, user_id: int, belief_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT b.belief_id, b.schema_name, b.proposition_key,
               r.belief_status, r.utility_class, r.polarity,
               r.resolved_arguments_json,
               (
                 SELECT a.candidate_kind
                 FROM memory_belief_support s
                 JOIN memory_assertions a ON a.assertion_id = s.assertion_id
                 WHERE s.belief_revision_id = r.belief_revision_id
                   AND s.relation = 'supports'
                 ORDER BY a.created_at DESC LIMIT 1
               ) AS candidate_kind
        FROM memory_belief_heads h
        JOIN memory_beliefs b ON b.belief_id = h.belief_id
        JOIN memory_belief_revisions r ON r.belief_revision_id = h.belief_revision_id
        WHERE h.belief_id = ? AND h.user_id = ?
        """,
        (belief_id, user_id),
    ).fetchone()
    return dict(row) if row else None


def _ensure_subject_entity(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    label: str,
    entity_type: str | None,
    persist: bool = True,
) -> str:
    from memory.attachment.taxonomy import normalize_label

    identity_key = f"label:{normalize_label(label)}"
    row = conn.execute(
        """
        SELECT entity_id FROM memory_entities
        WHERE user_id = ? AND identity_key = ?
        """,
        (user_id, identity_key),
    ).fetchone()
    if row is not None:
        return str(row["entity_id"])
    entity_id = make_entity_id(
        user_id=user_id,
        entity_type=entity_type or "product",
        identity_key=identity_key,
        resolver_version=RESOLVER_VERSION,
    )
    if not persist:
        return entity_id
    now = utc_now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO memory_entities(
            entity_id, user_id, entity_type, identity_key,
            canonical_label, status, resolver_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (
            entity_id,
            user_id,
            entity_type or "product",
            identity_key,
            label,
            RESOLVER_VERSION,
            now,
            now,
        ),
    )
    return entity_id
