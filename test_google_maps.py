import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config import google_maps_configured
from tools.builtins.google.errors import GoogleMapsNotConfiguredError
from tools.builtins.google.maps_client import (
    geocode,
    geocode_batch,
    require_maps_configured,
    reverse_geocode,
)
from tools.builtins.google.maps_misc import (
    elevation,
    static_map,
    street_view_image,
    street_view_metadata,
    timezone,
)
from tools.builtins.google.maps_places import places_text_search
from tools.builtins.google.maps_routes import compute_routes, travel_time
from tools.builtins.google.maps_serialize import (
    compact_geocode_response,
    compact_place,
    compact_route_response,
    format_duration,
    parse_duration_seconds,
)
from tools.builtins.google.maps_tools import _build_maps_link


class GoogleMapsSerializeTests(unittest.TestCase):
    def test_compact_geocode_response(self) -> None:
        payload = compact_geocode_response(
            {
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "Tashkent, Uzbekistan",
                        "place_id": "ChIJtest",
                        "geometry": {
                            "location": {"lat": 41.2995, "lng": 69.2401},
                            "location_type": "APPROXIMATE",
                        },
                        "types": ["locality", "political"],
                    }
                ],
            },
            query="Tashkent",
        )
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["lat"], 41.2995)


class GoogleMapsLinkTests(unittest.TestCase):
    def test_search_link(self) -> None:
        result = _build_maps_link({"link_type": "search", "query": "Chorsu Bazaar"})
        self.assertIn("google.com/maps/search/", result["url"])
        self.assertIn("Chorsu", result["url"])

    def test_directions_link_transit(self) -> None:
        result = _build_maps_link(
            {
                "link_type": "directions",
                "origin": "Tashkent Airport",
                "destination": "Chorsu Bazaar",
                "travel_mode": "TRANSIT",
            }
        )
        self.assertIn("google.com/maps", result["url"])
        self.assertIn("travelmode=transit", result["url"])
        self.assertEqual(result["travel_mode"], "TRANSIT")

    def test_place_link(self) -> None:
        result = _build_maps_link(
            {
                "link_type": "place",
                "place_id": "ChIJtest",
                "query": "Coffee",
            }
        )
        self.assertIn("query_place_id=ChIJtest", result["url"])


class GoogleMapsClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_require_maps_configured_raises_without_key(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}, clear=False):
            with self.assertRaises(GoogleMapsNotConfiguredError):
                require_maps_configured()

    async def test_geocode_success(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "OK",
            "results": [
                {
                    "formatted_address": "Tashkent, Uzbekistan",
                    "place_id": "ChIJtest",
                    "geometry": {
                        "location": {"lat": 41.2995, "lng": 69.2401},
                        "location_type": "APPROXIMATE",
                    },
                    "types": ["locality"],
                }
            ],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            with patch("tools.builtins.google.maps_client._get_client", return_value=mock_client):
                result = await geocode("Tashkent")

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["formatted_address"], "Tashkent, Uzbekistan")
        mock_client.get.assert_awaited_once()
        called_url = mock_client.get.await_args.args[0]
        self.assertIn("address=Tashkent", called_url)
        self.assertIn("key=test-key", called_url)
        self.assertIn("language=ru", called_url)
        self.assertIn("region=uz", called_url)

    async def test_reverse_geocode_success(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "OK",
            "results": [
                {
                    "formatted_address": "Tashkent, Uzbekistan",
                    "place_id": "ChIJtest",
                    "geometry": {
                        "location": {"lat": 41.2995, "lng": 69.2401},
                        "location_type": "APPROXIMATE",
                    },
                    "types": ["locality"],
                }
            ],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            with patch("tools.builtins.google.maps_client._get_client", return_value=mock_client):
                result = await reverse_geocode(41.2995, 69.2401)

        self.assertEqual(result["query"], "41.2995,69.2401")
        self.assertEqual(result["count"], 1)
        called_url = mock_client.get.await_args.args[0]
        self.assertIn("latlng=41.2995%2C69.2401", called_url)

    async def test_geocode_batch_limits(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            with patch(
                "tools.builtins.google.maps_client.geocode",
                new=AsyncMock(return_value={"count": 1, "results": []}),
            ) as mock_geocode:
                result = await geocode_batch(["A", "B"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(mock_geocode.await_count, 2)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            with self.assertRaisesRegex(ValueError, "at most 10"):
                await geocode_batch([str(index) for index in range(11)])


class GoogleMapsPlacesSerializeTests(unittest.TestCase):
    def test_compact_place(self) -> None:
        place = compact_place(
            {
                "id": "places/ChIJtest",
                "displayName": {"text": "Coffee House"},
                "formattedAddress": "Tashkent",
                "location": {"latitude": 41.3, "longitude": 69.24},
                "rating": 4.6,
                "googleMapsUri": "https://maps.google.com/",
                "currentOpeningHours": {"openNow": True},
            }
        )
        self.assertEqual(place["place_id"], "ChIJtest")
        self.assertEqual(place["name"], "Coffee House")
        self.assertTrue(place["open_now"])


class GoogleMapsPlacesClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_places_text_search(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "places": [
                {
                    "id": "places/ChIJcoffee",
                    "displayName": {"text": "Coffee"},
                    "formattedAddress": "Tashkent",
                    "location": {"latitude": 41.3, "longitude": 69.24},
                }
            ]
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            with patch("tools.builtins.google.maps_places._get_client", return_value=mock_client):
                result = await places_text_search("coffee in Tashkent")

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["places"][0]["name"], "Coffee")
        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.await_args.kwargs
        self.assertIn("X-Goog-FieldMask", call_kwargs["headers"])
        self.assertEqual(call_kwargs["json"]["textQuery"], "coffee in Tashkent")


class GoogleMapsRoutesSerializeTests(unittest.TestCase):
    def test_parse_duration_seconds(self) -> None:
        self.assertEqual(parse_duration_seconds("1680s"), 1680)
        self.assertEqual(format_duration(1680), "28 min")

    def test_compact_route_response(self) -> None:
        result = compact_route_response(
            {
                "routes": [
                    {
                        "distanceMeters": 12400,
                        "duration": "1680s",
                        "staticDuration": "1500s",
                        "localizedValues": {
                            "distance": {"text": "12.4 km"},
                            "duration": {"text": "28 min"},
                        },
                        "legs": [
                            {
                                "steps": [
                                    {
                                        "navigationInstruction": {
                                            "instructions": "Head north"
                                        }
                                    }
                                ]
                            }
                        ],
                    }
                ]
            },
            origin="A",
            destination="B",
            travel_mode="DRIVE",
            include_steps=True,
            include_polyline=False,
            maps_link="https://maps.example/dir",
        )
        self.assertEqual(result["distance_m"], 12400)
        self.assertEqual(result["steps"], ["Head north"])


class GoogleMapsRoutesClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_compute_routes_drive(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "routes": [
                {
                    "distanceMeters": 5000,
                    "duration": "900s",
                    "staticDuration": "900s",
                }
            ]
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            with patch("tools.builtins.google.maps_routes._get_client", return_value=mock_client):
                result = await compute_routes(
                    "Tashkent Airport",
                    "Chorsu Bazaar",
                    travel_mode="DRIVE",
                )

        self.assertEqual(result["distance_m"], 5000)
        self.assertEqual(result["travel_mode"], "DRIVE")
        self.assertIn("google.com/maps/dir/", result["google_maps_uri"])
        body = mock_client.post.await_args.kwargs["json"]
        self.assertEqual(body["travelMode"], "DRIVE")
        self.assertEqual(body["routingPreference"], "TRAFFIC_AWARE")
        called_url = mock_client.post.await_args.args[0]
        self.assertEqual(called_url, "https://routes.googleapis.com/directions/v2:computeRoutes")

    async def test_travel_time_transit(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            with patch(
                "tools.builtins.google.maps_routes.compute_routes",
                new=AsyncMock(
                    return_value={
                        "origin": "A",
                        "destination": "B",
                        "travel_mode": "TRANSIT",
                        "distance_m": 3000,
                        "duration_s": 600,
                        "duration_text": "10 min",
                        "google_maps_uri": "https://maps.example",
                        "steps": ["Take metro"],
                    }
                ),
            ) as mock_compute:
                result = await travel_time("A", "B", travel_mode="TRANSIT")

        self.assertNotIn("steps", result)
        self.assertEqual(result["duration_s"], 600)
        mock_compute.assert_awaited_once()


class GoogleMapsStaticTests(unittest.TestCase):
    def test_static_map_url_with_markers(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            result = static_map(
                center="41.2995,69.2401",
                markers=[{"lat": 41.3, "lng": 69.24, "label": "A", "color": "red"}],
            )

        self.assertIn("maps.googleapis.com/maps/api/staticmap", result["map_url"])
        self.assertIn("markers=", result["map_url"])
        self.assertIn("color%3Ared", result["map_url"])
        self.assertIn("key=test-key", result["map_url"])

    def test_street_view_image_url(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            result = street_view_image(41.2995, 69.2401)

        self.assertIn("maps.googleapis.com/maps/api/streetview", result["image_url"])
        self.assertIn("41.2995%2C69.2401", result["image_url"])


class GoogleMapsMiscClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_street_view_metadata_unavailable(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"status": "ZERO_RESULTS"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            with patch("tools.builtins.google.maps_misc._get_client", return_value=mock_client):
                result = await street_view_metadata(0.0, 0.0)

        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "ZERO_RESULTS")

    async def test_timezone_tashkent(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "OK",
            "timeZoneId": "Asia/Tashkent",
            "timeZoneName": "Uzbekistan Time",
            "rawOffset": 18000,
            "dstOffset": 0,
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            with patch("tools.builtins.google.maps_misc._get_client", return_value=mock_client):
                result = await timezone(41.2995, 69.2401, timestamp=1_700_000_000)

        self.assertEqual(result["time_zone_id"], "Asia/Tashkent")
        self.assertEqual(result["total_offset_s"], 18000)

    async def test_elevation_single_point(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "OK",
            "results": [
                {
                    "elevation": 455.5,
                    "location": {"lat": 41.2995, "lng": 69.2401},
                    "resolution": 4.7,
                }
            ],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
            with patch("tools.builtins.google.maps_misc._get_client", return_value=mock_client):
                result = await elevation(lat=41.2995, lng=69.2401)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["elevation_m"], 455.5)


class GoogleMapsRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_link_registered(self) -> None:
        from tools.bootstrap import create_tool_runtime

        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            runtime = await create_tool_runtime()

        result = await runtime.search_tools("", tags=["google", "maps"], mode="catalog")
        names = {tool["name"] for tool in result["tools"]}
        self.assertIn("google.maps.maps_link", names)
        self.assertIn("google.maps.geocode", names)
        self.assertIn("google.maps.reverse_geocode", names)
        self.assertIn("google.maps.geocode_batch", names)
        self.assertIn("google.maps.places_text_search", names)
        self.assertIn("google.maps.place_details", names)
        self.assertIn("google.maps.directions", names)
        self.assertIn("google.maps.travel_time", names)
        self.assertIn("google.maps.static_map", names)
        self.assertIn("google.maps.timezone", names)
        self.assertIn("google.maps.elevation", names)

        places_only = await runtime.search_tools("", tags=["google", "maps", "places"], mode="catalog")
        place_names = {tool["name"] for tool in places_only["tools"]}
        self.assertEqual(len(place_names), 5)

        routes_only = await runtime.search_tools("", tags=["google", "maps", "routes"], mode="catalog")
        route_names = {tool["name"] for tool in routes_only["tools"]}
        self.assertEqual(len(route_names), 4)

        static_only = await runtime.search_tools("", tags=["google", "maps", "static"], mode="catalog")
        static_names = {tool["name"] for tool in static_only["tools"]}
        self.assertEqual(len(static_names), 3)

    async def test_geocode_tool_runs_with_api_key(self) -> None:
        from tools.bootstrap import create_tool_runtime

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "OK",
            "results": [
                {
                    "formatted_address": "Tashkent, Uzbekistan",
                    "place_id": "ChIJtest",
                    "geometry": {
                        "location": {"lat": 41.2995, "lng": 69.2401},
                        "location_type": "APPROXIMATE",
                    },
                    "types": ["locality"],
                }
            ],
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.dict(
            os.environ,
            {"TOOL_EMBEDDING_PROVIDER": "keyword", "GOOGLE_MAPS_API_KEY": "test-key"},
            clear=False,
        ):
            runtime = await create_tool_runtime()
            with patch("tools.builtins.google.maps_client._get_client", return_value=mock_client):
                result = await runtime.use_tool(
                    "google.maps.geocode",
                    {"address": "Tashkent"},
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["count"], 1)

    async def test_geocode_requires_api_key(self) -> None:
        from tools.bootstrap import create_tool_runtime

        with patch.dict(
            os.environ,
            {"TOOL_EMBEDDING_PROVIDER": "keyword", "GOOGLE_MAPS_API_KEY": ""},
            clear=False,
        ):
            runtime = await create_tool_runtime()
            with self.assertRaises(GoogleMapsNotConfiguredError):
                await runtime.use_tool("google.maps.geocode", {"address": "Tashkent"})

    async def test_maps_link_runs_without_api_key(self) -> None:
        from tools.bootstrap import create_tool_runtime

        with patch.dict(
            os.environ,
            {"TOOL_EMBEDDING_PROVIDER": "keyword", "GOOGLE_MAPS_API_KEY": ""},
            clear=False,
        ):
            runtime = await create_tool_runtime()

        result = await runtime.use_tool(
            "google.maps.maps_link",
            {"link_type": "search", "query": "Tashkent"},
        )
        self.assertTrue(result["ok"])
        self.assertIn("google.com/maps/search/", result["result"]["url"])

    def test_google_maps_configured(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "abc"}, clear=False):
            self.assertTrue(google_maps_configured())
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}, clear=False):
            self.assertFalse(google_maps_configured())


if __name__ == "__main__":
    unittest.main()
