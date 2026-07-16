from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from memory.db import utc_now_iso
from memory.ids import canonical_json, make_belief_id
from memory.models import ProcessorContext, ProcessorOutput
from memory.resolution.assertions import build_assertion, is_correction_candidate, proposition_key
from memory.resolution.beliefs import reconcile_belief
from memory.resolution.canonical import canonical_arguments
from memory.resolution.critics import LinkCriticModel, critique_proposed_alias
from memory.resolution.entities import (
    accept_proposed_alias,
    resolve_literal_argument,
    resolve_mention_argument,
)
from memory.resolution.er_resolve import resolve_mention_with_er
from memory.resolution.er_types import ErConfig, MergeEventRecord
from memory.resolution.jobs import (
    CANDIDATE_RESOLVE_STAGE,
    resolution_input_hash,
)
from memory.resolution.schemas import (
    RESOLUTION_PROMPT_VERSION,
    RESOLVER_NAME,
    RESOLVER_VERSION,
    AliasRecord,
    AssertionRecord,
    BeliefRevisionRecord,
    BeliefSupportRecord,
    EntityRecord,
    MentionLinkRecord,
    ResolutionBatch,
    ResolutionVerdictRecord,
    ResolvedArgument,
)
from memory.resolution.temporal import (
    assertion_with_status,
    build_temporal_apply_plan,
)

if TYPE_CHECKING:
    from memory.processors import ProcessorRegistry
    from memory.service import MemoryService


class CandidateResolutionProcessor:
    name = RESOLVER_NAME
    version = RESOLVER_VERSION
    stages = frozenset({CANDIDATE_RESOLVE_STAGE})

    def __init__(
        self,
        *,
        service: "MemoryService",
        required_verification_policy: str,
        support_model: LinkCriticModel | None = None,
        adversarial_model: LinkCriticModel | None = None,
        support_profile: str = "extraction",
        adversarial_profile: str = "agent",
        er_config: ErConfig | None = None,
    ) -> None:
        self._service = service
        self._required_verification_policy = required_verification_policy
        self._support_model = support_model
        self._adversarial_model = adversarial_model
        self._support_profile = support_profile
        self._adversarial_profile = adversarial_profile
        self._er_config = er_config or ErConfig()

    async def process(self, context: ProcessorContext) -> ProcessorOutput:
        job = context.job
        if job.target_kind != "candidate" or not job.target_id:
            raise ValueError("candidate resolution job requires candidate target")
        candidate = self._service.resolution.load_ready_candidate(
            job.target_id,
            user_id=job.user_id,
            required_verification_policy=self._required_verification_policy,
        )
        if candidate is None:
            raise ValueError(f"unknown resolution candidate: {job.target_id}")
        if candidate["primary_source_version_id"] != job.source_version_id:
            raise ValueError("resolution candidate source version mismatch")
        if candidate["status"] != "ready_for_resolution":
            raise ValueError(
                f"candidate is not ready for resolution: {candidate['status']!r}"
            )
        score = candidate.get("score")
        if not isinstance(score, dict):
            raise ValueError("ready candidate is missing active verification score")
        if str(score.get("route_status")) != "ready_for_resolution":
            raise ValueError(
                f"score route is not ready_for_resolution: {score.get('route_status')!r}"
            )
        actual_hash = resolution_input_hash(
            job.target_id,
            score_id=str(score["score_id"]),
            verdict_set_hash=str(score["verdict_set_hash"]),
            required_verification_policy=self._required_verification_policy,
            support_profile=self._support_profile,
            adversarial_profile=self._adversarial_profile,
            candidate_generation_enabled=self._er_config.candidate_generation_enabled,
            fuzzy_blocking_enabled=self._er_config.fuzzy_blocking_enabled,
            fuzzy_min_trigram=self._er_config.fuzzy_min_trigram,
            cross_language_enabled=self._er_config.cross_language_enabled,
            cluster_critic_enabled=self._er_config.cluster_critic_enabled,
            merge_events_enabled=self._er_config.merge_events_enabled,
            max_candidates=self._er_config.max_candidates,
        )
        if actual_hash != job.input_hash:
            raise RuntimeError(
                "resolution input hash mismatch: "
                f"expected {job.input_hash!r}, got {actual_hash!r}"
            )

        batch = await self._resolve_candidate(candidate, user_id=job.user_id)
        payload = {
            "candidate_id": job.target_id,
            "assertion_id": batch.assertion.assertion_id if batch.assertion else None,
            "belief_revision_id": (
                batch.belief_revision.belief_revision_id if batch.belief_revision else None
            ),
            "entity_count": len(batch.entities),
            "critic_verdict_count": len(batch.resolution_verdicts),
        }
        return ProcessorOutput(
            output_hash=_hash_payload(payload),
            output_json={
                "schema_version": "1",
                "resolver_name": RESOLVER_NAME,
                "resolver_version": RESOLVER_VERSION,
                "prompt_version": RESOLUTION_PROMPT_VERSION,
                **payload,
            },
            resolution_batch=batch,
        )

    async def _resolve_candidate(
        self,
        candidate: dict[str, Any],
        *,
        user_id: int,
    ) -> ResolutionBatch:
        entities: list[EntityRecord] = []
        aliases: list[AliasRecord] = []
        links: list[MentionLinkRecord] = []
        verdicts: list[ResolutionVerdictRecord] = []
        merge_events: list[MergeEventRecord] = []
        resolved_args: list[ResolvedArgument] = []
        entity_by_id: dict[str, EntityRecord] = {}
        mentions = candidate.get("mentions") or {}
        authority = None
        occurred_at = None
        for evidence in candidate.get("evidence") or ():
            if isinstance(evidence, dict):
                authority = evidence.get("authority_class") or authority
                occurred_at = evidence.get("source_occurred_at") or occurred_at

        with self._service.db.connection() as conn:
            if self._er_config.candidate_generation_enabled:
                mention_args: list[tuple[str, dict[str, Any]]] = []
                for argument in candidate.get("arguments") or ():
                    if not isinstance(argument, dict):
                        continue
                    role = str(argument.get("role") or "")
                    mention_id = argument.get("mention_id")
                    if mention_id:
                        mention = mentions.get(str(mention_id))
                        if mention is None:
                            raise ValueError(f"missing mention for argument role {role!r}")
                        if str(mention.get("status")) != "active":
                            raise ValueError(f"inactive mention for argument role {role!r}")
                        mention_args.append((role, mention))
                        continue
                    if argument.get("has_literal") or "literal" in argument:
                        resolved, entity = resolve_literal_argument(
                            conn,
                            user_id=user_id,
                            role=role,
                            literal=argument.get("literal"),
                        )
                        resolved_args.append(resolved)
                        if entity is not None:
                            entities.append(entity)
                            entity_by_id[entity.entity_id] = entity
                        continue
                    raise ValueError(f"argument {role!r} has neither mention nor literal")

                neighbor_preview = [
                    {"role": role, "mention_surface": mention.get("surface_text")}
                    for role, mention in mention_args
                ]
                for role, mention in mention_args:
                    er_result = await resolve_mention_with_er(
                        conn,
                        user_id=user_id,
                        role=role,
                        mention=mention,
                        support_model=self._support_model,
                        adversarial_model=self._adversarial_model,
                        neighboring_arguments=neighbor_preview,
                        source_authority=str(authority) if authority else None,
                        source_occurred_at=str(occurred_at) if occurred_at else None,
                        config=self._er_config,
                    )
                    resolved_args.append(er_result.resolved)
                    entities.append(er_result.entity)
                    entity_by_id[er_result.entity.entity_id] = er_result.entity
                    if (
                        er_result.provisional_entity is not None
                        and er_result.provisional_entity.entity_id != er_result.entity.entity_id
                    ):
                        entities.append(er_result.provisional_entity)
                        entity_by_id[er_result.provisional_entity.entity_id] = (
                            er_result.provisional_entity
                        )
                    links.append(er_result.link)
                    if er_result.alias is not None:
                        aliases.append(er_result.alias)
                    verdicts.extend(er_result.verdicts)
                    merge_events.extend(er_result.merge_events)
            else:
                pending: list[tuple[str, dict[str, Any], Any, Any, Any, Any, Any]] = []
                for argument in candidate.get("arguments") or ():
                    if not isinstance(argument, dict):
                        continue
                    role = str(argument.get("role") or "")
                    mention_id = argument.get("mention_id")
                    if mention_id:
                        mention = mentions.get(str(mention_id))
                        if mention is None:
                            raise ValueError(f"missing mention for argument role {role!r}")
                        if str(mention.get("status")) != "active":
                            raise ValueError(f"inactive mention for argument role {role!r}")
                        resolved, entity, alias, link, proposal = resolve_mention_argument(
                            conn,
                            user_id=user_id,
                            role=role,
                            mention=mention,
                        )
                        pending.append(
                            (role, mention, resolved, entity, alias, link, proposal)
                        )
                        continue
                    if argument.get("has_literal") or "literal" in argument:
                        resolved, entity = resolve_literal_argument(
                            conn,
                            user_id=user_id,
                            role=role,
                            literal=argument.get("literal"),
                        )
                        resolved_args.append(resolved)
                        if entity is not None:
                            entities.append(entity)
                            entity_by_id[entity.entity_id] = entity
                        continue
                    raise ValueError(f"argument {role!r} has neither mention nor literal")

                neighbor_preview = [
                    {"role": role, "mention_surface": mention.get("surface_text")}
                    for role, mention, *_rest in pending
                ]

                for role, mention, resolved, entity, alias, link, proposal in pending:
                    if proposal is None:
                        resolved_args.append(resolved)
                        entities.append(entity)
                        entity_by_id[entity.entity_id] = entity
                        links.append(link)
                        if alias is not None:
                            aliases.append(alias)
                        continue
                    accepted, critic_verdicts, reason = await critique_proposed_alias(
                        proposal,
                        support_model=self._support_model,
                        adversarial_model=self._adversarial_model,
                        neighboring_arguments=neighbor_preview,
                        source_authority=str(authority) if authority else None,
                        source_occurred_at=str(occurred_at) if occurred_at else None,
                    )
                    verdicts.extend(critic_verdicts)
                    if accepted:
                        resolved, entity, alias, link = accept_proposed_alias(
                            user_id=user_id,
                            role=role,
                            mention=mention,
                            proposal=proposal,
                        )
                        link = MentionLinkRecord(
                            link_id=link.link_id,
                            mention_id=link.mention_id,
                            entity_id=link.entity_id,
                            decision=link.decision,
                            resolution_components={
                                **dict(link.resolution_components),
                                "critic_reason": reason,
                            },
                        )
                    else:
                        link = MentionLinkRecord(
                            link_id=link.link_id,
                            mention_id=link.mention_id,
                            entity_id=link.entity_id,
                            decision="provisional_new",
                            resolution_components={
                                **dict(link.resolution_components),
                                "decision": "provisional_new",
                                "critic_reason": reason,
                            },
                        )
                        entity = EntityRecord(
                            entity_id=entity.entity_id,
                            entity_type=entity.entity_type,
                            identity_key=entity.identity_key,
                            canonical_label=entity.canonical_label,
                            status="provisional",
                            decision="provisional_new",
                        )
                    resolved_args.append(resolved)
                    entities.append(entity)
                    entity_by_id[entity.entity_id] = entity
                    links.append(link)
                    if alias is not None:
                        aliases.append(alias)

            assertion = build_assertion(
                candidate=candidate,
                resolved_arguments=resolved_args,
                recorded_at=utc_now_iso(),
            )
            assertion = _assertion_for_belief_reconcile(
                conn,
                user_id=user_id,
                assertion=assertion,
                resolved_arguments=resolved_args,
                merge_events_enabled=self._er_config.merge_events_enabled,
            )
            is_correction = is_correction_candidate(candidate)
            plan = build_temporal_apply_plan(
                conn,
                user_id=user_id,
                candidate=candidate,
                assertion=assertion,
                entity_by_id=entity_by_id,
            )
            for ent in plan.winner_entities:
                entities.append(ent)
                entity_by_id[ent.entity_id] = ent
            _hydrate_entities_for_assertions(
                conn,
                user_id=user_id,
                assertions=list(plan.prior_assertions)
                + ([plan.winner_assertion] if plan.winner_assertion else []),
                entity_by_id=entity_by_id,
            )

            additional_assertions: list[AssertionRecord] = []
            additional_revisions: list[BeliefRevisionRecord] = []
            historicalize_ids: list[str] = []

            if plan.kind in {"correction", "cessation"} and plan.prior_assertions:
                historicalize_ids.extend(
                    item.assertion_id for item in plan.prior_assertions
                )
                for prior in plan.prior_assertions:
                    prior_hist = assertion_with_status(prior, "historical")
                    existing_prior = (
                        self._service.resolution.list_assertions_for_proposition(
                            conn,
                            user_id=user_id,
                            proposition_key=prior.proposition_key,
                        )
                    )
                    by_id = {
                        item.assertion_id: (
                            prior_hist
                            if item.assertion_id == prior.assertion_id
                            else (
                                assertion_with_status(item, "historical")
                                if item.assertion_id in {
                                    p.assertion_id for p in plan.prior_assertions
                                }
                                else item
                            )
                        )
                        for item in existing_prior
                    }
                    by_id[prior_hist.assertion_id] = prior_hist
                    belief_id_probe = make_belief_id(
                        user_id=user_id, proposition_key=prior.proposition_key
                    )
                    prior_head = self._service.resolution.get_belief_head(
                        conn,
                        belief_id=belief_id_probe,
                        user_id=user_id,
                    )
                    loser_revision = reconcile_belief(
                        user_id=user_id,
                        assertion=prior_hist,
                        supporting_assertions=list(by_id.values()),
                        entity_by_id=entity_by_id,
                        is_correction=False,
                        prior_head_revision_id=prior_head,
                    )
                    additional_revisions.append(loser_revision)

            if plan.kind == "correction" and plan.winner_assertion is not None:
                winner = _assertion_for_belief_reconcile(
                    conn,
                    user_id=user_id,
                    assertion=plan.winner_assertion,
                    resolved_arguments=plan.winner_assertion.resolved_arguments,
                    merge_events_enabled=self._er_config.merge_events_enabled,
                )
                additional_assertions.append(winner)
                existing_winner = (
                    self._service.resolution.list_assertions_for_proposition(
                        conn,
                        user_id=user_id,
                        proposition_key=winner.proposition_key,
                    )
                )
                by_id = {
                    item.assertion_id: (
                        assertion_with_status(item, "historical")
                        if item.assertion_id in set(historicalize_ids)
                        else item
                    )
                    for item in existing_winner
                }
                by_id[winner.assertion_id] = winner
                belief_id_probe = make_belief_id(
                    user_id=user_id, proposition_key=winner.proposition_key
                )
                prior_head = self._service.resolution.get_belief_head(
                    conn,
                    belief_id=belief_id_probe,
                    user_id=user_id,
                )
                winner_revision = reconcile_belief(
                    user_id=user_id,
                    assertion=winner,
                    supporting_assertions=list(by_id.values()),
                    entity_by_id=entity_by_id,
                    is_correction=False,
                    prior_head_revision_id=prior_head,
                )
                # Lineage: correction assertion corrects the winner domain fact.
                winner_revision = BeliefRevisionRecord(
                    belief_revision_id=winner_revision.belief_revision_id,
                    belief_id=winner_revision.belief_id,
                    proposition_key=winner_revision.proposition_key,
                    cluster_key=winner_revision.cluster_key,
                    schema_name=winner_revision.schema_name,
                    input_set_hash=winner_revision.input_set_hash,
                    resolved_arguments=winner_revision.resolved_arguments,
                    resolved_value=winner_revision.resolved_value,
                    polarity=winner_revision.polarity,
                    temporal=winner_revision.temporal,
                    belief_status=winner_revision.belief_status,
                    utility_class=winner_revision.utility_class,
                    utility_reason_codes=winner_revision.utility_reason_codes,
                    confidence_components=winner_revision.confidence_components,
                    supersedes_revision_id=winner_revision.supersedes_revision_id,
                    support=tuple(winner_revision.support)
                    + (
                        BeliefSupportRecord(
                            assertion_id=assertion.assertion_id,
                            relation="corrects",
                            weight_components={"status": assertion.status},
                        ),
                    ),
                )
                additional_revisions.append(winner_revision)

            existing = self._service.resolution.list_assertions_for_proposition(
                conn,
                user_id=user_id,
                proposition_key=assertion.proposition_key,
            )
            hist_ids = set(historicalize_ids)
            by_id = {
                item.assertion_id: (
                    assertion_with_status(item, "historical")
                    if item.assertion_id in hist_ids
                    else item
                )
                for item in existing
            }
            by_id[assertion.assertion_id] = assertion
            supporting = list(by_id.values())
            belief_id_probe = make_belief_id(
                user_id=user_id, proposition_key=assertion.proposition_key
            )
            prior_head = self._service.resolution.get_belief_head(
                conn,
                belief_id=belief_id_probe,
                user_id=user_id,
            )
            support_relations = None
            if plan.kind == "correction" and plan.prior_assertions:
                support_relations = {
                    assertion.assertion_id: "supports",
                    **{
                        prior.assertion_id: "corrects"
                        for prior in plan.prior_assertions
                    },
                }
            revision = reconcile_belief(
                user_id=user_id,
                assertion=assertion,
                supporting_assertions=supporting,
                entity_by_id=entity_by_id,
                is_correction=is_correction,
                prior_head_revision_id=prior_head,
                support_relations=support_relations,
            )

        entities = list({item.entity_id: item for item in entities}.values())
        aliases = list({item.alias_id: item for item in aliases}.values())
        links = list({item.link_id: item for item in links}.values())
        return ResolutionBatch(
            entities=tuple(entities),
            aliases=tuple(aliases),
            mention_links=tuple(links),
            resolution_verdicts=tuple(verdicts),
            assertion=assertion,
            belief_revision=revision,
            set_belief_head=True,
            additional_assertions=tuple(additional_assertions),
            additional_belief_revisions=tuple(additional_revisions),
            historicalize_assertion_ids=tuple(dict.fromkeys(historicalize_ids)),
            merge_events=tuple(merge_events),
        )


def register_candidate_resolver(
    registry: "ProcessorRegistry",
    *,
    service: "MemoryService",
    required_verification_policy: str,
    support_model: LinkCriticModel | None = None,
    adversarial_model: LinkCriticModel | None = None,
    support_profile: str = "extraction",
    adversarial_profile: str = "agent",
    er_config: ErConfig | None = None,
) -> CandidateResolutionProcessor:
    processor = CandidateResolutionProcessor(
        service=service,
        required_verification_policy=required_verification_policy,
        support_model=support_model,
        adversarial_model=adversarial_model,
        support_profile=support_profile,
        adversarial_profile=adversarial_profile,
        er_config=er_config,
    )
    registry.register(processor)
    return processor


def _hash_payload(payload: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _assertion_for_belief_reconcile(
    conn: Any,
    *,
    user_id: int,
    assertion: AssertionRecord,
    resolved_arguments: tuple[ResolvedArgument, ...] | list[ResolvedArgument],
    merge_events_enabled: bool,
) -> AssertionRecord:
    if not merge_events_enabled:
        return assertion
    canonical_args = canonical_arguments(conn, user_id, resolved_arguments)
    canonical_prop = proposition_key(
        candidate_kind=assertion.candidate_kind,
        schema_name=assertion.schema_name,
        schema_version=assertion.schema_version,
        resolved_arguments=canonical_args,
        attributes=assertion.attributes,
    )
    if canonical_prop == assertion.proposition_key:
        return assertion
    return replace(assertion, proposition_key=canonical_prop)


def _hydrate_entities_for_assertions(
    conn: Any,
    *,
    user_id: int,
    assertions: list[AssertionRecord],
    entity_by_id: dict[str, EntityRecord],
) -> None:
    missing: set[str] = set()
    for assertion in assertions:
        for arg in assertion.resolved_arguments:
            if (
                arg.value_kind == "entity"
                and arg.entity_id
                and arg.entity_id not in entity_by_id
            ):
                missing.add(arg.entity_id)
    if not missing:
        return
    placeholders = ",".join("?" for _ in missing)
    rows = conn.execute(
        f"""
        SELECT entity_id, entity_type, identity_key, canonical_label, status
        FROM memory_entities
        WHERE user_id = ? AND entity_id IN ({placeholders})
        """,
        (user_id, *sorted(missing)),
    ).fetchall()
    for row in rows:
        entity_by_id[str(row["entity_id"])] = EntityRecord(
            entity_id=str(row["entity_id"]),
            entity_type=str(row["entity_type"]),
            identity_key=str(row["identity_key"]),
            canonical_label=str(row["canonical_label"]),
            status=str(row["status"]),
            decision="loaded",
        )
