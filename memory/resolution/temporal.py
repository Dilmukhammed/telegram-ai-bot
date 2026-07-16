"""PR7 temporal reconciliation — correction/cessation apply plans."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from memory.ids import make_assertion_id
from memory.resolution.assertions import (
    is_correction_candidate,
    proposition_key,
)
from memory.resolution.normalization import display_label, lookup_key
from memory.resolution.schemas import (
    ASSERTION_SCHEMA_VERSION,
    RESOLVER_VERSION,
    AssertionRecord,
    EntityRecord,
    ResolvedArgument,
)
from memory.verification.adversarial import looks_like_correction


_SUBJECT_ROLES = frozenset(
    {
        "subject",
        "self",
        "person",
        "agent",
        "actor",
        "owner",
        "user",
    }
)
_VALUE_ROLES = frozenset(
    {
        "value",
        "object",
        "item",
        "game",
        "attribute",
        "description",
        "target",
        "food",
        "team",
        "topic",
        "skill",
        "place",
        "org",
        "organization",
        "product",
        "entity",
    }
)
_OLD_ROLES = frozenset({"old", "previous", "from"})
_NEW_ROLES = frozenset({"new", "current", "to", "replacement"})


@dataclass(frozen=True, slots=True)
class TemporalApplyPlan:
    kind: str  # none | correction | cessation
    prior_assertions: tuple[AssertionRecord, ...] = ()
    winner_assertion: AssertionRecord | None = None
    winner_entities: tuple[EntityRecord, ...] = ()
    reason_codes: tuple[str, ...] = ()


def build_temporal_apply_plan(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    candidate: Mapping[str, Any],
    assertion: AssertionRecord,
    entity_by_id: Mapping[str, EntityRecord],
) -> TemporalApplyPlan:
    if is_correction_candidate(candidate):
        return _plan_correction(
            conn,
            user_id=user_id,
            candidate=candidate,
            assertion=assertion,
            entity_by_id=entity_by_id,
        )
    if str(assertion.polarity) == "negative":
        return _plan_cessation(
            conn,
            user_id=user_id,
            assertion=assertion,
            entity_by_id=entity_by_id,
        )
    return TemporalApplyPlan(kind="none")


def _plan_correction(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    candidate: Mapping[str, Any],
    assertion: AssertionRecord,
    entity_by_id: Mapping[str, EntityRecord],
) -> TemporalApplyPlan:
    priors = _find_priors_via_evidence(
        conn,
        user_id=user_id,
        candidate_id=str(candidate["candidate_id"]),
        candidate_segment_id=str(candidate.get("segment_id") or ""),
    )
    old_arg = _arg_by_roles(assertion.resolved_arguments, _OLD_ROLES)
    if old_arg is not None and priors:
        old_label = _entity_label(old_arg, entity_by_id, conn, user_id=user_id)
        matched = [
            prior
            for prior in priors
            if _assertion_value_matches(
                prior,
                old_label,
                old_arg.entity_id,
                entity_by_id,
                conn,
                user_id,
            )
        ]
        priors = matched
    if not priors:
        priors = _find_priors_by_old_value(
            conn,
            user_id=user_id,
            assertion=assertion,
            entity_by_id=entity_by_id,
        )
    if not priors:
        return TemporalApplyPlan(
            kind="correction",
            reason_codes=("correction_no_prior",),
        )

    new_arg = _arg_by_roles(assertion.resolved_arguments, _NEW_ROLES)
    if new_arg is None:
        return TemporalApplyPlan(
            kind="correction",
            prior_assertions=tuple(priors),
            reason_codes=("correction_missing_new",),
        )

    prior = priors[0]
    winner, winner_entities = _build_winner_assertion(
        prior=prior,
        correction=assertion,
        new_arg=new_arg,
        entity_by_id=entity_by_id,
    )
    return TemporalApplyPlan(
        kind="correction",
        prior_assertions=tuple(priors),
        winner_assertion=winner,
        winner_entities=tuple(winner_entities),
        reason_codes=("correction_applied",),
    )


def _plan_cessation(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    assertion: AssertionRecord,
    entity_by_id: Mapping[str, EntityRecord],
) -> TemporalApplyPlan:
    priors = _find_positive_priors_for_negative(
        conn,
        user_id=user_id,
        assertion=assertion,
        entity_by_id=entity_by_id,
    )
    if not priors:
        return TemporalApplyPlan(kind="none")
    return TemporalApplyPlan(
        kind="cessation",
        prior_assertions=tuple(priors),
        reason_codes=("cessation_applied",),
    )


def _find_priors_via_evidence(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    candidate_id: str,
    candidate_segment_id: str,
) -> list[AssertionRecord]:
    evidence_rows = conn.execute(
        """
        SELECT segment_id, evidence_relation AS relation
        FROM memory_candidate_evidence
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    ).fetchall()
    # Prior trail: support segments that also host other candidates' evidence.
    # (candidate.segment_id is not persisted on claim rows.)
    support_segments = sorted(
        {
            str(row["segment_id"])
            for row in evidence_rows
            if str(row["relation"]) == "supports"
        }
    )
    if candidate_segment_id:
        support_segments = [
            seg for seg in support_segments if seg != candidate_segment_id
        ]
    else:
        shared: list[str] = []
        for seg in support_segments:
            other = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM memory_candidate_evidence
                WHERE segment_id = ? AND candidate_id != ?
                """,
                (seg, candidate_id),
            ).fetchone()
            if int(other["c"]) > 0:
                shared.append(seg)
        support_segments = shared
    if not support_segments:
        return []
    placeholders = ",".join("?" for _ in support_segments)
    cand_rows = conn.execute(
        f"""
        SELECT DISTINCT c.candidate_id, c.candidate_kind, c.arguments_json, c.status
        FROM memory_claim_candidates AS c
        JOIN memory_candidate_evidence AS e ON e.candidate_id = c.candidate_id
        WHERE c.user_id = ?
          AND e.segment_id IN ({placeholders})
          AND c.candidate_id != ?
        """,
        (user_id, *support_segments, candidate_id),
    ).fetchall()
    prior_candidate_ids: list[str] = []
    for row in cand_rows:
        if _candidate_row_is_correction(conn, row):
            continue
        prior_candidate_ids.append(str(row["candidate_id"]))
    return _assertions_for_candidates(conn, user_id=user_id, candidate_ids=prior_candidate_ids)


def _find_priors_by_old_value(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    assertion: AssertionRecord,
    entity_by_id: Mapping[str, EntityRecord],
) -> list[AssertionRecord]:
    old_arg = _arg_by_roles(assertion.resolved_arguments, _OLD_ROLES)
    if old_arg is None:
        return []
    old_label = _entity_label(old_arg, entity_by_id, conn, user_id=user_id)
    subject_ids = {
        arg.entity_id
        for arg in assertion.resolved_arguments
        if arg.value_kind == "entity"
        and arg.entity_id
        and arg.role.casefold() in _SUBJECT_ROLES
    }
    # Prefer subject from prior domain facts (self), not from correction old/new.
    rows = conn.execute(
        """
        SELECT *
        FROM memory_assertions
        WHERE user_id = ? AND status = 'active'
        ORDER BY created_at, assertion_id
        """,
        (user_id,),
    ).fetchall()
    matches: list[AssertionRecord] = []
    for row in rows:
        prior = _row_to_assertion(row)
        if looks_like_correction(
            {
                "candidate_kind": prior.candidate_kind,
                "arguments": [a.to_mapping() for a in prior.resolved_arguments],
                "evidence": [],
            }
        ):
            continue
        if not _assertion_value_matches(prior, old_label, old_arg.entity_id, entity_by_id, conn, user_id):
            continue
        if subject_ids:
            prior_subjects = {
                arg.entity_id
                for arg in prior.resolved_arguments
                if arg.value_kind == "entity"
                and arg.entity_id
                and arg.role.casefold() in _SUBJECT_ROLES
            }
            # Domain facts usually have self; correction often lacks subject.
            if prior_subjects and subject_ids.isdisjoint(prior_subjects):
                # Correction without shared subject still OK if only old matched.
                pass
        matches.append(prior)
    return matches


def _find_positive_priors_for_negative(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    assertion: AssertionRecord,
    entity_by_id: Mapping[str, EntityRecord],
) -> list[AssertionRecord]:
    subject_ids = {
        arg.entity_id
        for arg in assertion.resolved_arguments
        if arg.value_kind == "entity"
        and arg.entity_id
        and arg.role.casefold() in _SUBJECT_ROLES
    }
    value_labels = []
    value_entity_ids = set()
    for arg in assertion.resolved_arguments:
        if arg.role.casefold() in _SUBJECT_ROLES:
            continue
        if arg.value_kind == "entity" and arg.entity_id:
            value_entity_ids.add(arg.entity_id)
            value_labels.append(
                _entity_label(arg, entity_by_id, conn, user_id=user_id)
            )
    rows = conn.execute(
        """
        SELECT *
        FROM memory_assertions
        WHERE user_id = ? AND status = 'active' AND polarity = 'positive'
          AND schema_name = ?
        ORDER BY created_at, assertion_id
        """,
        (user_id, assertion.schema_name),
    ).fetchall()
    matches: list[AssertionRecord] = []
    for row in rows:
        prior = _row_to_assertion(row)
        if prior.assertion_id == assertion.assertion_id:
            continue
        prior_subjects = {
            arg.entity_id
            for arg in prior.resolved_arguments
            if arg.value_kind == "entity"
            and arg.entity_id
            and arg.role.casefold() in _SUBJECT_ROLES
        }
        if subject_ids and prior_subjects and subject_ids.isdisjoint(prior_subjects):
            continue
        if value_entity_ids or value_labels:
            if not any(
                (
                    arg.entity_id in value_entity_ids
                    if arg.value_kind == "entity" and arg.entity_id
                    else False
                )
                or labels_compatible(
                    _entity_label(arg, entity_by_id, conn, user_id=user_id),
                    label,
                )
                for arg in prior.resolved_arguments
                if arg.role.casefold() not in _SUBJECT_ROLES
                for label in value_labels
            ) and not any(
                arg.entity_id in value_entity_ids
                for arg in prior.resolved_arguments
                if arg.value_kind == "entity" and arg.entity_id
            ):
                # require some overlap
                overlapped = False
                for arg in prior.resolved_arguments:
                    if arg.role.casefold() in _SUBJECT_ROLES:
                        continue
                    if arg.entity_id and arg.entity_id in value_entity_ids:
                        overlapped = True
                        break
                    lab = _entity_label(arg, entity_by_id, conn, user_id=user_id)
                    if any(labels_compatible(lab, vl) for vl in value_labels if vl):
                        overlapped = True
                        break
                if not overlapped:
                    continue
        matches.append(prior)
    return matches


def _build_winner_assertion(
    *,
    prior: AssertionRecord,
    correction: AssertionRecord,
    new_arg: ResolvedArgument,
    entity_by_id: Mapping[str, EntityRecord],
) -> tuple[AssertionRecord, list[EntityRecord]]:
    value_role = "value"
    for arg in prior.resolved_arguments:
        if arg.role.casefold() not in _SUBJECT_ROLES:
            value_role = arg.role
            break
    resolved: list[ResolvedArgument] = []
    replaced = False
    for arg in prior.resolved_arguments:
        if arg.role.casefold() in _SUBJECT_ROLES:
            resolved.append(arg)
            continue
        if not replaced:
            resolved.append(
                ResolvedArgument(
                    role=value_role if arg.role else value_role,
                    value_kind=new_arg.value_kind,
                    entity_id=new_arg.entity_id,
                    literal=new_arg.literal,
                )
            )
            replaced = True
        # drop other non-subject args from prior (old multi-value)
    if not replaced:
        resolved.append(
            ResolvedArgument(
                role=value_role,
                value_kind=new_arg.value_kind,
                entity_id=new_arg.entity_id,
                literal=new_arg.literal,
            )
        )

    prop = proposition_key(
        candidate_kind=prior.candidate_kind,
        schema_name=prior.schema_name,
        schema_version=prior.schema_version,
        resolved_arguments=resolved,
        attributes=dict(prior.attributes),
    )
    winner_candidate_id = f"{correction.candidate_id}:winner"
    winner = AssertionRecord(
        assertion_id=make_assertion_id(
            candidate_id=winner_candidate_id,
            assertion_schema_version=ASSERTION_SCHEMA_VERSION,
            resolver_version=RESOLVER_VERSION,
        ),
        candidate_id=winner_candidate_id,
        proposition_key=prop,
        cluster_key=prior.cluster_key,
        candidate_kind=prior.candidate_kind,
        schema_name=prior.schema_name,
        schema_version=prior.schema_version,
        resolved_arguments=tuple(resolved),
        attributes=dict(prior.attributes),
        polarity="positive",
        epistemic=dict(correction.epistemic),
        temporal=dict(correction.temporal) if correction.temporal else None,
        observed_at=correction.observed_at,
        status="active",
    )
    entities: list[EntityRecord] = []
    if new_arg.entity_id and new_arg.entity_id in entity_by_id:
        entities.append(entity_by_id[new_arg.entity_id])
    return winner, entities


def labels_compatible(left: str, right: str) -> bool:
    a = lookup_key(left)
    b = lookup_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        return True
    prefix = 0
    for x, y in zip(a, b):
        if x != y:
            break
        prefix += 1
    return prefix >= 5


def assertion_with_status(assertion: AssertionRecord, status: str) -> AssertionRecord:
    return AssertionRecord(
        assertion_id=assertion.assertion_id,
        candidate_id=assertion.candidate_id,
        proposition_key=assertion.proposition_key,
        cluster_key=assertion.cluster_key,
        candidate_kind=assertion.candidate_kind,
        schema_name=assertion.schema_name,
        schema_version=assertion.schema_version,
        resolved_arguments=assertion.resolved_arguments,
        attributes=dict(assertion.attributes),
        polarity=assertion.polarity,
        epistemic=dict(assertion.epistemic),
        temporal=dict(assertion.temporal) if assertion.temporal else None,
        observed_at=assertion.observed_at,
        status=status,
    )


def _arg_by_roles(
    args: Sequence[ResolvedArgument], roles: frozenset[str]
) -> ResolvedArgument | None:
    for arg in args:
        if arg.role.casefold() in roles:
            return arg
    return None


def _entity_label(
    arg: ResolvedArgument,
    entity_by_id: Mapping[str, EntityRecord],
    conn: sqlite3.Connection,
    *,
    user_id: int,
) -> str:
    if arg.value_kind == "literal" and arg.literal is not None:
        return display_label(arg.literal)
    if arg.entity_id and arg.entity_id in entity_by_id:
        return entity_by_id[arg.entity_id].canonical_label
    if arg.entity_id:
        row = conn.execute(
            """
            SELECT canonical_label FROM memory_entities
            WHERE entity_id = ? AND user_id = ?
            """,
            (arg.entity_id, user_id),
        ).fetchone()
        if row is not None:
            return str(row["canonical_label"] or "")
    return ""


def _assertion_value_matches(
    prior: AssertionRecord,
    old_label: str,
    old_entity_id: str | None,
    entity_by_id: Mapping[str, EntityRecord],
    conn: sqlite3.Connection,
    user_id: int,
) -> bool:
    for arg in prior.resolved_arguments:
        if arg.role.casefold() in _SUBJECT_ROLES:
            continue
        if old_entity_id and arg.entity_id == old_entity_id:
            return True
        label = _entity_label(arg, entity_by_id, conn, user_id=user_id)
        if old_label and labels_compatible(label, old_label):
            return True
    return False


def _candidate_row_is_correction(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    args_raw = json.loads(str(row["arguments_json"] or "[]"))
    args = args_raw if isinstance(args_raw, list) else []
    evidence_relations = [
        str(item["relation"])
        for item in conn.execute(
            """
            SELECT evidence_relation AS relation
            FROM memory_candidate_evidence
            WHERE candidate_id = ?
            """,
            (row["candidate_id"],),
        ).fetchall()
    ]
    return looks_like_correction(
        {
            "candidate_kind": str(row["candidate_kind"] or ""),
            "arguments": args,
            "evidence": [{"relation": rel} for rel in evidence_relations],
        }
    )


def _assertions_for_candidates(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    candidate_ids: Sequence[str],
) -> list[AssertionRecord]:
    ids = sorted({str(item) for item in candidate_ids if item})
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT *
        FROM memory_assertions
        WHERE user_id = ? AND candidate_id IN ({placeholders})
          AND status = 'active'
        ORDER BY created_at, assertion_id
        """,
        (user_id, *ids),
    ).fetchall()
    return [_row_to_assertion(row) for row in rows]


def _row_to_assertion(row: sqlite3.Row) -> AssertionRecord:
    args_raw = json.loads(str(row["resolved_arguments_json"] or "[]"))
    resolved: list[ResolvedArgument] = []
    if isinstance(args_raw, list):
        for item in args_raw:
            if not isinstance(item, dict):
                continue
            resolved.append(
                ResolvedArgument(
                    role=str(item.get("role") or ""),
                    value_kind=str(item.get("value_kind") or "literal"),
                    entity_id=(
                        str(item["entity_id"]) if item.get("entity_id") else None
                    ),
                    literal=item.get("literal"),
                )
            )
    attributes = json.loads(str(row["attributes_json"] or "{}"))
    epistemic = json.loads(str(row["epistemic_json"] or "{}"))
    temporal = (
        json.loads(str(row["temporal_json"]))
        if row["temporal_json"]
        else None
    )
    return AssertionRecord(
        assertion_id=str(row["assertion_id"]),
        candidate_id=str(row["candidate_id"]),
        proposition_key=str(row["proposition_key"]),
        cluster_key=str(row["cluster_key"]),
        candidate_kind=str(row["candidate_kind"]),
        schema_name=str(row["schema_name"]),
        schema_version=str(row["schema_version"]),
        resolved_arguments=tuple(resolved),
        attributes=attributes if isinstance(attributes, dict) else {},
        polarity=str(row["polarity"]),
        epistemic=epistemic if isinstance(epistemic, dict) else {},
        temporal=temporal if isinstance(temporal, dict) else None,
        observed_at=str(row["observed_at"]) if row["observed_at"] else None,
        status=str(row["status"]),
    )
