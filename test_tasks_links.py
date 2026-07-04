import unittest

from agent.reply_markup import build_reply_markup
from agent.tasks_links import TasksLinkCollector, finalize_tasks_text

TASK_URL = "https://tasks.google.com/task/abc123"
TASK_URL_ALT = "https://tasks.google.com/embed/list/list1/tasks/abc123"


class TasksUrlTests(unittest.TestCase):
    def test_is_tasks_task_url(self) -> None:
        from tools.builtins.google.tasks_urls import is_tasks_task_url

        self.assertTrue(is_tasks_task_url(TASK_URL))
        self.assertTrue(is_tasks_task_url(TASK_URL_ALT))
        self.assertFalse(is_tasks_task_url("https://tasks.google.com/"))

    def test_parse_task_id_from_url(self) -> None:
        from tools.builtins.google.tasks_urls import parse_task_id_from_url

        self.assertEqual(parse_task_id_from_url(TASK_URL), "abc123")
        self.assertEqual(parse_task_id_from_url(TASK_URL_ALT), "abc123")


class TasksLinkCollectorTests(unittest.TestCase):
    def test_ingests_task_url_from_final_text(self) -> None:
        collector = TasksLinkCollector()
        collector.ingest_from_text(f"Задача создана.\n{TASK_URL}")
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][0], "Открыть задачу")
        self.assertEqual(buttons[0][1], TASK_URL)

    def test_ingests_markdown_link_label(self) -> None:
        collector = TasksLinkCollector()
        text = f"Открой [Купить молоко]({TASK_URL})"
        collector.ingest_from_text(text)
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][0], "Купить молоко")

    def test_dedupes_same_task_by_id(self) -> None:
        collector = TasksLinkCollector()
        collector.ingest_from_text(f"{TASK_URL}\n{TASK_URL_ALT}")
        self.assertEqual(len(collector.buttons()), 1)

    def test_strip_removes_tasks_links(self) -> None:
        collector = TasksLinkCollector()
        raw = (
            "Задача готова.\n"
            f"{TASK_URL}\n"
            f"[Открыть]({TASK_URL_ALT})"
        )
        collector.ingest_from_text(raw)
        cleaned = finalize_tasks_text(raw, collector)
        self.assertNotIn("tasks.google.com", cleaned)
        self.assertIn("Задача готова.", cleaned)

    def test_max_five_buttons(self) -> None:
        collector = TasksLinkCollector()
        urls = "\n".join(f"https://tasks.google.com/task/t{i}" for i in range(8))
        collector.ingest_from_text(urls)
        self.assertEqual(len(collector.buttons()), 5)

    def test_ingests_create_task_tool_result(self) -> None:
        collector = TasksLinkCollector()
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.tasks.create_task",
              "result": {
                "created": true,
                "webViewLink": "https://tasks.google.com/task/new1",
                "task": {
                  "id": "new1",
                  "title": "Buy milk",
                  "webViewLink": "https://tasks.google.com/task/new1"
                }
              }
            }
            """
        )
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 0)
        details = collector.details_items()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].label, "Buy milk")

    def test_ingests_list_today_tasks(self) -> None:
        collector = TasksLinkCollector()
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.tasks.list_today",
              "result": {
                "count": 2,
                "tasks": [
                  {
                    "id": "t1",
                    "title": "Call Alex",
                    "webViewLink": "https://tasks.google.com/task/t1"
                  },
                  {
                    "id": "t2",
                    "title": "Pay rent",
                    "webViewLink": "https://tasks.google.com/task/t2"
                  }
                ]
              }
            }
            """
        )
        labels = {link.label for link in collector.details_items()}
        self.assertEqual(labels, {"Call Alex", "Pay rent"})

    def test_ingests_assignment_link(self) -> None:
        collector = TasksLinkCollector()
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.tasks.get_task",
              "result": {
                "task": {
                  "id": "assigned1",
                  "title": "Review PR",
                  "assignmentInfo": {
                    "linkToTask": "https://tasks.google.com/task/assigned1"
                  }
                }
              }
            }
            """
        )
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 0)
        details = collector.details_items()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].label, "Review PR")

    def test_combined_reply_markup_includes_tasks(self) -> None:
        markup = build_reply_markup(
            tasks_buttons=(("Buy milk", TASK_URL),),
            calendar_buttons=(("Standup", "https://calendar.google.com/event?eid=x"),),
        )
        self.assertIsNotNone(markup)
        assert markup is not None
        labels = [btn.text for row in markup.inline_keyboard for btn in row]
        self.assertIn("Buy milk", labels)
        self.assertIn("Standup", labels)


if __name__ == "__main__":
    unittest.main()
