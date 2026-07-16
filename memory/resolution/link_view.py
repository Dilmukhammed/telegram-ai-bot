from __future__ import annotations

from typing import Any, Mapping, Sequence

from memory.resolution.schemas import ProposedExactAlias


def build_proposed_link_view(
    proposal: ProposedExactAlias,
    *,
    neighboring_arguments: Sequence[Mapping[str, Any]] = (),
    source_authority: str | None = None,
    source_occurred_at: str | None = None,
) -> dict[str, Any]:
    """Bounded view for entity-link critics. No raw instructions outside evidence."""
    return {
        "schema_version": "1",
        "proposed_link": {
            "mention_id": proposal.mention_id,
            "mention_type": proposal.mention_type,
            "surface_text": proposal.surface_text,
            "normalized_alias": proposal.normalized_alias,
            "argument_role": proposal.role,
            "proposed_entity": {
                "entity_id": proposal.proposed_entity.entity_id,
                "entity_type": proposal.proposed_entity.entity_type,
                "canonical_label": proposal.proposed_entity.canonical_label,
                "status": proposal.proposed_entity.status,
                "active_aliases": list(proposal.active_aliases),
            },
        },
        "neighboring_arguments": [dict(item) for item in neighboring_arguments],
        "source": {
            "authority_class": source_authority,
            "occurred_at": source_occurred_at,
        },
        "constraints": {
            "no_cross_type": True,
            "no_person_merge": True,
            "model_cannot_propose_target": True,
        },
    }
