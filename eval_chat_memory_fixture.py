"""In-memory fixture for chat memory eval (user 123456)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

from agent.run_trace import RunTrace
from bot.chat_index.sync import index_session_messages, index_session_summary, rebuild_user_index
from bot.chat_service import ChatService
from bot.chat_store import ChatStore, reset_chat_store
from bot.chat_store.summary import summarize_archived_session
from eval_memory_corpus.schema import CorpusPack, CorpusSession
from tools.tool_results.archive import archived_content_json
from tools.tool_results.store import ToolResultStore, reset_tool_result_store

FAKE_USER = 123456


class MemoryEvalFixture:
    def __init__(self, chat_store: ChatStore, tool_store: ToolResultStore) -> None:
        self.chat_store = chat_store
        self.tool_store = tool_store
        self.chat_service = ChatService(MagicMock(), chat_store=chat_store)

    @staticmethod
    def use_tool_exchange(
        *,
        tool_name: str,
        tool_args: dict,
        tool_content: str,
        call_id: str,
    ) -> list[dict]:
        return [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "use_tool",
                            "arguments": json.dumps(
                                {"tool_name": tool_name, "arguments": tool_args},
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_content,
            },
        ]

    def seed_turn_in_session(
        self,
        session_id: str,
        user_text: str,
        worker_history: list[dict],
    ) -> None:
        at = datetime.now(timezone.utc)
        session = self.chat_store.get_session_for_user(session_id, FAKE_USER)
        if session is None:
            raise ValueError(f"Unknown session for user: {session_id}")
        self.chat_store.append_messages(
            session_id,
            FAKE_USER,
            [{"role": "user", "content": user_text}, *worker_history],
            source_at_for_message=[at, *[at] * len(worker_history)],
        )
        index_session_messages(self.chat_store, session_id)

    def seed_session_turns(
        self,
        turns: list[tuple[str, list[dict]]],
        *,
        session_id: str | None = None,
        trace_every: int = 0,
    ) -> str:
        if session_id is None:
            session_id = self.chat_store.get_or_create_active_session(FAKE_USER).session_id
        elif self.chat_store.get_session_for_user(session_id, FAKE_USER) is None:
            raise ValueError(f"Unknown session for user: {session_id}")

        for index, (user_text, worker_history) in enumerate(turns, start=1):
            at = datetime.now(timezone.utc)
            self.chat_store.append_messages(
                session_id,
                FAKE_USER,
                [{"role": "user", "content": user_text}, *worker_history],
                source_at_for_message=[at, *[at] * len(worker_history)],
            )
            if trace_every and index % trace_every == 0:
                self.chat_store.append_session_trace(
                    session_id,
                    FAKE_USER,
                    trace=RunTrace(
                        user_id=FAKE_USER,
                        user_message=user_text,
                        started_at=time.time(),
                        final_outcome="success",
                    ),
                    assistant_reply=worker_history[-1].get("content", "") if worker_history else user_text,
                    source_at=at,
                )

        index_session_messages(self.chat_store, session_id)
        return session_id

    def seed_archived_turn(
        self,
        user_text: str,
        worker_history: list[dict],
        *,
        trace_user_message: str | None = None,
        successful_tools: tuple[str, ...] = (),
        progress_summary: str = "",
    ) -> str:
        at = datetime.now(timezone.utc)
        self.chat_service.append_turn_messages(
            FAKE_USER,
            [{"role": "user", "content": user_text}, *worker_history],
            user_message_at=at,
        )
        session = self.chat_store.get_active_session(FAKE_USER)
        if session is None:
            raise RuntimeError("No active session after seed")
        self.chat_store.append_session_trace(
            session.session_id,
            FAKE_USER,
            trace=RunTrace(
                user_id=FAKE_USER,
                user_message=trace_user_message or user_text,
                started_at=time.time(),
                final_outcome="success",
                successful_tools=list(successful_tools),
                progress_summary=progress_summary,
            ),
            assistant_reply=worker_history[-1].get("content", "") if worker_history else user_text,
            source_at=at,
        )
        index_session_messages(self.chat_store, session.session_id)
        return session.session_id

    def archive_session(self, session_id: str) -> None:
        self.chat_store.archive_session(session_id, closed_by="new_chat")

    def open_fresh_active_session(self) -> str:
        archived, created = self.chat_store.archive_and_create_active(
            FAKE_USER,
            closed_by="new_chat",
        )
        if archived is None:
            raise RuntimeError("Expected archived session when opening fresh active session")
        return created.session_id

    async def summarize_archived(self, session_id: str) -> None:
        await summarize_archived_session(self.chat_store, session_id)
        index_session_summary(self.chat_store, session_id)

    def insert_tool_result(
        self,
        *,
        turn: int,
        summary: str,
        payload: dict,
    ):
        ref = self.tool_store.insert(
            user_id=FAKE_USER,
            run_id="memeval_run",
            tool_name=str(payload.get("tool_name") or "exa.web_search"),
            turn=turn,
            args_json="{}",
            payload_json=json.dumps(payload, ensure_ascii=False),
            ok=True,
            cached=False,
        )
        self.tool_store.update_summary(
            ref,
            summary=summary,
            summarize_status="ok",
            summarize_attempts=1,
        )
        record = self.tool_store.get(ref, user_id=FAKE_USER)
        if record is None:
            raise RuntimeError("tool result insert failed")
        return record

    def archived_tool_json(self, record) -> str:
        return archived_content_json(record)

    def reindex(self) -> None:
        rebuild_user_index(self.chat_store, FAKE_USER, clear_existing=True)

    def collect_evidence(
        self,
        session_id: str,
        *,
        tool_payload_json: str | None = None,
        include_summary: bool = False,
    ) -> list[str]:
        chunks: list[str] = []
        messages = self.chat_store.read_message_dicts(session_id)
        for message in messages:
            role = message.get("role", "?")
            content = str(message.get("content") or "").strip()
            if content:
                chunks.append(f"[{role}] {content}")
        if tool_payload_json:
            chunks.append(f"[tool_result_payload] {tool_payload_json}")
        if include_summary:
            session = self.chat_store.get_session_for_user(session_id, FAKE_USER)
            if session and session.summary:
                chunks.append(f"[session_summary] {session.summary}")
        return chunks

    def inject_summary(self, session_id: str, *, title: str, summary: str) -> None:
        completed = datetime.now(timezone.utc)
        with self.chat_store._connect() as conn:
            from bot.chat_store import sessions as session_ops

            session_ops.update_session_summary_status(
                conn,
                session_id,
                title=title,
                summary=summary,
                summary_status="done",
                summary_completed_at=completed,
            )
            conn.commit()
        index_session_summary(self.chat_store, session_id)

    def _set_session_started_at(self, session_id: str, started_at: datetime) -> None:
        with self.chat_store._connect() as conn:
            conn.execute(
                """
                UPDATE chat_sessions
                SET started_at = ?, last_message_at = COALESCE(last_message_at, ?)
                WHERE session_id = ?
                """,
                (started_at.isoformat(), started_at.isoformat(), session_id),
            )
            conn.commit()

    def seed_corpus_session(
        self,
        session: CorpusSession,
        *,
        base_time: datetime | None = None,
    ) -> str:
        """Seed one corpus session as archived; returns DB session_id."""
        base = base_time or datetime.now(timezone.utc)
        started = base - timedelta(hours=max(0, session.started_offset_hours))
        session_id = self.chat_store.get_or_create_active_session(
            FAKE_USER,
            opened_by="corpus_seed",
            metadata={"slug": session.slug, "title": session.title},
        ).session_id
        self._set_session_started_at(session_id, started)

        tool_ref_by_fact: dict[str, int] = {}
        for turn_index, turn in enumerate(session.turns, start=1):
            at = started + timedelta(minutes=turn_index)
            worker: list[dict[str, Any]] = []
            if turn.tool_result is not None:
                record = self.insert_tool_result(
                    turn=turn_index,
                    summary=str(turn.tool_result.get("summary") or "archived tool result"),
                    payload=turn.tool_result,
                )
                for fact_id in turn.fact_ids:
                    tool_ref_by_fact[fact_id] = record.display_ref
                worker.extend(
                    self.use_tool_exchange(
                        tool_name=str(turn.tool_result.get("tool_name") or "exa.web_search"),
                        tool_args={"query": session.slug},
                        tool_content=self.archived_tool_json(record),
                        call_id=f"corpus_{session.slug}_{turn_index}",
                    )
                )
            worker.append({"role": "assistant", "content": turn.assistant})
            self.chat_store.append_messages(
                session_id,
                FAKE_USER,
                [{"role": "user", "content": turn.user}, *worker],
                source_at_for_message=[at, *[at] * len(worker)],
            )
            if turn_index == 1 or turn_index % 5 == 0 or turn.fact_ids:
                self.chat_store.append_session_trace(
                    session_id,
                    FAKE_USER,
                    trace=RunTrace(
                        user_id=FAKE_USER,
                        user_message=turn.user,
                        started_at=at.timestamp(),
                        final_outcome="success",
                        progress_summary=session.summary[:200],
                    ),
                    assistant_reply=turn.assistant,
                    source_at=at,
                )

        self.chat_store.archive_session(session_id, closed_by="new_chat")
        self.inject_summary(session_id, title=session.title, summary=session.summary)
        index_session_messages(self.chat_store, session_id)
        # stash tool refs on fixture for case wiring
        if not hasattr(self, "corpus_tool_refs"):
            self.corpus_tool_refs = {}
        self.corpus_tool_refs.update(
            {f"{session.slug}:{fact_id}": ref for fact_id, ref in tool_ref_by_fact.items()}
        )
        if not hasattr(self, "corpus_session_ids"):
            self.corpus_session_ids = {}
        self.corpus_session_ids[session.slug] = session_id
        return session_id

    def seed_corpus_sessions(
        self,
        pack: CorpusPack,
        session_slugs: tuple[str, ...] | list[str],
        *,
        open_fresh_active: bool = True,
    ) -> dict[str, str]:
        by_slug = pack.session_by_slug()
        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        mapping: dict[str, str] = {}
        for slug in session_slugs:
            session = by_slug.get(slug)
            if session is None:
                raise KeyError(f"Unknown corpus session slug: {slug}")
            mapping[slug] = self.seed_corpus_session(session, base_time=base)
        if open_fresh_active:
            # Ensure an empty active session for the probe question.
            active = self.chat_store.get_active_session(FAKE_USER)
            if active is None:
                self.chat_store.create_active_session(FAKE_USER, opened_by="corpus_probe")
            elif active.message_count > 0:
                self.chat_store.archive_and_create_active(FAKE_USER, closed_by="new_chat")
        self.reindex()
        return mapping


def fresh_fixture() -> MemoryEvalFixture:
    chat_store = ChatStore(":memory:")
    tool_store = ToolResultStore(":memory:")
    reset_chat_store(chat_store)
    reset_tool_result_store(tool_store)
    return MemoryEvalFixture(chat_store, tool_store)
