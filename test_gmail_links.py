import unittest

from agent.gmail_links import GmailLinkCollector, finalize_gmail_text
from agent.reply_markup import build_reply_markup
from tools.builtins.google.gmail_urls import build_search_url, build_thread_url


class GmailUrlTests(unittest.TestCase):
    def test_build_thread_url(self) -> None:
        url = build_thread_url("FMfcgzABC123")
        self.assertEqual(url, "https://mail.google.com/mail/u/0/#inbox/FMfcgzABC123")

    def test_build_search_url(self) -> None:
        url = build_search_url("from:user@example.com is:unread")
        self.assertIn("#search/", url)
        self.assertIn("from%3Auser%40example.com", url)


class GmailLinkCollectorTests(unittest.TestCase):
    def test_ingests_thread_url_from_final_text(self) -> None:
        collector = GmailLinkCollector()
        text = (
            "Нашёл счёт за июль.\n"
            "https://mail.google.com/mail/u/0/#inbox/t1"
        )
        collector.ingest_from_text(text)
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][1], build_thread_url("t1"))

    def test_ingests_markdown_link_label(self) -> None:
        collector = GmailLinkCollector()
        text = "Открой [Invoice July](https://mail.google.com/mail/u/0/#inbox/t1)"
        collector.ingest_from_text(text)
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][0], "Invoice July")

    def test_search_url_from_final_text(self) -> None:
        collector = GmailLinkCollector()
        url = build_search_url("from:bank@example.com")
        collector.ingest_from_text(f"Вот поиск: {url}")
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertIn("Поиск:", buttons[0][0])

    def test_dedupes_same_thread(self) -> None:
        collector = GmailLinkCollector()
        url = build_thread_url("t1")
        collector.ingest_from_text(f"{url}\n{url}")
        self.assertEqual(len(collector.buttons()), 1)

    def test_strip_removes_gmail_links(self) -> None:
        collector = GmailLinkCollector()
        raw = (
            "Письмо готово.\n"
            "https://mail.google.com/mail/u/0/#inbox/t999\n"
            "[Открыть](https://mail.google.com/mail/u/0/#inbox/t888)"
        )
        collector.ingest_from_text(raw)
        cleaned = finalize_gmail_text(raw, collector)
        self.assertNotIn("mail.google.com", cleaned)
        self.assertIn("Письмо готово.", cleaned)

    def test_max_five_buttons(self) -> None:
        collector = GmailLinkCollector()
        urls = "\n".join(build_thread_url(f"t{i}") for i in range(8))
        collector.ingest_from_text(urls)
        self.assertEqual(len(collector.buttons()), 5)

    def test_ingests_get_thread_tool_result(self) -> None:
        collector = GmailLinkCollector()
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.gmail.get_thread",
              "result": {
                "id": "t1",
                "snippet": "Invoice attached",
                "messages": [{
                  "thread_id": "t1",
                  "subject": "Invoice July",
                  "snippet": "Please review"
                }]
              }
            }
            """
        )
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 0)
        details = collector.details_items()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].label, "Invoice July")
        self.assertEqual(details[0].url, build_thread_url("t1"))

    def test_combined_reply_markup_two_buttons(self) -> None:
        markup = build_reply_markup(
            maps_buttons=(("На машине", "https://maps.example/a"),),
            gmail_buttons=(("Invoice", "https://mail.google.com/mail/u/0/#inbox/t1"),),
        )
        self.assertIsNotNone(markup)
        assert markup is not None
        self.assertEqual(len(markup.inline_keyboard), 2)
        self.assertEqual(len(markup.inline_keyboard[0]), 1)
        self.assertEqual(len(markup.inline_keyboard[1]), 1)


if __name__ == "__main__":
    unittest.main()
