import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from tools.builtins.google.auth import TASKS_SCOPE, auth_status_payload, user_has_tasks_scope
from tools.builtins.google.tasks_datetime import (
    due_bounds_for_day,
    normalize_task_due,
    today_date,
)
from tools.builtins.google.tasks_defaults import (
    _pick_default_tasklist,
    clear_default_tasklist_cache,
    resolve_default_tasklist,
)
from tools.builtins.google.tasks_serialize import (
    build_task_patch_body,
    build_tasklist_patch_body,
    compact_task,
    compact_tasklist,
    merge_task_for_update,
    merge_tasklist_for_update,
)
from tools.builtins.google.tasks_tools import (
    GOOGLE_TASKS_TOOLS,
    _clear_completed_handler,
    _complete_task_handler,
    _create_task_handler,
    _create_tasklist_handler,
    _delete_task_handler,
    _delete_tasklist_handler,
    _list_today_handler,
    _patch_task_handler,
    _quick_add_task_handler,
    _search_tasks_handler,
    _uncomplete_task_handler,
)
from tools.builtins.google.token_store import GoogleTokenStore
from tools.context import RunContext, get_run_context, reset_run_context, set_run_context


class TasksSerializeTests(unittest.TestCase):
    def test_compact_task(self) -> None:
        task = compact_task(
            {
                "id": "t1",
                "title": "Buy milk",
                "status": "needsAction",
                "due": "2026-07-04T00:00:00.000Z",
                "webViewLink": "https://tasks.google.com/task/t1",
                "notes": "2%",
            }
        )
        self.assertEqual(task["id"], "t1")
        self.assertEqual(task["title"], "Buy milk")
        self.assertEqual(task["webViewLink"], "https://tasks.google.com/task/t1")

    def test_compact_tasklist(self) -> None:
        tasklist = compact_tasklist({"id": "list1", "title": "My Tasks", "updated": "2026-07-03"})
        self.assertEqual(tasklist["title"], "My Tasks")


    def test_merge_task_for_update(self) -> None:
        existing = {
            "id": "t1",
            "title": "Old",
            "status": "needsAction",
            "notes": "keep",
            "due": "2026-07-04T00:00:00.000Z",
        }
        body = merge_task_for_update(existing, {"title": "New title"})
        self.assertEqual(body["title"], "New title")
        self.assertEqual(body["notes"], "keep")

    def test_build_tasklist_patch_body(self) -> None:
        body = build_tasklist_patch_body({"title": "Shopping"})
        self.assertEqual(body["title"], "Shopping")

    def test_merge_tasklist_for_update(self) -> None:
        body = merge_tasklist_for_update({"id": "l1", "title": "Old"}, {"title": "New"})
        self.assertEqual(body["title"], "New")


class TasksDatetimeTests(unittest.TestCase):
    def test_normalize_task_due_date_only(self) -> None:
        due = normalize_task_due("2026-07-04")
        self.assertIn("2026-07-04", due)

    def test_due_bounds_for_day(self) -> None:
        due_min, due_max = due_bounds_for_day(date(2026, 7, 4), "UTC")
        self.assertLess(due_min, due_max)


class TasksDefaultsTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_default_tasklist_prefers_my_tasks(self) -> None:
        clear_default_tasklist_cache()
        mock_service = MagicMock()
        mock_service.tasklists.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "shopping", "title": "Shopping"},
                {"id": "default", "title": "My Tasks"},
            ]
        }
        with patch(
            "tools.builtins.google.tasks_defaults.get_tasks_service",
            new=AsyncMock(return_value=mock_service),
        ):
            tasklist_id, title = await resolve_default_tasklist(42)
        self.assertEqual(tasklist_id, "default")
        self.assertEqual(title, "My Tasks")

    def test_pick_default_tasklist_russian(self) -> None:
        picked = _pick_default_tasklist([{"id": "1", "title": "Покупки"}, {"id": "2", "title": "Мои задачи"}])
        assert picked is not None
        self.assertEqual(picked["id"], "2")


class TasksAuthTests(unittest.TestCase):
    def test_user_has_tasks_scope(self) -> None:
        store = GoogleTokenStore(db_path=":memory:")
        store.save(
            telegram_user_id=7,
            email="user@example.com",
            refresh_token="r",
            access_token="a",
            token_expiry=None,
            scopes=(TASKS_SCOPE,),
        )
        stored = store.get(7)
        self.assertTrue(user_has_tasks_scope(stored))

    def test_auth_status_tasks_ready(self) -> None:
        store = GoogleTokenStore(db_path=":memory:")
        store.save(
            telegram_user_id=8,
            email="user@example.com",
            refresh_token="r",
            access_token="a",
            token_expiry=None,
            scopes=(TASKS_SCOPE,),
        )
        with patch("tools.builtins.google.auth.get_token_store", return_value=store), patch(
            "tools.builtins.google.auth.google_oauth_configured",
            return_value=True,
        ):
            status = auth_status_payload(8)
        self.assertTrue(status["tasks_ready"])


class TasksHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._ctx = RunContext(user_id=99)
        self._token = set_run_context(self._ctx)

    async def asyncTearDown(self) -> None:
        reset_run_context(self._token)
        clear_default_tasklist_cache(99)

    async def test_create_task_handler(self) -> None:
        mock_service = MagicMock()
        mock_service.tasks.return_value.insert.return_value.execute.return_value = {
            "id": "new1",
            "title": "Call mom",
            "status": "needsAction",
            "webViewLink": "https://tasks.google.com/task/new1",
        }
        with patch(
            "tools.builtins.google.tasks_tools.get_tasks_service",
            new=AsyncMock(return_value=mock_service),
        ), patch(
            "tools.builtins.google.tasks_tools.resolve_tasklist_id",
            new=AsyncMock(return_value=("list1", None)),
        ):
            result = await _create_task_handler({"title": "Call mom"})
        self.assertTrue(result["created"])
        self.assertEqual(result["task"]["title"], "Call mom")

    async def test_complete_task_handler(self) -> None:
        mock_service = MagicMock()
        mock_service.tasks.return_value.patch.return_value.execute.return_value = {
            "id": "t1",
            "title": "Done task",
            "status": "completed",
        }
        with patch(
            "tools.builtins.google.tasks_tools.get_tasks_service",
            new=AsyncMock(return_value=mock_service),
        ), patch(
            "tools.builtins.google.tasks_tools.resolve_tasklist_id",
            new=AsyncMock(return_value=("list1", None)),
        ):
            result = await _complete_task_handler({"task_id": "t1"})
        self.assertTrue(result["completed"])
        self.assertEqual(result["task"]["status"], "completed")

    async def test_quick_add_delegates_to_create(self) -> None:
        with patch(
            "tools.builtins.google.tasks_tools._create_task_handler",
            new=AsyncMock(return_value={"created": True, "task": {"title": "Bread"}}),
        ) as create_mock:
            result = await _quick_add_task_handler({"title": "Bread"})
        create_mock.assert_awaited_once()
        self.assertTrue(result["created"])

    async def test_list_today_filters_completed(self) -> None:
        mock_service = MagicMock()
        mock_service.tasks.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "1",
                    "title": "Open",
                    "status": "needsAction",
                    "due": "2026-07-04T00:00:00.000Z",
                },
                {
                    "id": "2",
                    "title": "Done",
                    "status": "completed",
                    "due": "2026-07-04T00:00:00.000Z",
                },
            ]
        }
        with patch(
            "tools.builtins.google.tasks_tools.get_tasks_service",
            new=AsyncMock(return_value=mock_service),
        ), patch(
            "tools.builtins.google.tasks_tools.resolve_tasklist_id",
            new=AsyncMock(return_value=("list1", None)),
        ), patch(
            "tools.builtins.google.tasks_tools.today_date",
            return_value=date(2026, 7, 4),
        ):
            result = await _list_today_handler({})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["tasks"][0]["title"], "Open")

    async def test_patch_task_handler(self) -> None:
        mock_service = MagicMock()
        mock_service.tasks.return_value.patch.return_value.execute.return_value = {
            "id": "t1",
            "title": "Renamed",
            "status": "needsAction",
        }
        with patch(
            "tools.builtins.google.tasks_tools.get_tasks_service",
            new=AsyncMock(return_value=mock_service),
        ), patch(
            "tools.builtins.google.tasks_tools.resolve_tasklist_id",
            new=AsyncMock(return_value=("list1", None)),
        ):
            result = await _patch_task_handler({"task_id": "t1", "title": "Renamed"})
        self.assertTrue(result["patched"])

    async def test_delete_task_handler(self) -> None:
        mock_service = MagicMock()
        mock_service.tasks.return_value.delete.return_value.execute.return_value = None
        with patch(
            "tools.builtins.google.tasks_tools.get_tasks_service",
            new=AsyncMock(return_value=mock_service),
        ), patch(
            "tools.builtins.google.tasks_tools.resolve_tasklist_id",
            new=AsyncMock(return_value=("list1", None)),
        ):
            result = await _delete_task_handler({"task_id": "t1"})
        self.assertTrue(result["deleted"])

    async def test_search_tasks_handler(self) -> None:
        with patch(
            "tools.builtins.google.tasks_tools.fetch_tasklists",
            new=AsyncMock(
                return_value=[{"id": "list1", "title": "My Tasks", "updated": "2026-07-03"}]
            ),
        ), patch(
            "tools.builtins.google.tasks_tools._list_tasks_raw",
            new=AsyncMock(
                return_value=[
                    {"id": "1", "title": "Buy milk", "status": "needsAction"},
                    {"id": "2", "title": "Call Alex", "status": "needsAction"},
                ]
            ),
        ):
            result = await _search_tasks_handler({"query": "milk"})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["tasks"][0]["title"], "Buy milk")

    async def test_uncomplete_task_handler(self) -> None:
        mock_service = MagicMock()
        mock_service.tasks.return_value.patch.return_value.execute.return_value = {
            "id": "t1",
            "title": "Again",
            "status": "needsAction",
        }
        with patch(
            "tools.builtins.google.tasks_tools.get_tasks_service",
            new=AsyncMock(return_value=mock_service),
        ), patch(
            "tools.builtins.google.tasks_tools.resolve_tasklist_id",
            new=AsyncMock(return_value=("list1", None)),
        ):
            result = await _uncomplete_task_handler({"task_id": "t1"})
        self.assertFalse(result["completed"])

    async def test_create_tasklist_handler(self) -> None:
        mock_service = MagicMock()
        mock_service.tasklists.return_value.insert.return_value.execute.return_value = {
            "id": "new-list",
            "title": "Shopping",
        }
        with patch(
            "tools.builtins.google.tasks_tools.get_tasks_service",
            new=AsyncMock(return_value=mock_service),
        ):
            result = await _create_tasklist_handler({"title": "Shopping"})
        self.assertTrue(result["created"])
        self.assertEqual(result["tasklist"]["title"], "Shopping")

    async def test_delete_tasklist_requires_confirm(self) -> None:
        with self.assertRaises(ValueError):
            await _delete_tasklist_handler({"tasklist_id": "l1"})

    async def test_clear_completed_requires_confirm(self) -> None:
        with self.assertRaises(ValueError):
            await _clear_completed_handler({})


class TasksRegistryTests(unittest.TestCase):
    def test_t3_full_catalog_count(self) -> None:
        self.assertEqual(len(GOOGLE_TASKS_TOOLS), 24)

    def test_all_tools_have_tasks_tag(self) -> None:
        for tool in GOOGLE_TASKS_TOOLS:
            self.assertIn("google", tool.tags)
            self.assertIn("tasks", tool.tags)


if __name__ == "__main__":
    unittest.main()
