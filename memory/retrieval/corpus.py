from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from memory.resolution.normalization import display_label, lookup_key


@dataclass(frozen=True, slots=True)
class BeliefHeadDoc:
    belief_id: str
    schema_name: str
    proposition_key: str
    belief_status: str
    utility_class: str
    polarity: str
    resolved_arguments: tuple[dict[str, Any], ...]
    temporal: Mapping[str, Any] | None
    statement: str
    search_text: str
    entity_ids: tuple[str, ...]
    candidate_kinds: tuple[str, ...]
    evidence_quotes: tuple[str, ...]
    support_pointers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntityDoc:
    entity_id: str
    entity_type: str
    canonical_label: str
    status: str
    aliases: tuple[str, ...]
    normalized_aliases: tuple[str, ...]


def load_belief_heads(
    conn: sqlite3.Connection,
    *,
    user_id: int,
) -> list[BeliefHeadDoc]:
    rows = conn.execute(
        """
        SELECT b.belief_id, b.schema_name, b.proposition_key,
               r.belief_revision_id, r.belief_status, r.utility_class, r.polarity,
               r.resolved_arguments_json, r.temporal_json
        FROM memory_belief_heads h
        JOIN memory_beliefs b ON b.belief_id = h.belief_id
        JOIN memory_belief_revisions r
          ON r.belief_revision_id = h.belief_revision_id
        WHERE h.user_id = ?
        ORDER BY b.created_at, b.belief_id
        """,
        (user_id,),
    ).fetchall()
    docs: list[BeliefHeadDoc] = []
    for row in rows:
        args = _loads_list(row["resolved_arguments_json"])
        temporal = _loads_obj(row["temporal_json"])
        entity_ids = tuple(
            str(arg["entity_id"])
            for arg in args
            if isinstance(arg, dict) and arg.get("entity_id")
        )
        labels = _argument_labels(conn, user_id=user_id, args=args)
        statement = _statement(
            schema_name=str(row["schema_name"]),
            polarity=str(row["polarity"]),
            labels=labels,
        )
        quotes, pointers, kinds = _evidence_for_revision(
            conn,
            belief_revision_id=str(row["belief_revision_id"]),
        )
        search_parts = [
            str(row["schema_name"]),
            statement,
            *labels,
            *quotes,
        ]
        docs.append(
            BeliefHeadDoc(
                belief_id=str(row["belief_id"]),
                schema_name=str(row["schema_name"]),
                proposition_key=str(row["proposition_key"]),
                belief_status=str(row["belief_status"]),
                utility_class=str(row["utility_class"]),
                polarity=str(row["polarity"]),
                resolved_arguments=tuple(args),
                temporal=temporal,
                statement=statement,
                search_text=" ".join(part for part in search_parts if part),
                entity_ids=entity_ids,
                candidate_kinds=kinds,
                evidence_quotes=quotes,
                support_pointers=pointers,
            )
        )
    return docs


def load_entities(
    conn: sqlite3.Connection,
    *,
    user_id: int,
) -> list[EntityDoc]:
    entity_rows = conn.execute(
        """
        SELECT entity_id, entity_type, canonical_label, status
        FROM memory_entities
        WHERE user_id = ? AND status IN ('active', 'provisional')
        ORDER BY canonical_label, entity_id
        """,
        (user_id,),
    ).fetchall()
    alias_rows = conn.execute(
        """
        SELECT entity_id, alias, normalized_alias
        FROM memory_entity_aliases
        WHERE user_id = ? AND status = 'active'
        """,
        (user_id,),
    ).fetchall()
    aliases_by_entity: dict[str, list[tuple[str, str]]] = {}
    for row in alias_rows:
        aliases_by_entity.setdefault(str(row["entity_id"]), []).append(
            (str(row["alias"]), str(row["normalized_alias"]))
        )
    docs: list[EntityDoc] = []
    for row in entity_rows:
        entity_id = str(row["entity_id"])
        pairs = aliases_by_entity.get(entity_id, [])
        docs.append(
            EntityDoc(
                entity_id=entity_id,
                entity_type=str(row["entity_type"]),
                canonical_label=str(row["canonical_label"]),
                status=str(row["status"]),
                aliases=tuple(alias for alias, _ in pairs),
                normalized_aliases=tuple(norm for _, norm in pairs),
            )
        )
    return docs


def _argument_labels(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    args: Sequence[Mapping[str, Any]],
) -> list[str]:
    labels: list[str] = []
    for arg in args:
        if not isinstance(arg, dict):
            continue
        entity_id = arg.get("entity_id")
        if entity_id:
            row = conn.execute(
                """
                SELECT canonical_label FROM memory_entities
                WHERE user_id = ? AND entity_id = ?
                """,
                (user_id, str(entity_id)),
            ).fetchone()
            if row:
                labels.append(str(row["canonical_label"]))
            continue
        if "literal" in arg:
            labels.append(display_label(arg.get("literal")))
    return [label for label in labels if label]


def _statement(*, schema_name: str, polarity: str, labels: Sequence[str]) -> str:
    joined = " / ".join(labels) if labels else ""
    if polarity == "negative":
        return f"not {schema_name}: {joined}".strip(": ")
    return f"{schema_name}: {joined}".strip(": ")


def _evidence_for_revision(
    conn: sqlite3.Connection,
    *,
    belief_revision_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    rows = conn.execute(
        """
        SELECT e.exact_quote, e.pointer_json, c.candidate_kind, e.segment_id
        FROM memory_belief_support s
        JOIN memory_assertions a ON a.assertion_id = s.assertion_id
        JOIN memory_claim_candidates c ON c.candidate_id = a.candidate_id
        LEFT JOIN memory_candidate_evidence e ON e.candidate_id = a.candidate_id
        WHERE s.belief_revision_id = ?
        """,
        (belief_revision_id,),
    ).fetchall()
    quotes: list[str] = []
    pointers: list[str] = []
    kinds: list[str] = []
    for row in rows:
        kind = str(row["candidate_kind"] or "")
        if kind and kind not in kinds:
            kinds.append(kind)
        quote = row["exact_quote"]
        if quote:
            quotes.append(str(quote))
        pointer = row["pointer_json"]
        if pointer:
            pointers.append(str(pointer))
        elif row["segment_id"]:
            pointers.append(f"segment:{row['segment_id']}")
    return tuple(quotes), tuple(pointers), tuple(kinds)


def _loads_list(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _loads_obj(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def match_entity_surface(entity: EntityDoc, surface: str) -> bool:
    key = lookup_key(surface)
    if not key:
        return False
    if lookup_key(entity.canonical_label) == key:
        return True
    return key in entity.normalized_aliases or any(
        lookup_key(alias) == key for alias in entity.aliases
    )
