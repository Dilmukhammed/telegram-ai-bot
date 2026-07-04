import unittest

from rich_format import (
    convert_gfm_tables_to_html,
    fix_url_amp_entities,
    prepare_telegram_rich_markdown,
    strip_maps_route_urls,
)


class RichFormatTests(unittest.TestCase):
    def test_converts_gfm_table_to_html(self) -> None:
        source = """Intro

| Feature | Status |
|:--------|:------:|
| Tables  | **ok** |
| Math    | ok |

Tail"""
        result = prepare_telegram_rich_markdown(source)
        self.assertIn("<table bordered striped>", result)
        self.assertIn('<th align="left"><b>Feature</b></th>', result)
        self.assertIn('<th align="center"><b>Status</b></th>', result)
        self.assertIn("<b>ok</b>", result)
        self.assertNotIn("|:--------|", result)

    def test_leaves_non_table_text(self) -> None:
        text = "Just text\n\n$x^2$"
        self.assertEqual(prepare_telegram_rich_markdown(text), text)

    def test_fixes_amp_in_google_maps_url(self) -> None:
        broken = (
            "https://www.google.com/maps/dir/?api=1&amp;origin=Foo&amp;"
            "destination=Bar&amp;travelmode=driving"
        )
        fixed = fix_url_amp_entities(broken)
        self.assertIn("&origin=Foo", fixed)
        self.assertNotIn("&amp;", fixed)

    def test_fixes_amp_in_markdown_link(self) -> None:
        broken = "[Maps](https://www.google.com/maps/dir/?api=1&amp;origin=Foo)"
        fixed = fix_url_amp_entities(broken)
        self.assertIn("](https://www.google.com/maps/dir/?api=1&origin=Foo)", fixed)

    def test_prepare_fixes_model_escaped_maps_url(self) -> None:
        broken = (
            "Route: https://www.google.com/maps/dir/?api=1&amp;origin=A&amp;"
            "destination=B&amp;travelmode=driving"
        )
        result = prepare_telegram_rich_markdown(broken)
        self.assertIn("[Открыть в Google Maps](https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving)", result)

    def test_telegram_href_keeps_literal_ampersands(self) -> None:
        from rich_format import telegram_href

        url = "https://www.google.com/maps/dir/?api=1&origin=A&destination=B"
        self.assertEqual(telegram_href(url), url)
        self.assertNotIn("&amp;", telegram_href("https://x?a=1&amp;b=2"))

    def test_fixes_model_html_maps_anchor(self) -> None:
        broken = (
            '<a href="https://www.google.com/maps/dir/?api=1&amp;origin=A&amp;'
            'destination=B&amp;travelmode=driving">Maps</a>'
        )
        result = prepare_telegram_rich_markdown(broken)
        self.assertIn("[Maps](https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving)", result)
        self.assertNotIn("&amp;", result)

    def test_strip_yandex_route_markdown_link(self) -> None:
        yandex_url = "https://yandex.ru/maps/?rtext=A~B&rtt=mt"
        text = f"Готово.\n[Посмотреть маршрут на ОТ]({yandex_url})"
        stripped = strip_maps_route_urls(text)
        self.assertEqual(stripped, "Готово.")
        self.assertNotIn("yandex.", stripped)

    def test_strip_yandex_route_bare_url(self) -> None:
        yandex_url = "https://yandex.ru/maps/?rtext=A~B&rtt=mt"
        stripped = strip_maps_route_urls(f"Ссылка: {yandex_url}")
        self.assertEqual(stripped, "Ссылка:")

    def test_table_cell_preserves_url_ampersands(self) -> None:
        source = """| Name | Link |
|------|------|
| Route | https://www.google.com/maps/dir/?api=1&origin=A&destination=B |"""
        result = prepare_telegram_rich_markdown(source)
        self.assertIn('<a href="https://www.google.com/maps/dir/?api=1&origin=A&destination=B">', result)


if __name__ == "__main__":
    unittest.main()
