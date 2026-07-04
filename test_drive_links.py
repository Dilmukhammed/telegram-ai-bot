import unittest
from agent.drive_links import DriveLinkCollector, finalize_drive_text
from agent.inline_button_layout import layout_url_button_rows
from agent.reply_markup import build_reply_markup
from agent.drive_button_urls import DRIVE_PAIR_WHEN_MORE_THAN
from tools.builtins.google.drive_urls import is_drive_url, parse_file_id_from_url


class DriveUrlTests(unittest.TestCase):
    def test_parse_file_id_from_drive_view_url(self) -> None:
        url = "https://drive.google.com/file/d/abc123XYZ/view?usp=drivesdk"
        self.assertEqual(parse_file_id_from_url(url), "abc123XYZ")

    def test_parse_file_id_from_docs_url(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/sheetId123/edit"
        self.assertEqual(parse_file_id_from_url(url), "sheetId123")

    def test_is_drive_url(self) -> None:
        self.assertTrue(is_drive_url("https://drive.google.com/drive/folders/f1"))
        self.assertFalse(is_drive_url("https://mail.google.com/mail/u/0/"))


class DriveLinkCollectorTests(unittest.TestCase):
    def test_ingests_url_from_final_text(self) -> None:
        collector = DriveLinkCollector()
        url = "https://drive.google.com/file/d/file1/view"
        collector.ingest_from_text(f"Файл: {url}")
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][1], url)

    def test_ingests_markdown_label(self) -> None:
        collector = DriveLinkCollector()
        text = "[Балансы API](https://docs.google.com/spreadsheets/d/abc/edit)"
        collector.ingest_from_text(text)
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][0], "Балансы API")

    def test_spreadsheet_url_gets_smart_label(self) -> None:
        from tools.builtins.google.drive_urls import label_for_drive_url

        url = "https://docs.google.com/spreadsheets/d/abc/edit"
        self.assertEqual(label_for_drive_url(url), "Открыть таблицу")

    def test_spreadsheet_url_with_name(self) -> None:
        from tools.builtins.google.drive_urls import label_for_drive_url

        url = "https://docs.google.com/spreadsheets/d/abc/edit"
        self.assertEqual(label_for_drive_url(url, name="Budget Q3"), "Budget Q3")

    def test_ingests_spreadsheet_tool_result(self) -> None:
        collector = DriveLinkCollector()
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.sheets.create_spreadsheet",
              "result": {
                "spreadsheet": {
                  "spreadsheet_id": "abc123",
                  "title": "Budget 2026",
                  "url": "https://docs.google.com/spreadsheets/d/abc123/edit"
                }
              }
            }
            """
        )
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 0)
        details = collector.details_items()
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].label, "Budget 2026")
        self.assertIn("/spreadsheets/d/abc123", details[0].url)

    def test_ingests_drive_search_files(self) -> None:
        collector = DriveLinkCollector()
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.drive.search_files",
              "result": {
                "count": 1,
                "files": [{
                  "name": "Report.pdf",
                  "mime_type": "application/pdf",
                  "web_view_link": "https://drive.google.com/file/d/pdf1/view"
                }]
              }
            }
            """
        )
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 0)
        details = collector.details_items()
        self.assertEqual(details[0].label, "Report.pdf")

    def test_bare_spreadsheet_url_in_final_text(self) -> None:
        collector = DriveLinkCollector()
        url = "https://docs.google.com/spreadsheets/d/sheetId123/edit"
        collector.ingest_from_text(url)
        buttons = collector.buttons()
        self.assertEqual(buttons[0][0], "Открыть таблицу")

    def test_dedupes_same_file_id(self) -> None:
        collector = DriveLinkCollector()
        collector.add("https://drive.google.com/file/d/same/view")
        collector.add("https://docs.google.com/document/d/same/edit")
        self.assertEqual(len(collector.details_items()), 1)

    def test_strip_removes_drive_links(self) -> None:
        collector = DriveLinkCollector()
        raw = (
            "Готово.\n"
            "https://drive.google.com/file/d/x/view\n"
            "[Sheet](https://docs.google.com/spreadsheets/d/y/edit)"
        )
        collector.ingest_from_text(raw)
        cleaned = finalize_drive_text(raw, collector)
        self.assertNotIn("drive.google.com", cleaned)
        self.assertNotIn("docs.google.com", cleaned)
        self.assertIn("Готово.", cleaned)

    def test_max_five_buttons(self) -> None:
        collector = DriveLinkCollector()
        urls = "\n".join(
            f"https://drive.google.com/file/d/f{i}/view" for i in range(8)
        )
        collector.ingest_from_text(urls)
        self.assertEqual(len(collector.buttons()), 5)


class DriveButtonLayoutTests(unittest.TestCase):
    def test_two_drive_buttons_one_row(self) -> None:
        rows = layout_url_button_rows(
            (("A", "https://drive.google.com/a"), ("B", "https://drive.google.com/b")),
            pair_when_more_than=DRIVE_PAIR_WHEN_MORE_THAN,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 2)

    def test_three_drive_buttons_two_rows(self) -> None:
        rows = layout_url_button_rows(
            (
                ("A", "https://drive.google.com/a"),
                ("B", "https://drive.google.com/b"),
                ("C", "https://drive.google.com/c"),
            ),
            pair_when_more_than=DRIVE_PAIR_WHEN_MORE_THAN,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(len(rows[1]), 1)

    def test_combined_markup_appends_drive_rows(self) -> None:
        markup = build_reply_markup(
            maps_buttons=(("Map", "https://maps.example/m"),),
            drive_buttons=(
                ("File 1", "https://drive.google.com/f1"),
                ("File 2", "https://drive.google.com/f2"),
                ("File 3", "https://drive.google.com/f3"),
            ),
        )
        self.assertIsNotNone(markup)
        assert markup is not None
        self.assertEqual(len(markup.inline_keyboard), 3)
        self.assertEqual(len(markup.inline_keyboard[0]), 1)
        self.assertEqual(len(markup.inline_keyboard[1]), 2)
        self.assertEqual(len(markup.inline_keyboard[2]), 1)


if __name__ == "__main__":
    unittest.main()
