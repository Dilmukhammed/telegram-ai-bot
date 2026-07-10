"""Tests for day/week/month chat period digests."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from bot.chat_store import reset_chat_store
from bot.chat_store.period_boundary import run_period_boundary_once
from bot.chat_store.period_keys import (
    closed_period_keys,
    day_key,
    month_key,
    parse_period_key,
    period_key_for,
    previous_day_key,
    previous_month_key,
    previous_week_key,
    to_local_date,
    week_key,
)
from bot.chat_store.period_summary import ensure_period_summary, summarize_period
from bot.chat_store.store import ChatStore
from tools.bootstrap import create_tool_runtime
from tools.builtins.chat_tools import CHAT_TOOLS
from tools.context import RunContext


class PeriodKeyTests(unittest.TestCase):
    def test_iso_week_and_month(self) -> None:
        d = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
        local = to_local_date(d, "Asia/Tashkent")
        self.assertEqual(day_key(local), "2026-07-09")
        self.assertEqual(week_key(local), "2026-W28")
        self.assertEqual(month_key(local), "2026-07")
        self.assertEqual(period_key_for(local, "week"), "2026-W28")

    def test_parse_period_key(self) -> None:
        self.assertEqual(parse_period_key("day", "2026-07-09"), "2026-07-09")
        self.assertEqual(parse_period_key("week", "2026-w28"), "2026-W28")
        self.assertEqual(parse_period_key("month", "2026-7"), "2026-07")

    def test_closed_period_keys(self) -> None:
        # 2026-07-09 12:00 UTC = same local day in UTC tz
        now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
        closed = closed_period_keys(now, "UTC")
        self.assertEqual(closed["day"], "2026-07-08")
        self.assertEqual(closed["week"], previous_week_key(now.date()))
        self.assertEqual(closed["month"], "2026-06")
        self.assertEqual(previous_day_key(now.date()), "2026-07-08")
        self.assertEqual(previous_month_key(now.date()), "2026-06")


class PeriodSummaryStoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "CHAT_DB_PATH": ":memory:",
                "CHAT_PERIOD_SUMMARY_ENABLED": "1",
                "CHAT_PERIOD_SUMMARY_ON_SESSION_ARCHIVE": "0",
                "CHAT_PERIOD_SUMMARY_BOUNDARY_ENABLED": "1",
                "BOT_TIMEZONE": "UTC",
            },
            clear=False,
        )
        self.env.start()
        self.store = ChatStore(":memory:")
        reset_chat_store(self.store)
        self.user_id = 123456

    def tearDown(self) -> None:
        reset_chat_store(None)
        self.env.stop()

    def _seed_archived_session(
        self,
        *,
        started: datetime,
        title: str,
        summary: str,
    ) -> str:
        session = self.store.get_or_create_active_session(self.user_id, opened_by="test")
        self.store.append_messages(
            session.session_id,
            self.user_id,
            [
                {"role": "user", "content": f"note for {title}"},
                {"role": "assistant", "content": "ok"},
            ],
            source_at_for_message=[started, started + timedelta(minutes=1)],
        )
        with self.store._connect() as conn:
            conn.execute(
                """
                UPDATE chat_sessions
                SET started_at = ?, last_message_at = ?
                WHERE session_id = ?
                """,
                (started.isoformat(), started.isoformat(), session.session_id),
            )
            conn.commit()
        self.store.archive_session(session.session_id, closed_by="new_chat")
        with self.store._connect() as conn:
            from bot.chat_store import sessions as session_ops

            session_ops.update_session_summary_status(
                conn,
                session.session_id,
                title=title,
                summary=summary,
                summary_status="done",
                summary_completed_at=started + timedelta(hours=1),
            )
            conn.commit()
        return session.session_id

    async def test_summarize_day_period(self) -> None:
        day = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        self._seed_archived_session(
            started=day,
            title="Trip planning",
            summary="User planned a trip to Samarkand and saved a hotel code for later.",
        )
        self._seed_archived_session(
            started=day + timedelta(hours=3),
            title="Budget",
            summary="User set a trip budget and asked about exchange rates briefly.",
        )

        with patch("bot.chat_store.period_summary.LLMClient") as llm_cls:
            llm = llm_cls.return_value
            llm.chat_without_reasoning = AsyncMock(
                return_value=(
                    '{"title":"June 1 trip day","summary":'
                    '"The user planned a Samarkand trip, saved a hotel code, '
                    'and discussed budget and exchange rates across two sessions."}'
                )
            )
            result = await summarize_period(
                self.store,
                user_id=self.user_id,
                period_type="day",
                period_key="2026-06-01",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["session_count"], 2)
        period = self.store.get_period_summary(self.user_id, "day", "2026-06-01")
        self.assertIsNotNone(period)
        assert period is not None
        self.assertEqual(period.summary_status, "done")
        self.assertIn("Samarkand", period.summary or "")

        cached = await ensure_period_summary(
            self.store,
            user_id=self.user_id,
            period_type="day",
            period_key="2026-06-01",
        )
        self.assertTrue(cached["ok"])
        self.assertTrue(cached["cached"])

    async def test_period_tools_registered(self) -> None:
        names = {tool.name for tool in CHAT_TOOLS}
        self.assertIn("chat.period.summary", names)
        self.assertIn("chat.periods.list", names)

    async def test_period_tools_via_runtime(self) -> None:
        day = datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc)
        self._seed_archived_session(
            started=day,
            title="Health",
            summary="User recorded a pharmacy code and mentioned a food allergy update.",
        )
        with patch("bot.chat_store.period_summary.LLMClient") as llm_cls:
            llm = llm_cls.return_value
            llm.chat_without_reasoning = AsyncMock(
                return_value=(
                    '{"title":"Health day","summary":'
                    '"The user updated pharmacy and allergy details in one archived session."}'
                )
            )
            runtime = await create_tool_runtime()
            ctx = RunContext(user_id=self.user_id)
            got_env = await runtime.use_tool(
                "chat.period.summary",
                {"period_type": "day", "period_key": "2026-05-10"},
                ctx=ctx,
            )
            got = got_env.get("result") if isinstance(got_env.get("result"), dict) else got_env
            self.assertTrue(got.get("ok"), got)
            listed_env = await runtime.use_tool(
                "chat.periods.list",
                {"period_type": "day"},
                ctx=ctx,
            )
            listed = (
                listed_env.get("result")
                if isinstance(listed_env.get("result"), dict)
                else listed_env
            )
            self.assertTrue(listed.get("ok"), listed)
            self.assertGreaterEqual(listed.get("count", 0), 1)

    async def test_boundary_closes_yesterday_once(self) -> None:
        yesterday = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
        self._seed_archived_session(
            started=yesterday,
            title="Closed day work",
            summary=(
                "User finished trip planning and confirmed the hotel booking details "
                "for the archived day session."
            ),
        )
        now = datetime(2026, 6, 2, 0, 5, tzinfo=timezone.utc)
        with patch("bot.chat_store.period_summary.LLMClient") as llm_cls:
            llm = llm_cls.return_value
            llm.chat_without_reasoning = AsyncMock(
                return_value=(
                    '{"title":"June 1 wrap","summary":'
                    '"The user finished trip planning and confirmed hotel booking details."}'
                )
            )
            first = await run_period_boundary_once(self.store, now=now)
            second = await run_period_boundary_once(self.store, now=now)

        self.assertIn("day", first)
        self.assertEqual(first["day"]["ok"], 1)
        # Idempotent: second tick must not re-close.
        self.assertEqual(second, {})
        period = self.store.get_period_summary(self.user_id, "day", "2026-06-01")
        self.assertIsNotNone(period)
        assert period is not None
        self.assertEqual(period.summary_status, "done")
        # LLM called once for day (week/month may also close if not marked).
        self.assertGreaterEqual(llm.chat_without_reasoning.await_count, 1)


if __name__ == "__main__":
    unittest.main()
