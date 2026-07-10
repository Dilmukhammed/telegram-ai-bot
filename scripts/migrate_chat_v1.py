#!/usr/bin/env python3
"""One-shot migration: chat_history.sqlite (v1 blob) → chat.sqlite (v2 sessions)."""

from __future__ import annotations

import argparse
import json
import sys

from bot.chat_store.migrate_v1 import migrate_v1_history, verify_v1_migration
from bot.chat_store.store import ChatStore
from config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate chat history v1 blob store to chat_store v2.")
    parser.add_argument(
        "--source",
        help="Path to legacy v1 chat_history.sqlite (default: CHAT_MIGRATE_V1_SOURCE_PATH)",
    )
    parser.add_argument(
        "--target-db",
        help="Path to v2 chat.sqlite (default: CHAT_DB_PATH)",
    )
    parser.add_argument(
        "--target",
        choices=("active", "archived"),
        help="Import v1 blob as active session (default) or archived+empty active",
    )
    parser.add_argument("--no-backup", action="store_true", help="Skip .bak copy of v1 DB")
    parser.add_argument("--force", action="store_true", help="Re-run even if migration marker exists")
    parser.add_argument("--verify-only", action="store_true", help="Verify counts without migrating")
    args = parser.parse_args()

    settings = get_settings()
    store = ChatStore(db_path=args.target_db or settings.chat_db_path)
    source = args.source or settings.chat_migrate_v1_source_path

    if args.verify_only:
        report = verify_v1_migration(store, source_db_path=source)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    result = migrate_v1_history(
        store,
        settings=settings,
        source_db_path=source,
        target=args.target,
        backup=not args.no_backup,
        force=args.force,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    if result.applied and result.users_migrated:
        report = verify_v1_migration(store, source_db_path=source)
        print(json.dumps({"verify": report}, ensure_ascii=False, indent=2))
        if not report["ok"]:
            return 1
    return 0 if result.applied or result.reason in {"already migrated", "disabled", "no v1 rows"} else 1


if __name__ == "__main__":
    sys.exit(main())
