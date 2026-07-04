import os
import unittest

from agent.maps_link_providers import resolve_route_button_url
from tools.builtins.yandex.maps_urls import build_yandex_route_url


class YandexMapsUrlTests(unittest.TestCase):
    def test_build_yandex_transit_url(self) -> None:
        url = build_yandex_route_url(
            "Сквер Амира Темура, Ташкент",
            "Туринский политех, Ташкент",
        )
        self.assertTrue(url.startswith("https://yandex.ru/maps/?"))
        self.assertIn("rtt=mt", url)
        self.assertIn("rtext=", url)

    def test_resolve_transit_to_yandex_by_default(self) -> None:
        google_url = (
            "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=transit"
        )
        resolved = resolve_route_button_url(
            google_url,
            origin="Point A",
            destination="Point B",
            travel_mode="TRANSIT",
            transit_link_provider="yandex",
        )
        self.assertIn("yandex.", resolved)
        self.assertIn("rtt=mt", resolved)

    def test_resolve_transit_stays_google_when_configured(self) -> None:
        google_url = (
            "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=transit"
        )
        resolved = resolve_route_button_url(
            google_url,
            origin="Point A",
            destination="Point B",
            travel_mode="TRANSIT",
            transit_link_provider="google",
        )
        self.assertIn("google.com/maps", resolved)
        self.assertNotIn("yandex.", resolved)

    def test_resolve_driving_unaffected(self) -> None:
        google_url = (
            "https://www.google.com/maps/dir/?api=1&origin=A&destination=B&travelmode=driving"
        )
        resolved = resolve_route_button_url(
            google_url,
            origin="Point A",
            destination="Point B",
            travel_mode="DRIVE",
            transit_link_provider="yandex",
        )
        self.assertEqual(resolved, google_url)


if __name__ == "__main__":
    unittest.main()
