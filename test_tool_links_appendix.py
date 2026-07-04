import unittest

from agent.calendar_links import CalendarLinkCollector
from agent.drive_links import DriveLinkCollector
from agent.gmail_links import GmailLinkCollector
from agent.maps_links import MapsLinkCollector
from agent.tasks_links import TasksLinkCollector
from agent.tool_links_appendix import append_tool_links_appendix


class ToolLinksAppendixTests(unittest.TestCase):
    def test_tool_links_go_to_details_not_buttons(self) -> None:
        calendar = CalendarLinkCollector()
        calendar.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.calendar.list_upcoming",
              "result": {
                "events": [
                  {
                    "id": "e1",
                    "summary": "Standup",
                    "htmlLink": "https://www.google.com/calendar/event?eid=e1"
                  }
                ]
              }
            }
            """
        )
        self.assertEqual(calendar.buttons(), ())
        self.assertEqual(len(calendar.details_items()), 1)

    def test_final_text_link_becomes_button(self) -> None:
        calendar = CalendarLinkCollector()
        url = "https://www.google.com/calendar/event?eid=final1"
        calendar.ingest_from_text(f"Встреча: {url}")
        self.assertEqual(len(calendar.buttons()), 1)
        self.assertEqual(calendar.details_items(), [])

    def test_appendix_renders_collapsed_links(self) -> None:
        calendar = CalendarLinkCollector()
        calendar.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.calendar.create_event",
              "result": {
                "event": {
                  "summary": "Dentist",
                  "htmlLink": "https://www.google.com/calendar/event?eid=d1"
                }
              }
            }
            """
        )
        reply = append_tool_links_appendix(
            "Готово.",
            maps_links=MapsLinkCollector(),
            gmail_links=GmailLinkCollector(),
            drive_links=DriveLinkCollector(),
            calendar_links=calendar,
            tasks_links=TasksLinkCollector(),
        )
        self.assertIn("<details>", reply)
        self.assertIn("<summary>Ссылки</summary>", reply)
        self.assertIn("calendar/event", reply)


if __name__ == "__main__":
    unittest.main()
