import json
import sqlite3
import unittest
from datetime import datetime, timezone

from bot.chat_store import ChatStore
from bot.chat_store.schema import SCHEMA_VERSION, ensure_schema


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class ChatStoreSchemaTests(unittest.TestCase):
    def test_schema_version_recorded(self) -> None:
        store = ChatStore(db_path=":memory:")
        with store._connect() as conn:
            row = conn.execute(
                "SELECT MAX(version) AS version FROM schema_migrations"
            ).fetchone()
        self.assertEqual(int(row["version"]), SCHEMA_VERSION)


class ChatStoreSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ChatStore(db_path=":memory:")

    def test_get_or_create_active_is_idempotent(self) -> None:
        first = self.store.get_or_create_active_session(42, opened_by="first_message")
        second = self.store.get_or_create_active_session(42)
        self.assertEqual(first.session_id, second.session_id)
        self.assertEqual(first.status, "active")

    def test_one_active_session_per_user(self) -> None:
        self.store.get_or_create_active_session(1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_active_session(1)

    def test_archive_active_and_create_new(self) -> None:
        active = self.store.get_or_create_active_session(7)
        archived, new_active = self.store.archive_and_create_active(
            7,
            closed_by="reset",
        )
        self.assertIsNotNone(archived)
        assert archived is not None
        self.assertEqual(archived.session_id, active.session_id)
        self.assertEqual(archived.status, "archived")
        self.assertEqual(archived.summary_status, "pending")
        self.assertIsNotNone(archived.archived_at)
        self.assertEqual(archived.metadata.get("closed_by"), "reset")
        self.assertNotEqual(new_active.session_id, active.session_id)
        self.assertEqual(new_active.status, "active")

    def test_list_sessions_by_status(self) -> None:
        self.store.get_or_create_active_session(9)
        self.store.archive_and_create_active(9, closed_by="reset")
        archived = self.store.list_sessions(9, status="archived")
        active = self.store.list_sessions(9, status="active")
        self.assertEqual(len(archived), 1)
        self.assertEqual(len(active), 1)


class ChatStoreMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ChatStore(db_path=":memory:")
        self.user_id = 100
        self.session = self.store.get_or_create_active_session(self.user_id)
        self.t1 = _utc(2026, 7, 9, 10, 0)
        self.t2 = _utc(2026, 7, 9, 10, 5)

    def test_append_and_round_trip(self) -> None:
        messages = [
            {"role": "user", "content": "find route"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "u1",
                        "type": "function",
                        "function": {
                            "name": "use_tool",
                            "arguments": json.dumps(
                                {
                                    "tool_name": "google.maps.maps_link",
                                    "arguments": {"origin": "A", "destination": "B"},
                                }
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "u1",
                "content": json.dumps(
                    {
                        "tool_name": "google.maps.maps_link",
                        "ok": True,
                        "result": {"url": "https://maps.example/a-b"},
                    }
                ),
            },
            {"role": "assistant", "content": "Here is the route."},
        ]
        ids = self.store.append_messages(
            self.session.session_id,
            self.user_id,
            messages,
            default_source_at=self.t2,
            source_at_for_message=[self.t1, self.t2, self.t2, self.t2],
            metadata_for_message=[
                {"telegram_message_id": 1001, "telegram_chat_id": 555},
                None,
                None,
                None,
            ],
        )
        self.assertEqual(len(ids), 4)

        loaded = self.store.read_message_dicts(self.session.session_id)
        self.assertEqual(len(loaded), 4)
        self.assertEqual(loaded[0]["content"], "find route")
        self.assertIn("tool_calls", loaded[1])
        self.assertEqual(loaded[1]["tool_calls"][0]["id"], "u1")
        self.assertEqual(loaded[2]["tool_call_id"], "u1")
        self.assertIn("google.maps.maps_link", loaded[2]["content"])
        self.assertEqual(loaded[3]["content"], "Here is the route.")

        row = self.store.get_message_by_id(ids[0])
        assert row is not None
        self.assertEqual(row.metadata["telegram_message_id"], 1001)
        self.assertEqual(row.source_at, self.t1)

        updated = self.store.get_active_session(self.user_id)
        assert updated is not None
        self.assertEqual(updated.message_count, 4)
        self.assertEqual(updated.started_at, self.t1)
        self.assertEqual(updated.last_message_at, self.t2)

    def test_seq_is_monotonic(self) -> None:
        self.store.append_messages(
            self.session.session_id,
            self.user_id,
            [{"role": "user", "content": "one"}],
            default_source_at=self.t1,
        )
        self.store.append_messages(
            self.session.session_id,
            self.user_id,
            [{"role": "assistant", "content": "two"}],
            default_source_at=self.t2,
        )
        rows = self.store.read_messages(self.session.session_id)
        self.assertEqual([row.seq for row in rows], [1, 2])

    def test_read_range(self) -> None:
        self.store.append_messages(
            self.session.session_id,
            self.user_id,
            [
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
                {"role": "user", "content": "c"},
            ],
            default_source_at=self.t1,
        )
        partial = self.store.read_message_dicts(self.session.session_id, from_seq=2, limit=1)
        self.assertEqual(len(partial), 1)
        self.assertEqual(partial[0]["content"], "b")

    def test_last_user_source_at(self) -> None:
        self.store.append_messages(
            self.session.session_id,
            self.user_id,
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ok"},
            ],
            source_at_for_message=[self.t1, self.t2],
        )
        self.store.append_messages(
            self.session.session_id,
            self.user_id,
            [{"role": "user", "content": "second"}],
            default_source_at=self.t2,
        )
        last = self.store.get_last_user_source_at(self.session.session_id)
        self.assertEqual(last, self.t2)

    def test_load_active_history_for_prompt_trims_turns(self) -> None:
        session = self.store.get_or_create_active_session(200)
        batch = []
        for turn in range(3):
            batch.extend(
                [
                    {"role": "user", "content": f"user-{turn}"},
                    {"role": "assistant", "content": f"assistant-{turn}"},
                ]
            )
        self.store.append_messages(session.session_id, 200, batch, default_source_at=self.t1)

        loaded_session, history, last_at = self.store.load_active_history_for_prompt(
            200,
            max_turns=1,
        )
        self.assertIsNotNone(loaded_session)
        self.assertEqual(history[0]["content"], "user-2")
        self.assertEqual(len(history), 2)
        self.assertEqual(last_at, self.t1)


if __name__ == "__main__":
    unittest.main()
