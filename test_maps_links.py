import unittest

from agent.maps_links import (
    MapsLinkCollector,
    build_maps_reply_markup,
    finalize_maps_text,
)
from rich_format import linkify_google_maps_urls, prepare_telegram_rich_markdown
from tools.builtins.google.maps_urls import build_directions_url, group_key_for_route


class MapsUrlBuilderTests(unittest.TestCase):
    def test_build_directions_url_uses_urlencode(self) -> None:
        url = build_directions_url(
            "Samarkand Darvoza, Tashkent",
            "Turin Polytechnic University in Tashkent",
            travel_mode="DRIVE",
        )
        self.assertTrue(url.startswith("https://www.google.com/maps/dir/?api=1&"))
        self.assertIn("origin=Samarkand+Darvoza%2C+Tashkent", url)
        self.assertIn("destination=Turin+Polytechnic+University+in+Tashkent", url)
        self.assertIn("travelmode=driving", url)
        self.assertNotIn("&amp;", url)

    def test_build_directions_url_with_coordinates(self) -> None:
        url = build_directions_url(
            "41.3115769,69.2233103",
            "41.3507034,69.2210652",
            travel_mode="DRIVE",
        )
        self.assertIn("origin=41.3115769%2C69.2233103", url)
        self.assertIn("destination=41.3507034%2C69.2210652", url)


class MapsRouteGroupKeyTests(unittest.TestCase):
    def test_group_key_includes_origin_and_destination(self) -> None:
        url_a = "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving"
        url_b = "https://www.google.com/maps/dir/?api=1&origin=A2&destination=B2&travelmode=driving"
        self.assertNotEqual(group_key_for_route(url_a), group_key_for_route(url_b))

    def test_group_key_same_for_same_endpoints(self) -> None:
        url_a = "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving"
        url_b = "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving&extra=1"
        self.assertEqual(group_key_for_route(url_a), group_key_for_route(url_b))


class MapsLinkCollectorTests(unittest.TestCase):
    def test_ingests_route_tool_result(self) -> None:
        collector = MapsLinkCollector()
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.maps.travel_time",
              "result": {
                "origin": "A",
                "destination": "B",
                "google_maps_uri": "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving"
              }
            }
            """
        )
        self.assertEqual(len(collector.items), 1)
        buttons = collector.buttons()
        self.assertEqual(buttons[0][0], "На машине")
        self.assertIn("&origin=A", buttons[0][1])
        self.assertNotIn("&amp;", buttons[0][1])

    def test_ingests_yandex_transit_tool_result(self) -> None:
        collector = MapsLinkCollector()
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.maps.directions",
              "result": {
                "origin": "Южный вокзал",
                "destination": "Тинчлик",
                "travel_mode": "TRANSIT",
                "google_maps_uri": "https://yandex.ru/maps/?rtext=%D0%AE%D0%B6%D0%BD%D1%8B%D0%B9+%D0%B2%D0%BE%D0%BA%D0%B7%D0%B0%D0%BB~%D0%A2%D0%B8%D0%BD%D1%87%D0%BB%D0%B8%D0%BA&rtt=mt"
              }
            }
            """
        )
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][0], "На общественном транспорте")

    def test_ingests_street_view_tool_result(self) -> None:
        collector = MapsLinkCollector()
        url = (
            "https://maps.googleapis.com/maps/api/streetview?"
            "location=48.8583701%2C2.2944813&size=640x640&heading=315&pitch=20&fov=90&key=test"
        )
        collector.ingest_tool_result_json(
            f"""
            {{
              "ok": true,
              "tool_name": "google.maps.street_view_image",
              "result": {{
                "lat": 48.8583701,
                "lng": 2.2944813,
                "image_url": "{url}"
              }}
            }}
            """
        )
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][0], "Панорама")
        self.assertIn("size=640x640", buttons[0][1])
        self.assertNotIn("&amp;", buttons[0][1])

    def test_ingests_static_map_tool_result(self) -> None:
        collector = MapsLinkCollector()
        url = "https://maps.googleapis.com/maps/api/staticmap?center=Paris&zoom=14&size=640x640&key=test"
        collector.ingest_tool_result_json(
            f"""
            {{
              "ok": true,
              "tool_name": "google.maps.static_map",
              "result": {{
                "center": "Paris",
                "map_url": "{url}"
              }}
            }}
            """
        )
        buttons = collector.buttons()
        self.assertEqual(buttons[0][0], "Снимок карты")

    def test_finalize_strips_street_view_amp_url(self) -> None:
        collector = MapsLinkCollector()
        url = (
            "https://maps.googleapis.com/maps/api/streetview?"
            "location=48.8583701%2C2.2944813&size=640x640&heading=315&pitch=20&fov=90&key=test"
        )
        collector.add(url, tool_name="google.maps.street_view_image")
        broken = (
            "Панорама:\n"
            f"[Открыть](https://maps.googleapis.com/maps/api/streetview?"
            "location=48.8583701%2C2.2944813&amp;size=640x640&amp;heading=315&amp;pitch=20&amp;fov=90&amp;key=test)"
        )
        reply = finalize_maps_text(broken, collector)
        self.assertNotIn("maps.googleapis.com", reply)
        self.assertIn("Панорама:", reply)

    def test_build_maps_reply_markup(self) -> None:
        markup = build_maps_reply_markup(
            (("Route", "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving"),)
        )
        self.assertIsNotNone(markup)
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.text, "Route")
        self.assertIn("&origin=A", button.url)

    def test_text_promotes_same_yandex_url_after_tool_ingest(self) -> None:
        collector = MapsLinkCollector()
        yandex_url = (
            "https://yandex.ru/maps/?rtext=%D0%AE%D0%B6%D0%BD%D1%8B%D0%B9+%D0%B2%D0%BE%D0%BA%D0%B7%D0%B0%D0%BB~"
            "%D0%A2%D0%B8%D0%BD%D1%87%D0%BB%D0%B8%D0%BA&rtt=mt"
        )
        collector.ingest_tool_result_json(
            """
            {
              "ok": true,
              "tool_name": "google.maps.directions",
              "result": {
                "origin": "A",
                "destination": "B",
                "travel_mode": "TRANSIT",
                "url": "%s"
              }
            }
            """
            % yandex_url
        )
        collector.ingest_from_text(f"Маршрут: [На ОТ]({yandex_url})")
        self.assertEqual(len(collector.buttons()), 1)
        self.assertEqual(collector.details_items(), [])
        self.assertEqual(collector.buttons()[0][0], "На ОТ")

    def test_keeps_different_route_endpoints_same_travel_mode(self) -> None:
        collector = MapsLinkCollector()
        collector.add(
            "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving",
        )
        collector.add(
            "https://www.google.com/maps/dir/?api=1&origin=A2&destination=B2&travelmode=driving",
        )
        self.assertEqual(len(collector.items), 2)

    def test_dedupes_same_origin_destination_same_travel_mode(self) -> None:
        collector = MapsLinkCollector()
        collector.add(
            "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving",
        )
        collector.add(
            "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving&waypoints=C",
        )
        self.assertEqual(len(collector.items), 1)
        self.assertIn("origin=A", collector.items[0].url)

    def test_buttons_keep_different_travel_modes(self) -> None:
        collector = MapsLinkCollector()
        collector.add(
            "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving",
        )
        collector.add(
            "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=transit",
            origin="Сквер Амира Темура, Ташкент",
            destination="Туринский политех, Ташкент",
        )
        buttons = collector.buttons()
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0][0], "На машине")
        self.assertIn("google.com/maps", buttons[0][1])
        self.assertEqual(buttons[1][0], "На общественном транспорте")
        self.assertIn("yandex.", buttons[1][1])
        self.assertIn("rtt=mt", buttons[1][1])

    def test_finalize_maps_text_strips_yandex_transit_link(self) -> None:
        collector = MapsLinkCollector()
        yandex_url = (
            "https://yandex.ru/maps/?rtext=%D0%AE%D0%B6%D0%BD%D1%8B%D0%B9+%D0%B2%D0%BE%D0%BA%D0%B7%D0%B0%D0%BB~"
            "%D0%A2%D0%B8%D0%BD%D1%87%D0%BB%D0%B8%D0%BA&rtt=mt"
        )
        collector.add(yandex_url, travel_mode="TRANSIT", origin="A", destination="B")
        reply = finalize_maps_text(
            f"Маршрут готов.\n[Посмотреть маршрут на ОТ]({yandex_url})",
            collector,
        )
        self.assertEqual(reply, "Маршрут готов.")
        self.assertNotIn("yandex.", reply)

    def test_finalize_maps_text_strips_model_links(self) -> None:
        collector = MapsLinkCollector()
        collector.add(
            "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving",
            label="Route",
        )
        reply = finalize_maps_text(
            "Done.\n[Route](https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving)",
            collector,
        )
        self.assertEqual(reply, "Done.")
        self.assertNotIn("google.com/maps", reply)


class RichFormatLinkifyTests(unittest.TestCase):
    def test_linkify_broken_amp_maps_url(self) -> None:
        broken = (
            "https://www.google.com/maps/dir/?api=1&amp;origin=A&amp;"
            "destination=B&amp;travelmode=driving"
        )
        result = prepare_telegram_rich_markdown(broken)
        self.assertIn("[Открыть в Google Maps](https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving)", result)
        self.assertNotIn("Route: https://", result)

    def test_linkify_model_html_anchor(self) -> None:
        text = (
            '<a href="https://www.google.com/maps/dir/?api=1&amp;origin=A&amp;'
            'destination=B&amp;travelmode=driving">Ссылка</a>'
        )
        result = prepare_telegram_rich_markdown(text)
        self.assertIn("[Ссылка](https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving)", result)
        self.assertNotIn("&amp;", result)

    def test_strip_removes_model_maps_links(self) -> None:
        from rich_format import strip_google_maps_urls

        text = (
            "Маршрут готов.\n"
            "[Ссылка](https://www.google.com/maps/dir/?api=1&amp;origin=A&amp;destination=B&amp;travelmode=driving)"
        )
        stripped = strip_google_maps_urls(text)
        self.assertNotIn("google.com/maps", stripped)
        self.assertIn("Маршрут готов.", stripped)


if __name__ == "__main__":
    unittest.main()
