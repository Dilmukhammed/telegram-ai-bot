import unittest

from agent.inline_button_layout import build_url_button_markup, layout_url_button_rows
from agent.reply_markup import build_reply_markup


class InlineButtonLayoutTests(unittest.TestCase):
    def test_one_button_single_row(self) -> None:
        rows = layout_url_button_rows((("A", "https://example.com/a"),))
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 1)

    def test_two_buttons_single_column(self) -> None:
        rows = layout_url_button_rows(
            (("A", "https://example.com/a"), ("B", "https://example.com/b"))
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 1)
        self.assertEqual(len(rows[1]), 1)

    def test_three_buttons_two_columns(self) -> None:
        rows = layout_url_button_rows(
            (
                ("A", "https://example.com/a"),
                ("B", "https://example.com/b"),
                ("C", "https://example.com/c"),
            )
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(len(rows[1]), 1)

    def test_combined_reply_markup_capped_at_five(self) -> None:
        markup = build_reply_markup(
            maps_buttons=(
                ("M1", "https://maps.example/1"),
                ("M2", "https://maps.example/2"),
                ("M3", "https://maps.example/3"),
            ),
            gmail_buttons=(
                ("G1", "https://mail.google.com/mail/u/0/#inbox/t1"),
                ("G2", "https://mail.google.com/mail/u/0/#inbox/t2"),
                ("G3", "https://mail.google.com/mail/u/0/#inbox/t3"),
            ),
        )
        self.assertIsNotNone(markup)
        assert markup is not None
        total = sum(len(row) for row in markup.inline_keyboard)
        self.assertEqual(total, 5)

    def test_build_url_button_markup_empty(self) -> None:
        self.assertIsNone(build_url_button_markup(()))


if __name__ == "__main__":
    unittest.main()
