from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

_MAX_LOCK_RETRIES = 5
_LOCK_RETRY_SLEEP_SECONDS = 0.05


class MemoryDatabase:
    def __init__(self, db_path: str) -> None:
        if db_path == ":memory:":
            self._db_path: Path | None = None
            self._memory_conn: sqlite3.Connection | None = None
        else:
            self._db_path = Path(db_path)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._memory_conn = None
        self._schema_ready = False
        self._write_lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._db_path is None:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
                configure_connection(self._memory_conn)
                self._init_schema(connection=self._memory_conn)
            return self._memory_conn

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        configure_connection(conn)
        return conn

    def _init_schema(self, connection: sqlite3.Connection | None = None) -> None:
        if connection is None and self._schema_ready and self._db_path is None:
            return
        from memory.schema import ensure_schema

        conn = connection or self._connect()
        owns_connection = connection is None and self._db_path is not None
        try:
            ensure_schema(conn)
            if self._db_path is None:
                conn.commit()
                self._schema_ready = True
            elif owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            if self._db_path is not None:
                conn.close()

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn: sqlite3.Connection | None = None
            for attempt in range(_MAX_LOCK_RETRIES):
                candidate = self._connect()
                try:
                    if immediate:
                        candidate.execute("BEGIN IMMEDIATE")
                    else:
                        candidate.execute("BEGIN")
                    conn = candidate
                    break
                except sqlite3.OperationalError as exc:
                    candidate.rollback()
                    if self._db_path is not None:
                        candidate.close()
                    if "locked" not in str(exc).lower() or attempt == _MAX_LOCK_RETRIES - 1:
                        raise
                    time.sleep(_LOCK_RETRY_SLEEP_SECONDS * (attempt + 1))
            if conn is None:
                raise RuntimeError("failed to begin memory database transaction")

            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._db_path is not None:
                    conn.close()


def configure_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def dumps_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def loads_json_object(raw: str | None) -> dict:
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object")
    return dict(payload)
