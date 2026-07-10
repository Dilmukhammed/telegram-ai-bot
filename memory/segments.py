from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from memory.db import MemoryDatabase, dumps_json, loads_json_object, parse_utc, utc_now_iso
from memory.ids import make_segment_id, pointer_hash
from memory.models import LineageInput, LineageRelation, MemorySegment, SegmentInput, SegmentStatus
from memory.pointers import pointer_from_mapping, pointer_to_mapping


class MemorySegmentStore:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    def insert_segments(
        self,
        segments: Sequence[SegmentInput],
        *,
        user_id: int,
        lineage_store: "MemoryLineageStore",
    ) -> int:
        from memory.lineage import MemoryLineageStore

        with self._db.transaction() as conn:
            return self.insert_segments_in_txn(
                conn,
                segments,
                user_id=user_id,
                lineage_store=lineage_store,
            )

    def list_for_source_version(
        self,
        source_version_id: str,
        *,
        user_id: int,
        active_only: bool = True,
    ) -> list[MemorySegment]:
        status_clause = "AND seg.status = 'active'" if active_only else ""
        with self._db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT seg.*
                FROM memory_segments seg
                JOIN memory_source_versions v ON v.source_version_id = seg.source_version_id
                JOIN memory_sources s ON s.source_id = v.source_id
                WHERE seg.source_version_id = ? AND s.user_id = ? {status_clause}
                ORDER BY seg.ordinal, seg.segment_id
                """,
                (source_version_id, user_id),
            ).fetchall()
        result: list[MemorySegment] = []
        for row in rows:
            created_at = parse_utc(row["created_at"])
            if created_at is None:
                raise ValueError(f"segment {row['segment_id']} has invalid created_at")
            result.append(
                MemorySegment(
                    segment_id=str(row["segment_id"]),
                    source_version_id=str(row["source_version_id"]),
                    parent_segment_id=row["parent_segment_id"],
                    segment_type=str(row["segment_type"]),
                    ordinal=int(row["ordinal"]),
                    text=row["text"],
                    pointer=pointer_from_mapping(loads_json_object(row["pointer_json"])),
                    normalizer_name=str(row["normalizer_name"]),
                    normalizer_version=str(row["normalizer_version"]),
                    input_hash=str(row["input_hash"]),
                    created_at=created_at,
                    status=SegmentStatus(str(row["status"])),
                )
            )
        return result

    def insert_segments_in_txn(
        self,
        conn: sqlite3.Connection,
        segments: Sequence[SegmentInput],
        *,
        user_id: int,
        lineage_store: "MemoryLineageStore",
    ) -> int:
        created = 0
        now = utc_now_iso()
        checked_versions: set[str] = set()
        for segment in segments:
            if segment.ordinal < 0:
                raise ValueError("segment ordinal must be non-negative")
            if segment.source_version_id not in checked_versions:
                _assert_active_owned_version(
                    conn,
                    source_version_id=segment.source_version_id,
                    user_id=user_id,
                )
                checked_versions.add(segment.source_version_id)
            if segment.pointer.source_version_id != segment.source_version_id:
                raise ValueError("segment pointer source_version_id mismatch")
            if segment.parent_segment_id is not None:
                _assert_owned_parent_segment(
                    conn,
                    parent_segment_id=segment.parent_segment_id,
                    source_version_id=segment.source_version_id,
                    user_id=user_id,
                )
            payload = pointer_to_mapping(segment.pointer)
            segment_id = make_segment_id(
                source_version_id=segment.source_version_id,
                segment_type=segment.segment_type,
                ordinal=segment.ordinal,
                pointer_payload_hash=pointer_hash(payload),
                normalizer_version=segment.normalizer_version,
            )
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO memory_segments(
                    segment_id, source_version_id, parent_segment_id,
                    segment_type, ordinal, text, pointer_json,
                    normalizer_name, normalizer_version, input_hash,
                    created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment_id,
                    segment.source_version_id,
                    segment.parent_segment_id,
                    segment.segment_type,
                    segment.ordinal,
                    segment.text,
                    dumps_json(payload),
                    segment.normalizer_name,
                    segment.normalizer_version,
                    segment.input_hash,
                    now,
                    SegmentStatus.ACTIVE.value,
                ),
            )
            if cursor.rowcount:
                created += 1
                lineage_store.add_links(
                    conn,
                    user_id=user_id,
                    links=[
                        LineageInput(
                            parent_kind="source_version",
                            parent_id=segment.source_version_id,
                            child_kind="segment",
                            child_id=segment_id,
                            relation=LineageRelation.DERIVED_FROM,
                        )
                    ],
                )
        return created


def _assert_active_owned_version(
    conn: sqlite3.Connection,
    *,
    source_version_id: str,
    user_id: int,
) -> None:
    row = conn.execute(
        """
        SELECT s.user_id, s.status AS source_status, v.status AS version_status
        FROM memory_source_versions v
        JOIN memory_sources s ON s.source_id = v.source_id
        WHERE v.source_version_id = ?
        """,
        (source_version_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown source_version_id: {source_version_id}")
    if int(row["user_id"]) != user_id:
        raise PermissionError("source version belongs to another user")
    if row["source_status"] != "active" or row["version_status"] != "active":
        raise RuntimeError("cannot add segments to inactive source version")


def _assert_owned_parent_segment(
    conn: sqlite3.Connection,
    *,
    parent_segment_id: str,
    source_version_id: str,
    user_id: int,
) -> None:
    row = conn.execute(
        """
        SELECT seg.source_version_id, s.user_id
        FROM memory_segments seg
        JOIN memory_source_versions v ON v.source_version_id = seg.source_version_id
        JOIN memory_sources s ON s.source_id = v.source_id
        WHERE seg.segment_id = ?
        """,
        (parent_segment_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown parent_segment_id: {parent_segment_id}")
    if int(row["user_id"]) != user_id:
        raise PermissionError("parent segment belongs to another user")
    if row["source_version_id"] != source_version_id:
        raise ValueError("parent segment must belong to the same source version")
