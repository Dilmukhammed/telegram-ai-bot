import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from bot.chat_store import ChatStore, reset_chat_store
from bot.chat_store.migrate_v1 import (
    _load_v1_rows,
    migrate_v1_history,
    migration_already_applied,
    run_v1_migration_if_needed,
    seed_v1_history_db,
    verify_v1_migration,
)
from config import get_settings


class ChatV1MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_store(None)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.v1_path = Path(self.temp_dir.name) / "chat_history.sqlite"
        self.user_id = 9001
        self.messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "again"},
            {"role": "assistant", "content": "sure"},
        ]
        seed_v1_history_db(self.v1_path, self.user_id, self.messages)
        self.assertTrue(self.v1_path.is_file())
        self.assertEqual(len(_load_v1_rows(self.v1_path)), 1)
        self.store = ChatStore(db_path=":memory:")

    def tearDown(self) -> None:
        reset_chat_store(None)
        if hasattr(self, "store") and self.store is not None and self.store._memory_conn is not None:
            self.store._memory_conn.close()
            self.store._memory_conn = None
        self.store = None  # type: ignore[assignment]
        try:
            self.temp_dir.cleanup()
        except (PermissionError, NotADirectoryError, OSError):
            pass

    def test_migrate_to_active_session(self) -> None:
        result = migrate_v1_history(
            self.store,
            source_db_path=str(self.v1_path),
            target="active",
            backup=False,
        )
        self.assertTrue(result.applied, result.reason)
        self.assertEqual(result.users_migrated, 1, result.errors)
        self.assertEqual(result.messages_migrated, 4)

        active = self.store.get_active_session(self.user_id)
        assert active is not None
        self.assertEqual(active.message_count, 4)
        self.assertEqual(active.metadata.get("migrated_from"), "chat_history_v1")

        _, history, _ = self.store.load_active_history_for_prompt(self.user_id, max_turns=20)
        self.assertEqual(len(history), 4)
        self.assertEqual(history[0]["content"], "hello")

        report = verify_v1_migration(self.store, source_db_path=str(self.v1_path))
        self.assertTrue(report["ok"], report["mismatches"])

    def test_migrate_to_archived_plus_empty_active(self) -> None:
        result = migrate_v1_history(
            self.store,
            source_db_path=str(self.v1_path),
            target="archived",
            backup=False,
        )
        self.assertEqual(result.users_migrated, 1)

        archived = self.store.list_sessions(self.user_id, status="archived")
        active = self.store.get_active_session(self.user_id)
        assert active is not None
        self.assertEqual(active.message_count, 0)
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].message_count, 4)
        self.assertIsNone(archived[0].summary_status)

        _, history, _ = self.store.load_active_history_for_prompt(self.user_id, max_turns=20)
        self.assertEqual(history, [])

    def test_migration_is_idempotent(self) -> None:
        first = migrate_v1_history(
            self.store,
            source_db_path=str(self.v1_path),
            target="active",
            backup=False,
        )
        self.assertTrue(first.applied)
        self.assertTrue(migration_already_applied(self.store))

        second = migrate_v1_history(
            self.store,
            source_db_path=str(self.v1_path),
            target="active",
            backup=False,
        )
        self.assertFalse(second.applied)
        self.assertEqual(second.reason, "already migrated")

    def test_skips_user_with_existing_v2_data(self) -> None:
        self.store.get_or_create_active_session(self.user_id)
        result = migrate_v1_history(
            self.store,
            source_db_path=str(self.v1_path),
            target="active",
            backup=False,
        )
        self.assertTrue(result.applied)
        self.assertEqual(result.users_migrated, 0)
        self.assertEqual(result.users_skipped, 1)

    def test_run_if_needed_disabled(self) -> None:
        settings = replace(get_settings(), chat_migrate_v1_on_startup=False)
        result = run_v1_migration_if_needed(self.store, settings=settings)
        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "disabled")

    def test_backup_created(self) -> None:
        migrate_v1_history(
            self.store,
            source_db_path=str(self.v1_path),
            target="active",
            backup=True,
        )
        backup = self.v1_path.with_suffix(self.v1_path.suffix + ".bak")
        self.assertTrue(backup.is_file())
        self.assertGreater(backup.stat().st_size, 0)

    def test_seed_v1_history_db_round_trip(self) -> None:
        path = Path(self.temp_dir.name) / "seed.sqlite"
        seed_v1_history_db(
            path,
            42,
            [{"role": "user", "content": "x"}],
            last_message_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
        )
        rows = _load_v1_rows(path)
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0]["messages_json"])
        self.assertEqual(payload[0]["content"], "x")


if __name__ == "__main__":
    unittest.main()
