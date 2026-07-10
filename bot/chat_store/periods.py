"""CRUD for chat_period_summaries."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from bot.chat_store.models import ChatPeriodSummary, PeriodType, SummaryStatus
from bot.chat_store.schema import parse_dt, utc_now_iso


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_session_ids(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(str(item) for item in payload if item)


def row_to_period(row: sqlite3.Row) -> ChatPeriodSummary:
    return ChatPeriodSummary(
        period_id=str(row["period_id"]),
        user_id=int(row["user_id"]),
        period_type=row["period_type"],  # type: ignore[arg-type]
        period_key=str(row["period_key"]),
        title=row["title"],
        summary=row["summary"],
        summary_status=row["summary_status"],
        session_count=int(row["session_count"] or 0),
        source_session_ids=_parse_session_ids(row["source_session_ids_json"]),
        coverage_start=parse_dt(row["coverage_start"]),
        coverage_end=parse_dt(row["coverage_end"]),
        summary_started_at=parse_dt(row["summary_started_at"]),
        summary_completed_at=parse_dt(row["summary_completed_at"]),
        created_at=parse_dt(row["created_at"]) or datetime.fromisoformat(row["created_at"]),
        updated_at=parse_dt(row["updated_at"]) or datetime.fromisoformat(row["updated_at"]),
        metadata=_parse_metadata(row["metadata_json"]),
    )


def get_period(
    conn: sqlite3.Connection,
    user_id: int,
    period_type: PeriodType | str,
    period_key: str,
) -> ChatPeriodSummary | None:
    row = conn.execute(
        """
        SELECT * FROM chat_period_summaries
        WHERE user_id = ? AND period_type = ? AND period_key = ?
        """,
        (user_id, period_type, period_key),
    ).fetchone()
    return row_to_period(row) if row else None


def get_period_by_id(
    conn: sqlite3.Connection,
    period_id: str,
    user_id: int,
) -> ChatPeriodSummary | None:
    row = conn.execute(
        """
        SELECT * FROM chat_period_summaries
        WHERE period_id = ? AND user_id = ?
        """,
        (period_id, user_id),
    ).fetchone()
    return row_to_period(row) if row else None


def list_periods(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    period_type: PeriodType | str | None = None,
    limit: int = 20,
) -> list[ChatPeriodSummary]:
    limit = max(1, min(int(limit), 100))
    if period_type:
        rows = conn.execute(
            """
            SELECT * FROM chat_period_summaries
            WHERE user_id = ? AND period_type = ?
            ORDER BY period_key DESC
            LIMIT ?
            """,
            (user_id, period_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM chat_period_summaries
            WHERE user_id = ?
            ORDER BY period_key DESC, period_type ASC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [row_to_period(row) for row in rows]


def upsert_period_pending(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    period_type: PeriodType | str,
    period_key: str,
    session_ids: list[str] | tuple[str, ...],
    coverage_start: datetime | None,
    coverage_end: datetime | None,
) -> ChatPeriodSummary:
    now = utc_now_iso()
    existing = get_period(conn, user_id, period_type, period_key)
    ids_json = json.dumps(list(session_ids), ensure_ascii=False)
    cov_start = coverage_start.isoformat() if coverage_start else None
    cov_end = coverage_end.isoformat() if coverage_end else None
    if existing is None:
        period_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO chat_period_summaries (
                period_id, user_id, period_type, period_key,
                title, summary, summary_status, session_count,
                source_session_ids_json, coverage_start, coverage_end,
                summary_started_at, summary_completed_at,
                created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, NULL, NULL, 'pending', ?, ?, ?, ?, NULL, NULL, ?, ?, NULL)
            """,
            (
                period_id,
                user_id,
                period_type,
                period_key,
                len(session_ids),
                ids_json,
                cov_start,
                cov_end,
                now,
                now,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE chat_period_summaries
            SET session_count = ?,
                source_session_ids_json = ?,
                coverage_start = ?,
                coverage_end = ?,
                summary_status = 'pending',
                summary_started_at = NULL,
                summary_completed_at = NULL,
                title = NULL,
                summary = NULL,
                updated_at = ?
            WHERE user_id = ? AND period_type = ? AND period_key = ?
            """,
            (
                len(session_ids),
                ids_json,
                cov_start,
                cov_end,
                now,
                user_id,
                period_type,
                period_key,
            ),
        )
    period = get_period(conn, user_id, period_type, period_key)
    if period is None:
        raise RuntimeError("upsert_period_pending failed to read back row")
    return period


def update_period_summary_status(
    conn: sqlite3.Connection,
    period_id: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    summary_status: SummaryStatus,
    summary_started_at: datetime | None = None,
    summary_completed_at: datetime | None = None,
    session_count: int | None = None,
    source_session_ids: list[str] | tuple[str, ...] | None = None,
    coverage_start: datetime | None = None,
    coverage_end: datetime | None = None,
) -> ChatPeriodSummary | None:
    now = utc_now_iso()
    ids_json = (
        json.dumps(list(source_session_ids), ensure_ascii=False)
        if source_session_ids is not None
        else None
    )
    conn.execute(
        """
        UPDATE chat_period_summaries
        SET title = COALESCE(?, title),
            summary = COALESCE(?, summary),
            summary_status = ?,
            summary_started_at = COALESCE(?, summary_started_at),
            summary_completed_at = COALESCE(?, summary_completed_at),
            session_count = COALESCE(?, session_count),
            source_session_ids_json = COALESCE(?, source_session_ids_json),
            coverage_start = COALESCE(?, coverage_start),
            coverage_end = COALESCE(?, coverage_end),
            updated_at = ?
        WHERE period_id = ?
        """,
        (
            title,
            summary,
            summary_status,
            summary_started_at.isoformat() if summary_started_at else None,
            summary_completed_at.isoformat() if summary_completed_at else None,
            session_count,
            ids_json,
            coverage_start.isoformat() if coverage_start else None,
            coverage_end.isoformat() if coverage_end else None,
            now,
            period_id,
        ),
    )
    row = conn.execute(
        "SELECT * FROM chat_period_summaries WHERE period_id = ?",
        (period_id,),
    ).fetchone()
    return row_to_period(row) if row else None
