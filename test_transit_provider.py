from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MAPS_TRANSIT_LINK_PROVIDER", "yandex")

from tools.builtins.google.transit_provider import apply_transit_route_overlay
from tools.builtins.yandex.maps_urls import build_yandex_route_url, format_yandex_rtext_point
from tools.builtins.yandex.route_cache import clear_yandex_route_cache


class TransitProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clear_yandex_route_cache()

    async def test_transit_overlay_uses_geocoded_coords(self) -> None:
        with patch(
            "tools.builtins.google.maps_client.geocode",
            new=AsyncMock(
                side_effect=[
                    {"results": [{"lat": 41.221, "lng": 69.221}]},
                    {"results": [{"lat": 41.350, "lng": 69.290}]},
                ]
            ),
        ):
            result = await apply_transit_route_overlay(
                {
                    "origin": "Yuzhny Vokzal, Tashkent",
                    "destination": "Tinchlik metro station, Tashkent",
                    "travel_mode": "TRANSIT",
                    "count": 0,
                }
            )

        rtext = f"{format_yandex_rtext_point(41.221, 69.221)}~{format_yandex_rtext_point(41.350, 69.290)}"
        self.assertIn(rtext.replace(",", "%2C"), result["google_maps_uri"])
        self.assertNotIn("Yuzhny", result["google_maps_uri"])


class YandexRouteUrlTests(unittest.TestCase):
    def test_build_with_coordinates(self) -> None:
        url = build_yandex_route_url(
            "A",
            "B",
            origin_lat=41.221,
            origin_lng=69.221,
            dest_lat=41.350,
            dest_lng=69.290,
        )
        self.assertIn("rtext=", url)
        self.assertIn("41.221", url)
        self.assertIn("69.221", url)
        self.assertIn("41.35", url)
        self.assertIn("69.29", url)
        self.assertIn("rtt=mt", url)
