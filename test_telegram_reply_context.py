"""Tests for Telegram reply-to-message context injection."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot.chat_request import ChatRequest, merge_chat_requests
from bot.chat_service import ChatService
from bot.chat_store import ChatStore, reset_chat_store
from bot.telegram_reply_context import (
    apply_reply_context_prefix,
    format_reply_block,
    resolve_reply_context,
)
from bot.transcription_format import format_transcription_agent
from skills.session import SkillRunSnapshot


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _telegram_message(
    *,
    message_id: int = 100,
    text: str | None = "user question",
    reply_to_message=None,
    is_bot: bool = False,
):
    return SimpleNamespace(
        message_id=message_id,
        text=text,
        caption=None,
        from_user=SimpleNamespace(is_bot=is_bot, id=999),
        reply_to_message=reply_to_message,
        date=_utc(2026, 7, 8, 12, 0),
        quote=None,
        external_reply=None,
        voice=None,
        audio=None,
        photo=None,
        document=None,
        sticker=None,
        location=None,
    )


class TelegramReplyContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "CHAT_DB_PATH": ":memory:",
                "TELEGRAM_REPLY_CONTEXT_ENABLED": "1",
                "TELEGRAM_REPLY_TURN_RADIUS": "5",
                "CHAT_MAX_HISTORY": "50",
            },
            clear=False,
        )
        self.env.start()
        self.store = ChatStore(":memory:")
        reset_chat_store(self.store)
        self.user_id = 4242

    def tearDown(self) -> None:
        reset_chat_store(None)
        self.env.stop()

    def _persist_user_message(
        self,
        *,
        session_id: str,
        content: str,
        telegram_message_id: int,
        at: datetime,
    ) -> int:
        ids = self.store.append_messages(
            session_id,
            self.user_id,
            [{"role": "user", "content": content}],
            source_at_for_message=[at],
            metadata_for_message=[{"telegram_message_id": telegram_message_id}],
        )
        return ids[0]

    def test_resolve_without_reply_returns_none(self) -> None:
        message = _telegram_message(reply_to_message=None)
        self.assertIsNone(resolve_reply_context(message, self.user_id, self.store))

    def test_resolve_same_session_from_database(self) -> None:
        session = self.store.get_or_create_active_session(self.user_id)
        self._persist_user_message(
            session_id=session.session_id,
            content="Hotel code HOTEL-42",
            telegram_message_id=555,
            at=_utc(2026, 7, 8, 10, 0),
        )
        quoted = _telegram_message(message_id=555, text="Hotel code HOTEL-42")
        incoming = _telegram_message(
            message_id=556,
            text="ну как, забронировали?",
            reply_to_message=quoted,
        )
        ctx = resolve_reply_context(incoming, self.user_id, self.store)
        assert ctx is not None
        self.assertEqual(ctx.session_id, session.session_id)
        self.assertEqual(ctx.turn_number, 1)
        self.assertIn("HOTEL-42", ctx.quoted_body)
        self.assertFalse(ctx.is_cross_session)

    def test_cross_session_includes_summary_hint(self) -> None:
        old_session = self.store.get_or_create_active_session(self.user_id)
        self._persist_user_message(
            session_id=old_session.session_id,
            content="Plan trip to Samarkand",
            telegram_message_id=701,
            at=_utc(2026, 7, 7, 9, 0),
        )
        archived = self.store.archive_session(old_session.session_id, closed_by="reset")
        assert archived is not None
        with self.store._connect() as conn:
            conn.execute(
                """
                UPDATE chat_sessions
                SET title = ?, summary = ?, summary_status = 'done'
                WHERE session_id = ?
                """,
                (
                    "Trip day",
                    "User planned a Samarkand trip and discussed hotels.",
                    old_session.session_id,
                ),
            )
            conn.commit()

        new_session = self.store.get_or_create_active_session(self.user_id)
        self.assertNotEqual(new_session.session_id, old_session.session_id)

        quoted = _telegram_message(message_id=701, text="Plan trip to Samarkand")
        incoming = _telegram_message(
            message_id=702,
            text="а что там с отелем?",
            reply_to_message=quoted,
        )
        ctx = resolve_reply_context(incoming, self.user_id, self.store)
        assert ctx is not None
        self.assertTrue(ctx.is_cross_session)
        block = format_reply_block(ctx, user_reply_text="а что там с отелем?")
        self.assertIn("[telegram-reply]", block)
        self.assertIn("Samarkand", block)
        self.assertIn("chat.turns.read", block)
        self.assertIn("chat.session.summary", block)
        self.assertIn(old_session.session_id, block)

    def test_telegram_only_fallback(self) -> None:
        quoted = _telegram_message(message_id=900, text="Old bot answer from Telegram")
        incoming = _telegram_message(
            message_id=901,
            text="поясни",
            reply_to_message=quoted,
            is_bot=False,
        )
        ctx = resolve_reply_context(incoming, self.user_id, self.store)
        assert ctx is not None
        self.assertEqual(ctx.source, "telegram_only")
        self.assertIn("Old bot answer", ctx.quoted_body)

    def test_voice_reply_wraps_transcription_text(self) -> None:
        session = self.store.get_or_create_active_session(self.user_id)
        self._persist_user_message(
            session_id=session.session_id,
            content="Hotel code HOTEL-42",
            telegram_message_id=801,
            at=_utc(2026, 7, 8, 11, 0),
        )
        quoted = _telegram_message(message_id=801, text="Hotel code HOTEL-42")
        voice = _telegram_message(
            message_id=802,
            text=None,
            reply_to_message=quoted,
        )
        voice.voice = SimpleNamespace(file_id="voice-file")
        transcript = format_transcription_agent("ну как, забронировали?", "voice")
        block = apply_reply_context_prefix(
            transcript,
            telegram_message=voice,
            user_id=self.user_id,
            chat_store=self.store,
        )
        self.assertIn("[telegram-reply]", block)
        self.assertIn("HOTEL-42", block)
        self.assertIn("[transcription:voice]", block)
        self.assertIn("ну как, забронировали?", block)

    def test_quote_fallback_when_reply_body_empty(self) -> None:
        quoted = _telegram_message(message_id=910, text=None)
        incoming = _telegram_message(
            message_id=911,
            text="уточни",
            reply_to_message=quoted,
        )
        incoming.quote = SimpleNamespace(text="фрагмент из цитаты", position=0, is_manual=True)
        ctx = resolve_reply_context(incoming, self.user_id, self.store)
        assert ctx is not None
        self.assertTrue(ctx.is_partial_quote)
        self.assertIn("фрагмент", ctx.quoted_body)
        block = format_reply_block(ctx, user_reply_text="уточни")
        self.assertIn("Quoted fragment", block)
        self.assertIn("quote_scope=partial", block)

    def test_partial_quote_uses_fragment_not_full_turn(self) -> None:
        session = self.store.get_or_create_active_session(self.user_id)
        long_text = (
            "Here is a long answer with hotel code HOTEL-42 and many other details "
            "about the trip that the user does not care about right now."
        )
        self._persist_user_message(
            session_id=session.session_id,
            content=long_text,
            telegram_message_id=820,
            at=_utc(2026, 7, 8, 12, 0),
        )
        quoted = _telegram_message(message_id=820, text=long_text)
        incoming = _telegram_message(
            message_id=821,
            text="что это за код?",
            reply_to_message=quoted,
        )
        incoming.quote = SimpleNamespace(text="HOTEL-42", position=42, is_manual=True)
        ctx = resolve_reply_context(incoming, self.user_id, self.store)
        assert ctx is not None
        self.assertTrue(ctx.is_partial_quote)
        self.assertEqual(ctx.quoted_body, "HOTEL-42")
        self.assertEqual(ctx.turn_number, 1)
        self.assertEqual(ctx.session_id, session.session_id)
        block = format_reply_block(ctx, user_reply_text="что это за код?")
        self.assertIn("HOTEL-42", block)
        self.assertNotIn("many other details", block)
        self.assertIn("chat.turns.read", block)
        self.assertIn("selected fragment", block)

    def test_find_message_by_telegram_id(self) -> None:
        session = self.store.get_or_create_active_session(self.user_id)
        self._persist_user_message(
            session_id=session.session_id,
            content="needle",
            telegram_message_id=321,
            at=_utc(2026, 7, 9, 12, 0),
        )
        found = self.store.find_message_by_telegram_id(self.user_id, 321)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.content, "needle")


class TelegramReplyMergeTests(unittest.TestCase):
    def test_burst_merge_skipped_when_reply_present(self) -> None:
        quoted = _telegram_message(message_id=10, text="first")
        first = ChatRequest(
            message=_telegram_message(message_id=11, text="a"),
            user_text="a",
        )
        second = ChatRequest(
            message=_telegram_message(
                message_id=12,
                text="b",
                reply_to_message=quoted,
            ),
            user_text="b",
        )
        message, text, _, _ = merge_chat_requests([first, second])
        self.assertEqual(text, "b")
        self.assertEqual(message.message_id, 12)
        self.assertIsNotNone(message.reply_to_message)


class TelegramReplyServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "CHAT_DB_PATH": ":memory:",
                "TELEGRAM_REPLY_CONTEXT_ENABLED": "1",
                "TELEGRAM_REPLY_TURN_RADIUS": "5",
            },
            clear=False,
        )
        self.env.start()
        self.store = ChatStore(":memory:")
        reset_chat_store(self.store)
        self.user_id = 777

    def tearDown(self) -> None:
        reset_chat_store(None)
        self.env.stop()

    async def test_generate_reply_persists_reply_block_with_voice_transcription(self) -> None:
        session = self.store.get_or_create_active_session(self.user_id)
        self.store.append_messages(
            session.session_id,
            self.user_id,
            [{"role": "user", "content": "Hotel HOTEL-42"}],
            source_at_for_message=[_utc(2026, 7, 8, 8, 0)],
            metadata_for_message=[{"telegram_message_id": 44}],
        )

        agent = MagicMock()
        agent.run = AsyncMock(
            return_value=SimpleNamespace(
                reply="ok",
                worker_history=[{"role": "assistant", "content": "ok"}],
                skill_snapshot=SkillRunSnapshot(
                    expanded_skill_id=None,
                    skills_with_tools=frozenset(),
                ),
                maps_buttons=(),
                gmail_buttons=(),
                calendar_buttons=(),
                tasks_buttons=(),
                drive_buttons=(),
                outbound_files=(),
            )
        )
        agent.last_trace = MagicMock(return_value=None)
        service = ChatService(agent, chat_store=self.store)

        quoted = _telegram_message(message_id=44, text="Hotel HOTEL-42")
        voice = _telegram_message(
            message_id=45,
            text=None,
            reply_to_message=quoted,
        )
        voice.voice = SimpleNamespace(file_id="voice-file")
        transcript = format_transcription_agent("ну как?", "voice")

        await service.generate_reply(
            self.user_id,
            transcript,
            message_at=_utc(2026, 7, 8, 8, 5),
            telegram_message_id=45,
            telegram_chat_id=12345,
            telegram_message=voice,
        )

        messages = self.store.read_messages(session.session_id)
        user_rows = [row for row in messages if row.role == "user"]
        self.assertIn("[telegram-reply]", user_rows[-1].content or "")
        self.assertIn("HOTEL-42", user_rows[-1].content or "")
        self.assertIn("[transcription:voice]", user_rows[-1].content or "")

    async def test_generate_reply_persists_reply_block(self) -> None:
        session = self.store.get_or_create_active_session(self.user_id)
        self.store.append_messages(
            session.session_id,
            self.user_id,
            [{"role": "user", "content": "favorite city Samarkand"}],
            source_at_for_message=[_utc(2026, 7, 8, 8, 0)],
            metadata_for_message=[{"telegram_message_id": 44}],
        )

        agent = MagicMock()
        agent.run = AsyncMock(
            return_value=SimpleNamespace(
                reply="ok",
                worker_history=[{"role": "assistant", "content": "ok"}],
                skill_snapshot=SkillRunSnapshot(
                    expanded_skill_id=None,
                    skills_with_tools=frozenset(),
                ),
                maps_buttons=(),
                gmail_buttons=(),
                calendar_buttons=(),
                tasks_buttons=(),
                drive_buttons=(),
                outbound_files=(),
            )
        )
        agent.last_trace = MagicMock(return_value=None)
        service = ChatService(agent, chat_store=self.store)

        quoted = _telegram_message(message_id=44, text="favorite city Samarkand")
        incoming = _telegram_message(
            message_id=45,
            text="почему?",
            reply_to_message=quoted,
        )

        await service.generate_reply(
            self.user_id,
            "почему?",
            message_at=_utc(2026, 7, 8, 8, 5),
            telegram_message_id=45,
            telegram_chat_id=12345,
            telegram_message=incoming,
        )

        messages = self.store.read_messages(session.session_id)
        user_rows = [row for row in messages if row.role == "user"]
        self.assertEqual(len(user_rows), 2)
        self.assertIn("[telegram-reply]", user_rows[-1].content or "")
        self.assertIn("Samarkand", user_rows[-1].content or "")
        self.assertIn("почему?", user_rows[-1].content or "")

    def test_apply_prefix_disabled(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_REPLY_CONTEXT_ENABLED": "0"}, clear=False):
            quoted = _telegram_message(message_id=1, text="x")
            incoming = _telegram_message(
                message_id=2,
                text="y",
                reply_to_message=quoted,
            )
            result = apply_reply_context_prefix(
                "y",
                telegram_message=incoming,
                user_id=self.user_id,
                chat_store=self.store,
            )
            self.assertEqual(result, "y")


if __name__ == "__main__":
    unittest.main()
