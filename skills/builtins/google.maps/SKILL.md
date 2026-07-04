---
skill_id: google.maps
description: Google Maps Platform — places, routes, geocoding, static maps, links, transit (Yandex overlay)
tags: google, maps
---

# Google Maps skill

Use this skill when the user asks about **places, addresses, directions, travel time, maps links, nearby POI, timezone, or elevation**.

**Auth:** server-side `GOOGLE_MAPS_API_KEY` only — no user OAuth. If maps tools return "Maps API not configured", tell the user to set the API key in bot config.

**Defaults:** language `ru`, region `uz`, default map center near Tashkent (41.2995, 69.2401) from bot config.

## Discovery

Load this skill once per agent run with `skills.load` (`skill_id: "google.maps"`).

Find tools via `search_tools` — always pass tags (AND filter):

| Need | search_tools |
|------|----------------|
| Full maps catalog | `{"mode":"catalog","tags":["google","maps"]}` |
| Places only | `{"mode":"catalog","tags":["google","maps","places"]}` |
| Routes only | `{"mode":"catalog","tags":["google","maps","routes"]}` |
| Geocoding only | `{"mode":"catalog","tags":["google","maps","geocoding"]}` |
| Rank by capability | `{"mode":"rank","query":"directions driving","tags":["google","maps"]}` |

Param for text search is **`text_query`**, not `query` (on `google.maps.places_text_search`).

## Tool families (18 tools)

### Geocoding — tags `google, maps, geocoding`

| Tool | When |
|------|------|
| `google.maps.geocode` | Address or place name → `{lat, lng, formatted_address, place_id?}` |
| `google.maps.reverse_geocode` | `{lat, lng}` → address |
| `google.maps.geocode_batch` | Up to 10 addresses in one call |

**Rule:** If the user gave an address string but a tool needs coordinates (nearby, timezone, elevation), **geocode first**.

### Places — tags `google, maps, places`

| Tool | When |
|------|------|
| `google.maps.places_text_search` | «кофейня в центре», «McDonald's near X» — param `text_query` |
| `google.maps.places_nearby_search` | POI near `{lat, lng}` + `included_types` + radius |
| `google.maps.place_details` | Hours, phone, website, rating — needs `place_id` from search |
| `google.maps.place_photo` | Photo URL for a place |
| `google.maps.places_autocomplete` | Disambiguate partial input |

**Flow:** text_search or nearby → `place_id` → place_details for rich answer.

### Routes — tags `google, maps, routes`

| Tool | When |
|------|------|
| `google.maps.travel_time` | **Sugar** — «сколько ехать» — duration + distance only |
| `google.maps.directions` | **Sugar** — addresses → geocode both → route summary + steps |
| `google.maps.compute_routes` | Low-level Routes API (origin/destination as lat/lng or place) |
| `google.maps.compute_route_matrix` | Many origins × destinations ETA matrix |

**travel_mode:** `DRIVE` | `WALK` | `TRANSIT` | `BICYCLE` (where supported).

**Prefer sugar tools** (`travel_time`, `directions`) for natural-language A→B questions.

### Static & misc — tags `google, maps, static` or `geocoding`

| Tool | When |
|------|------|
| `google.maps.static_map` | PNG map URL — center, markers, path, zoom |
| `google.maps.street_view_metadata` | Is Street View available? |
| `google.maps.street_view_image` | Panorama image URL |
| `google.maps.timezone` | Time zone at coordinates |
| `google.maps.elevation` | Meters above sea level |

### Zero-cost links

| Tool | When |
|------|------|
| `google.maps.maps_link` | User only needs a URL — **no API call**. `link_type`: `search` \| `directions` \| `place` |

Use `maps_link` when a link is enough; use route tools when you need live ETA or steps.

## Transit (public transport)

When `MAPS_TRANSIT_LINK_PROVIDER=yandex` (default for Tashkent-friendly UX):

- `travel_mode=TRANSIT` on `directions`, `maps_link`, or route tools triggers **Yandex Maps URL** overlay.
- Tool result includes `route_complete=true`, `count=1`, `route_note` — **do not call `exa.web_search`** for more transit info.
- Agent loop may skip redundant `exa.web_search` after a satisfied transit route.

Tell the user to open the **inline button** «На общественном транспорте» or paste the directions URL in your final reply.

## Telegram reply rules

1. **Directions / places the user should open:** put `google_maps_uri` or `url` in the **final reply** as plain URL or `[label](url)` — becomes inline button, stripped from visible text.
2. **Transit:** paste the Yandex or Google directions URL from the tool result.
3. **Do NOT** paste raw Static Map / Street View / place photo API URLs in the reply — those stay in collapsed «Ссылки» only.
4. URLs must use literal `&` in query strings, never `&amp;`.
5. Tool-only map links appear in collapsed «Ссылки» at the bottom unless you repeat the same URL in the final answer.

## Typical workflows

### «Как доехать из A в B?»
1. Optional: `skills.load` if not loaded.
2. `google.maps.directions` with `origin`, `destination`, `travel_mode` (TRANSIT if public transport).
3. Summarize duration/distance; add map URL in final reply for button.

### «Где ближайшая аптека?»
1. Geocode user location or use Telegram 📍 coordinates from message.
2. `places_nearby_search` with types + radius.
3. `place_details` on top result if needed.

### «Что это за адрес?» (coordinates)
`reverse_geocode` with `lat`, `lng`.

### «Сколько ехать на машине?»
`travel_time` — faster than full directions.

### User only wants a map link
`maps_link` with `link_type=search|directions|place` — skip paid API route calls.

## Anti-patterns

- Do not guess coordinates or travel times — use tools.
- Do not use Exa for maps/places/routes when maps tools are available.
- Do not call `places_text_search` with param name `query` — use `text_query`.
- Do not re-search transit after `route_complete=true`.
- Do not require `/connect_google` for maps (OAuth is unrelated).

## Rate limits (env defaults)

Geocode ~30/min, Places ~15/min, Routes ~10/min, Static ~5/min. Results are cached (geocode 24h, places search 1h, routes 30m).
