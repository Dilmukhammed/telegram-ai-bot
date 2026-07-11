from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from memory.db import MemoryDatabase, dumps_json, loads_json_object, utc_now_iso
from memory.ids import make_mention_id
from memory.models import LineageInput, LineageRelation
from memory.pointers import EvidencePointer, pointer_from_mapping, pointer_to_mapping

if TYPE_CHECKING:
    from memory.lineage import MemoryLineageStore


@dataclass(frozen=True, slots=True)
class MentionInput:
    local_ref: str
    segment_id: str
    mention_type: str
    surface_text: str
    normalized_hint: str | None
    pointer: EvidencePointer
    extractor_name: str
    extractor_version: str
    prompt_version: str


class MemoryMentionStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def insert_in_txn(
        self,
        conn: sqlite3.Connection,
        mentions: Sequence[MentionInput],
        *,
        user_id: int,
        lineage_store: "MemoryLineageStore",
    ) -> dict[tuple[str, str], str]:
        resolved: dict[tuple[str, str], str] = {}
        now = utc_now_iso()
        for mention in mentions:
            source_version_id = _assert_active_owned_segment(
                conn,
                segment_id=mention.segment_id,
                user_id=user_id,
            )
            if mention.pointer.source_version_id != source_version_id:
                raise ValueError("mention pointer source_version_id mismatch")
            assert_exact_segment_span(
                conn,
                segment_id=mention.segment_id,
                user_id=user_id,
                pointer=mention.pointer,
                expected_text=mention.surface_text,
            )
            pointer_payload = pointer_to_mapping(mention.pointer)
            mention_id = make_mention_id(
                user_id=user_id,
                pointer_payload=pointer_payload,
                mention_type=mention.mention_type,
                surface_text=mention.surface_text,
                extractor_name=mention.extractor_name,
                extractor_version=mention.extractor_version,
                prompt_version=mention.prompt_version,
            )
            key = (mention.segment_id, mention.local_ref)
            previous = resolved.get(key)
            if previous is not None and previous != mention_id:
                raise ValueError(f"duplicate local mention reference: {key!r}")
            resolved[key] = mention_id
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO memory_mentions(
                    mention_id, user_id, segment_id, mention_type, surface_text,
                    normalized_hint, pointer_json, extractor_name, extractor_version,
                    prompt_version, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    mention_id,
                    user_id,
                    mention.segment_id,
                    mention.mention_type,
                    mention.surface_text,
                    mention.normalized_hint,
                    dumps_json(pointer_payload),
                    mention.extractor_name,
                    mention.extractor_version,
                    mention.prompt_version,
                    now,
                ),
            )
            if cursor.rowcount:
                lineage_store.add_links(
                    conn,
                    user_id=user_id,
                    links=(
                        LineageInput(
                            parent_kind="segment",
                            parent_id=mention.segment_id,
                            child_kind="mention",
                            child_id=mention_id,
                            relation=LineageRelation.DERIVED_FROM,
                        ),
                    ),
                )
        return resolved

    def list_for_segment(
        self,
        segment_id: str,
        *,
        user_id: int,
        active_only: bool = True,
    ) -> list[dict[str, object]]:
        status_clause = "AND status = 'active'" if active_only else ""
        with self._db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM memory_mentions
                WHERE segment_id = ? AND user_id = ? {status_clause}
                ORDER BY mention_id
                """,
                (segment_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_for_source_version(
        self,
        source_version_id: str,
        *,
        user_id: int,
        active_only: bool = True,
    ) -> list[dict[str, object]]:
        status_clause = "AND m.status = 'active'" if active_only else ""
        with self._db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT m.*
                FROM memory_mentions m
                JOIN memory_segments seg ON seg.segment_id = m.segment_id
                JOIN memory_source_versions v ON v.source_version_id = seg.source_version_id
                JOIN memory_sources s ON s.source_id = v.source_id
                WHERE seg.source_version_id = ? AND s.user_id = ? {status_clause}
                ORDER BY m.segment_id, m.mention_id
                """,
                (source_version_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]


def _assert_active_owned_segment(
    conn: sqlite3.Connection,
    *,
    segment_id: str,
    user_id: int,
) -> str:
    row = conn.execute(
        """
        SELECT seg.source_version_id, seg.status AS segment_status,
               v.status AS version_status, s.status AS source_status, s.user_id
        FROM memory_segments seg
        JOIN memory_source_versions v ON v.source_version_id = seg.source_version_id
        JOIN memory_sources s ON s.source_id = v.source_id
        WHERE seg.segment_id = ?
        """,
        (segment_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown segment_id: {segment_id}")
    if int(row["user_id"]) != user_id:
        raise PermissionError("segment belongs to another user")
    if (
        row["segment_status"] != "active"
        or row["version_status"] != "active"
        or row["source_status"] != "active"
    ):
        raise RuntimeError("cannot extract from an inactive segment")
    return str(row["source_version_id"])


def assert_exact_segment_span(
    conn: sqlite3.Connection,
    *,
    segment_id: str,
    user_id: int,
    pointer: EvidencePointer,
    expected_text: str,
) -> None:
    row = conn.execute(
        """
        SELECT seg.text, seg.pointer_json, seg.source_version_id, seg.status,
               s.user_id
        FROM memory_segments seg
        JOIN memory_source_versions v ON v.source_version_id = seg.source_version_id
        JOIN memory_sources s ON s.source_id = v.source_id
        WHERE seg.segment_id = ?
        """,
        (segment_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown evidence segment: {segment_id}")
    if int(row["user_id"]) != user_id:
        raise PermissionError("evidence segment belongs to another user")
    if row["status"] != "active":
        raise RuntimeError("cannot use inactive evidence")
    if str(row["source_version_id"]) != pointer.source_version_id:
        raise ValueError("evidence pointer source version mismatch")
    segment_text = row["text"]
    if not isinstance(segment_text, str):
        raise ValueError("exact text evidence requires a text segment")
    base_pointer = pointer_from_mapping(loads_json_object(row["pointer_json"]))
    base_location = dict(base_pointer.location)
    location = dict(pointer.location)
    if pointer.kind == "chat_span" and base_pointer.kind in {"chat_message", "chat_span"}:
        if int(location["chat_message_id"]) != int(base_location["chat_message_id"]):
            raise ValueError("chat evidence pointer targets a different message")
    elif pointer.kind == "tool_result" and base_pointer.kind == "tool_result":
        if str(location["tool_result_ref"]) != str(base_location["tool_result_ref"]):
            raise ValueError("tool evidence pointer targets a different result")
    else:
        raise ValueError("evidence pointer kind is incompatible with its segment")
    base_start = int(base_location.get("char_start", 0))
    local_start = int(location["char_start"]) - base_start
    local_end = int(location["char_end"]) - base_start
    if local_start < 0 or local_end < local_start or local_end > len(segment_text):
        raise ValueError("evidence pointer falls outside its segment")
    if segment_text[local_start:local_end] != expected_text:
        raise ValueError("evidence pointer does not exactly match stored segment text")
