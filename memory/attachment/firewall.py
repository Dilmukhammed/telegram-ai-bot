from __future__ import annotations

from collections.abc import Callable

from memory.attachment.schemas import (
    DOMAIN_ALLOWED_OPS,
    ShortlistCandidate,
)


_PERSON_TYPES = frozenset({"person"})
_INCOMPATIBLE = {
    ("food", "person"),
    ("product", "person"),
    ("concept", "person"),
    ("dish", "person"),
}


def apply_firewall(
    candidates: tuple[ShortlistCandidate, ...],
    *,
    user_id: int,
    source_entity_id: str | None,
    source_entity_type: str | None,
    attach_domains: tuple[str, ...],
    existing_attachments: tuple[dict, ...],
    negatives_check: Callable[..., bool],
    max_candidates: int,
) -> tuple[ShortlistCandidate, ...]:
    allowed_ops: set[str] = set()
    for domain in attach_domains:
        allowed_ops.update(DOMAIN_ALLOWED_OPS.get(domain, frozenset()))

    active_pairs = {
        (str(row["op"]), str(row["target_entity_id"]))
        for row in existing_attachments
        if str(row.get("status")) == "active"
    }

    kept: list[ShortlistCandidate] = []
    for cand in candidates:
        if source_entity_id and cand.target_id == source_entity_id:
            continue
        if source_entity_type in _PERSON_TYPES or cand.entity_type in _PERSON_TYPES:
            continue
        pair_type = (source_entity_type or "concept", cand.entity_type)
        if pair_type in _INCOMPATIBLE or (pair_type[1], pair_type[0]) in _INCOMPATIBLE:
            continue
        if cand.metadata and cand.metadata.get("entity_status") == "provisional":
            continue
        op_hint = cand.op_hint
        if op_hint and op_hint not in allowed_ops:
            continue
        blocked = negatives_check(
            user_id=user_id,
            source_entity_id=source_entity_id or "",
            target_entity_id=cand.target_id,
            op=op_hint or "cuisine_of",
        )
        if blocked:
            continue
        dup = False
        for op, target_id in active_pairs:
            if target_id == cand.target_id and op == (op_hint or op):
                dup = True
                break
        if dup:
            continue
        kept.append(cand)
        if len(kept) >= max_candidates:
            break
    return tuple(kept)
