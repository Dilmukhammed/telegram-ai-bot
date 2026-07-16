from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from memory.ids import canonical_json, make_belief_id, make_belief_revision_id
from memory.resolution.schemas import (
    RECONCILIATION_POLICY_VERSION,
    UTILITY_POLICY_VERSION,
    AssertionRecord,
    BeliefRevisionRecord,
    BeliefSupportRecord,
    EntityRecord,
)
from memory.resolution.utility import classify_utility


def _is_soft(epistemic: Mapping[str, Any], polarity: str) -> bool:
    if polarity == "unknown":
        return True
    if epistemic.get("needs_confirmation") is True:
        return True
    commitment = str(epistemic.get("speaker_commitment") or "")
    mode = str(epistemic.get("mode") or "")
    return commitment in {"possible", "probable", "uncertain", "unknown"} or mode in {
        "reported",
        "quoted",
        "inferred",
    }


def reconcile_belief(
    *,
    user_id: int,
    assertion: AssertionRecord,
    supporting_assertions: Sequence[AssertionRecord],
    entity_by_id: Mapping[str, EntityRecord],
    is_correction: bool,
    prior_head_revision_id: str | None,
    support_relations: Mapping[str, str] | None = None,
) -> BeliefRevisionRecord:
    """Reconcile over assertions sharing the same proposition_key."""
    active = [item for item in supporting_assertions if item.status == "active"]
    historical = [item for item in supporting_assertions if item.status == "historical"]
    invalidated = [item for item in supporting_assertions if item.status == "invalidated"]

    polarities = {item.polarity for item in active}
    soft = any(_is_soft(item.epistemic, item.polarity) for item in active)
    reason_codes: list[str] = []
    confidence: dict[str, Any] = {
        "active_count": len(active),
        "historical_count": len(historical),
        "invalidated_count": len(invalidated),
    }

    if not supporting_assertions or (
        not active and not historical and invalidated
    ):
        belief_status = "unsupported"
        polarity = assertion.polarity
    elif not active and historical:
        belief_status = "historical"
        polarity = historical[-1].polarity
    elif soft:
        belief_status = "uncertain"
        polarity = next(iter(polarities)) if len(polarities) == 1 else "unknown"
        reason_codes.append("uncertain_claim")
    elif {"positive", "negative"} <= polarities:
        belief_status = "uncertain"
        polarity = "unknown"
        reason_codes.append("polarity_conflict")
        confidence["polarity_conflict"] = True
    elif len(polarities) == 1:
        belief_status = "active"
        polarity = next(iter(polarities))
    else:
        belief_status = "uncertain"
        polarity = "unknown"
        reason_codes.append("mixed_polarity")

    # Historical / unsupported heads are never graph-eligible.
    if belief_status in {"historical", "unsupported"}:
        utility_class = "deferred"
        utility_reasons: tuple[str, ...] = ("not_current",)
    else:
        has_provisional = any(
            entity_by_id[arg.entity_id].status == "provisional"
            for item in active
            for arg in item.resolved_arguments
            if arg.value_kind == "entity" and arg.entity_id in entity_by_id
        )
        utility_class, utility_reasons = classify_utility(
            polarity=polarity,
            epistemic=assertion.epistemic,
            has_provisional_identity=has_provisional,
            is_correction=is_correction,
        )
    reason_codes.extend(utility_reasons)

    support_ids = sorted({item.assertion_id for item in supporting_assertions})
    input_set_hash = canonical_json(
        {
            "proposition_key": assertion.proposition_key,
            "assertion_ids": support_ids,
            "belief_status": belief_status,
            "polarity": polarity,
            "policy": RECONCILIATION_POLICY_VERSION,
        }
    )
    belief_id = make_belief_id(user_id=user_id, proposition_key=assertion.proposition_key)
    revision_id = make_belief_revision_id(
        belief_id=belief_id,
        input_set_hash=input_set_hash,
        reconciliation_policy_version=RECONCILIATION_POLICY_VERSION,
        utility_policy_version=UTILITY_POLICY_VERSION,
    )
    rel_map = dict(support_relations or {})
    support = tuple(
        BeliefSupportRecord(
            assertion_id=item.assertion_id,
            relation=rel_map.get(item.assertion_id, "supports"),
            weight_components={"status": item.status},
        )
        for item in supporting_assertions
    )
    head_assertion = next((item for item in active), assertion)
    return BeliefRevisionRecord(
        belief_revision_id=revision_id,
        belief_id=belief_id,
        proposition_key=assertion.proposition_key,
        cluster_key=assertion.cluster_key,
        schema_name=assertion.schema_name,
        input_set_hash=input_set_hash,
        resolved_arguments=head_assertion.resolved_arguments,
        resolved_value=None,
        polarity=polarity,
        temporal=head_assertion.temporal,
        belief_status=belief_status,
        utility_class=utility_class,
        utility_reason_codes=tuple(dict.fromkeys(reason_codes)),
        confidence_components=confidence,
        supersedes_revision_id=prior_head_revision_id,
        support=support,
    )


def replace_belief_support(
    revision: BeliefRevisionRecord,
    support: Sequence[BeliefSupportRecord],
) -> BeliefRevisionRecord:
    return replace(revision, support=tuple(support))
