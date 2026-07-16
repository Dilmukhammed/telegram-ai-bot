from __future__ import annotations

import sqlite3
from typing import Sequence

from memory.resolution.entities import ROOT_ENTITY_TYPE, ROOT_IDENTITY_KEY
from memory.resolution.schemas import ResolvedArgument


def canonical_entity_id(
    conn: sqlite3.Connection,
    user_id: int,
    entity_id: str,
) -> str:
    """Resolve entity_id through active merge events (loser -> winner)."""
    if not entity_id:
        return entity_id

    root = conn.execute(
        """
        SELECT entity_id
        FROM memory_entities
        WHERE user_id = ? AND entity_type = ? AND identity_key = ?
        LIMIT 1
        """,
        (user_id, ROOT_ENTITY_TYPE, ROOT_IDENTITY_KEY),
    ).fetchone()
    if root is not None and str(root["entity_id"]) == entity_id:
        return entity_id

    entity_types = {
        str(row["entity_id"]): str(row["entity_type"])
        for row in conn.execute(
            """
            SELECT entity_id, entity_type
            FROM memory_entities
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
    }
    if entity_id not in entity_types:
        return entity_id

    parent: dict[str, str] = {}
    try:
        rows = conn.execute(
            """
            SELECT loser_entity_id, winner_entity_id
            FROM memory_entity_resolution_events
            WHERE user_id = ?
              AND status = 'active'
              AND op = 'merge'
            """,
            (user_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return entity_id

    for row in rows:
        loser = str(row["loser_entity_id"])
        winner = str(row["winner_entity_id"])
        if loser == winner:
            continue
        loser_type = entity_types.get(loser)
        winner_type = entity_types.get(winner)
        if loser_type is None or winner_type is None:
            continue
        if loser_type != winner_type:
            continue
        parent[loser] = winner

    current = entity_id
    seen: set[str] = set()
    while current in parent:
        if current in seen:
            break
        seen.add(current)
        nxt = parent[current]
        nxt_type = entity_types.get(nxt)
        current_type = entity_types.get(current)
        if nxt_type is None or current_type is None or nxt_type != current_type:
            break
        current = nxt
    return current


def canonical_arguments(
    conn: sqlite3.Connection,
    user_id: int,
    args: Sequence[ResolvedArgument],
) -> tuple[ResolvedArgument, ...]:
    resolved: list[ResolvedArgument] = []
    for arg in args:
        if arg.value_kind != "entity" or not arg.entity_id:
            resolved.append(arg)
            continue
        canonical_id = canonical_entity_id(conn, user_id, arg.entity_id)
        if canonical_id == arg.entity_id:
            resolved.append(arg)
            continue
        resolved.append(
            ResolvedArgument(
                role=arg.role,
                value_kind="entity",
                entity_id=canonical_id,
            )
        )
    return tuple(resolved)
