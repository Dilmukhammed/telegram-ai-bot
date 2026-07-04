import unittest

from agent.calendar_links import CalendarLinkCollector, finalize_calendar_text
from agent.reply_markup import build_reply_markup

EVENT_URL = (
    "https://www.google.com/calendar/event?eid=YWJjMTIzX3VzZXJAZ21haWwuY29t"
)
EVENT_URL_ALT = (
    "https://calendar.google.com/calendar/event?eid=YWJjMTIzX3VzZXJAZ21haWwuY29t"
)


class CalendarUrlTests(unittest.TestCase):
    def test_is_calendar_event_url(self) -> None:
        from tools.builtins.google.calendar_urls import is_calendar_event_url

        self.assertTrue(is_calendar_event_url(EVENT_URL))
        self.assertFalse(
            is_calendar_event_url("https://calendar.google.com/calendar/u/0/r/day/2026/7/3")
        )


class CalendarLinkCollectorTests(unittest.TestCase):
    def test_ingests_event_url_from_final_text(self) -> None:
        collector = CalendarLinkCollector()
        collector.ingest_from_text(f"Встреча создана.\n{EVENT_URL}")
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][0], "Открыть событие")
        self.assertEqual(buttons[0][1], EVENT_URL)

    def test_ingests_markdown_link_label(self) -> None:
        collector = CalendarLinkCollector()
        text = f"Открой [Team sync]({EVENT_URL})"
        collector.ingest_from_text(text)
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][0], "Team sync")

    def test_dedupes_same_event_by_eid(self) -> None:
        collector = CalendarLinkCollector()
        collector.ingest_from_text(f"{EVENT_URL}\n{EVENT_URL_ALT}")
        self.assertEqual(len(collector.buttons()), 1)

    def test_strip_removes_calendar_links(self) -> None:
        collector = CalendarLinkCollector()
        raw = (
            "Событие готово.\n"
            f"{EVENT_URL}\n"
            f"[Открыть]({EVENT_URL_ALT})"
        )
        collector.ingest_from_text(raw)
        cleaned = finalize_calendar_text(raw, collector)
        self.assertNotIn("google.com/calendar", cleaned)
        self.assertNotIn("calendar.google.com", cleaned)
        self.assertIn("Событие готово.", cleaned)

    def test_max_five_buttons(self) -> None:
        collector = CalendarLinkCollector()
        urls = "\n".join(
            f"https://www.google.com/calendar/event?eid=evt{i}" for i in range(8)
        )
        collector.ingest_from_text(urls)
        self.assertEqual(len(collector.buttons()), 5)

    def test_ingests_create_event_tool_result(self) -> None:
        collector = CalendarLinkCollector()
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.calendar.create_event",
              "result": {
                "created": true,
                "htmlLink": "https://www.google.com/calendar/event?eid=created1",
                "event": {
                  "id": "evt1",
                  "summary": "Standup",
                  "htmlLink": "https://www.google.com/calendar/event?eid=created1"
                }
              }
            }
            """
        )
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 0)
        details = collector.details_items()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].label, "Standup")

    def test_ingests_list_upcoming_events(self) -> None:
        collector = CalendarLinkCollector()
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.calendar.list_upcoming",
              "result": {
                "count": 2,
                "events": [
                  {
                    "id": "e1",
                    "summary": "Call with Alex",
                    "htmlLink": "https://www.google.com/calendar/event?eid=e1"
                  },
                  {
                    "id": "e2",
                    "summary": "Dentist",
                    "htmlLink": "https://www.google.com/calendar/event?eid=e2"
                  }
                ]
              }
            }
            """
        )
        labels = {link.label for link in collector.details_items()}
        self.assertEqual(labels, {"Call with Alex", "Dentist"})

    def test_combined_reply_markup_includes_calendar(self) -> None:
        markup = build_reply_markup(
            calendar_buttons=(("Standup", EVENT_URL),),
            maps_buttons=(("Map", "https://maps.example/m"),),
        )
        self.assertIsNotNone(markup)
        assert markup is not None
        labels = [btn.text for row in markup.inline_keyboard for btn in row]
        self.assertIn("Standup", labels)
        self.assertIn("Map", labels)


if __name__ == "__main__":
    unittest.main()
