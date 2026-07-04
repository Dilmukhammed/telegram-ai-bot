# Google Maps — план интеграции

Полный каталог tools, волны, auth-модель, биллинг и технические детали.  
Файл для ревью перед кодом.

---

## 1. Цель

Telegram-бот (Hermes Agent) получает доступ к **Google Maps Platform** для:

- геокодирования («где это», адрес ↔ координаты)
- поиска мест («кафе рядом», «аптека в Ташкенте»)
- маршрутов и ETA («как доехать», «сколько ехать»)
- картинок карты в чат (Static Maps)
- timezone / elevation по координатам

Агент вызывает tools через существний flow: `search_tools` → `use_tool`.  
**Tool graph не используется** — maps tools регистрируются в общем registry с тегами.

```json
{"query": "directions to airport", "tags": ["google", "maps"]}
{"mode": "catalog", "tags": ["google", "maps", "places"]}
```

---

## 2. Auth — принципиально не OAuth

| | Calendar | Maps |
|---|----------|------|
| Модель | User OAuth 2.0 | **Project API key** |
| Кто платит | квота пользователя в Google | **billing проекта GCP** |
| Per-user login | да (`/connect_google`) | **нет** |
| Токен | refresh per telegram_user_id | один ключ на сервер |

**Почему:** Maps Platform — server-side API с биллингом на проект. User OAuth для Maps возможен (Places New поддерживает), но для личного бота **API key проще и дешевле в поддержке**.

### 2.1 Env

```
GOOGLE_MAPS_API_KEY=                    # обязателен для google.maps.*
GOOGLE_MAPS_DEFAULT_LANGUAGE=ru         # languageCode в запросах
GOOGLE_MAPS_DEFAULT_REGION=uz           # regionCode bias (ISO 3166-1 alpha-2)
GOOGLE_MAPS_DEFAULT_LOCATION=41.2995,69.2401   # fallback center (Tashkent), если user не дал точку
```

→ `config.py`, `.env.example`

### 2.2 GCP setup

1. Тот же Google Cloud project, что Calendar (или отдельный — решить).
2. **Enable APIs:**
   - Geocoding API
   - Places API **(New)** — не Legacy
   - Routes API — не Directions / Distance Matrix Legacy
   - Time Zone API
   - Elevation API
   - Maps Static API
   - Street View Static API
   - Address Validation API *(опционально, Maps-5)*
3. **API key** с restrictions:
   - Application: IP addresses (сервер бота) **или** none для dev
   - API restrictions: только список выше
4. **Billing alerts** — обязательно (см. §8).

### 2.3 Guard

- `google.maps.*` без `GOOGLE_MAPS_API_KEY` → `{ok: false, error: "Maps API not configured"}`
- OAuth / `/connect_google` **не нужен** для maps
- Per-user **rate limits** в боте (общая квота ключа на всех users)

### 2.4 Файлы (target layout)

```
tools/builtins/google/
  maps_client.py          # httpx async client, API key header, field masks
  maps_geocoding.py       # geocode handlers
  maps_places.py          # Places (New)
  maps_routes.py          # Routes API
  maps_static.py          # Static Map + Street View URLs
  maps_misc.py            # timezone, elevation, validate_address
  maps_tools.py           # ToolSpec registry → GOOGLE_MAPS_TOOLS
  maps_serialize.py       # compact place/route/geocode for LLM
```

---

## 3. API surface — что используем (2026)

| Legacy (не брать) | Замена |
|-------------------|--------|
| Places API (Legacy) | **Places API (New)** |
| Directions API | **Routes API** `computeRoutes` |
| Distance Matrix API | **Routes API** `computeRouteMatrix` |
| Find Place (Legacy) | Text Search (New) |

**Field masks обязательны** для Places (New) и Routes — иначе дорого и Google вернёт ошибку.

Pricing tiers (Routes): Basic / Advanced / Preferred — зависят от полей в `X-Goog-FieldMask`.  
Для бота: **минимальные field masks** по умолчанию.

---

## 4. Полный каталог tools

Префикс: `google.maps.*`  
Tags baseline: `google`, `maps` + семейство (`geocoding`, `places`, `routes`, `static`, `scheduling`)

### 4.1 Geocoding (Maps-1)

| Tool | API | Что делает |
|------|-----|------------|
| `google.maps.geocode` | Geocoding: forward | Адрес / название → `{lat, lng, formatted_address, place_id?, components}` |
| `google.maps.reverse_geocode` | Geocoding: reverse | `{lat, lng}` → адрес, район, город, страна |
| `google.maps.geocode_batch` | Geocoding × N | Несколько адресов (local loop, max 10, с rate guard) |

**Параметры `geocode`:**

| Param | Type | Notes |
|-------|------|-------|
| `address` | string | «ул. Навoi, Ташкент» |
| `language` | string? | default `ru` |
| `region` | string? | bias, default `uz` |
| `bounds` | object? | `{sw, ne}` для disambiguation |

**Returns (compact):**

```json
{
  "query": "Chorsu Bazaar Tashkent",
  "results": [
    {
      "formatted_address": "...",
      "lat": 41.326,
      "lng": 69.234,
      "place_id": "ChIJ...",
      "location_type": "ROOFTOP",
      "types": ["tourist_attraction"]
    }
  ],
  "count": 1
}
```

---

### 4.2 Places — Places API (New) (Maps-2)

| Tool | API endpoint | Что делает |
|------|--------------|------------|
| `google.maps.places_text_search` | `places:searchText` | «кофейня в центре Ташкента», «McDonald's near me» + optional location bias |
| `google.maps.places_nearby_search` | `places:searchNearby` | POI рядом с `{lat,lng}` + `included_types[]` + radius |
| `google.maps.place_details` | `places/{place_id}` | Часы, телефон, сайт, рейтинг, reviews snippet, coords |
| `google.maps.place_photo` | `places/{id}/photos/{ref}/media` | URL фото места (max dimensions) |
| `google.maps.places_autocomplete` | `places:autocomplete` | Подсказки при неполном вводе (disambiguation) |

**`places_text_search` params:**

| Param | Notes |
|-------|-------|
| `text_query` | required |
| `location_bias` | circle `{center, radius_m}` or rectangle |
| `included_type` | e.g. `restaurant`, `pharmacy` |
| `min_rating` | filter |
| `open_now` | bool |
| `language` | default `ru` |
| `max_results` | default 10, cap 20 |

**`places_nearby_search` params:**

| Param | Notes |
|-------|-------|
| `lat`, `lng` | required center |
| `radius_m` | default 1500, max 50000 |
| `included_types` | array, max 5 types |
| `max_results` | default 10 |

**`place_details` — preset field groups** (чтобы LLM не перечислял 40 полей):

| `detail_level` | Fields (field mask) |
|----------------|---------------------|
| `basic` | id, displayName, formattedAddress, location, googleMapsUri |
| `contact` | + nationalPhoneNumber, websiteUri, regularOpeningHours |
| `full` | + rating, userRatingCount, reviews (1), photos metadata, priceLevel |

**Returns (compact place):**

```json
{
  "place_id": "ChIJ...",
  "name": "Coffee Shop",
  "address": "...",
  "lat": 41.31,
  "lng": 69.24,
  "rating": 4.5,
  "open_now": true,
  "hours_today": "09:00–22:00",
  "phone": "+998...",
  "website": "https://...",
  "google_maps_uri": "https://maps.google.com/?cid=..."
}
```

---

### 4.3 Routes — Routes API (Maps-3)

| Tool | API | Что делает |
|------|-----|------------|
| `google.maps.compute_routes` | `directions/v2:computeRoutes` | Маршрут A→B: distance, duration, steps summary, polyline optional |
| `google.maps.compute_route_matrix` | `directions/v2:computeRouteMatrix` | N origins × M destinations → matrix ETA/distance |
| `google.maps.directions` | **sugar** | Addresses/strings → geocode both → `compute_routes` (DRIVE default) |
| `google.maps.travel_time` | **sugar** | «сколько ехать из A в B» — только duration + distance |

**`compute_routes` params:**

| Param | Notes |
|-------|-------|
| `origin` | `{lat,lng}` or address string (local geocode first) |
| `destination` | same |
| `waypoints` | optional array, max 25 |
| `travel_mode` | `DRIVE` (default), `WALK`, `TRANSIT` — v1; `BICYCLE`, `TWO_WHEELER` later |
| `departure_time` | ISO — traffic-aware ETA |
| `avoid` | `tolls`, `highways`, `ferries` |
| `language` | default `ru` |
| `units` | `METRIC` |
| `include_steps` | bool, default false (summary only) |
| `include_polyline` | bool, default false (экономия токенов) |

**Returns (compact route):**

```json
{
  "origin": "...",
  "destination": "...",
  "travel_mode": "DRIVE",
  "distance_m": 12400,
  "distance_text": "12.4 km",
  "duration_s": 1680,
  "duration_text": "28 min",
  "duration_in_traffic_s": 1920,
  "steps": ["Head north on...", "Turn right..."],
  "google_maps_uri": "https://www.google.com/maps/dir/..."
}
```

---

### 4.4 Static & visual (Maps-4)

| Tool | API | Что делает |
|------|-----|------------|
| `google.maps.static_map` | Maps Static API | URL PNG карты: center, markers, path, zoom |
| `google.maps.street_view_metadata` | Street View Static metadata | Есть ли панорама для `{lat,lng}` |
| `google.maps.street_view_image` | Street View Static | URL панорамы |

**Telegram integration (optional, same wave):**

- Bot отправляет `static_map` как **photo** в чат (download URL → sendPhoto)
- Не tool, а `chat_service` hook: если agent вернул `{static_map_url}` → attach

**`static_map` params:**

| Param | Notes |
|-------|-------|
| `center` | `{lat,lng}` or address |
| `zoom` | 1–21, default 14 |
| `size` | `640x640` max for free tier usage |
| `markers` | array `{lat,lng,label?,color?}` |
| `path` | encoded polyline from route (optional) |
| `map_type` | `roadmap`, `satellite`, `hybrid` |

---

### 4.5 Misc (Maps-4 / Maps-5)

| Tool | API | Что делает |
|------|-----|------------|
| `google.maps.timezone` | Time Zone API | `{lat,lng}` + optional timestamp → `timeZoneId`, offset |
| `google.maps.elevation` | Elevation API | coords → meters above sea level |
| `google.maps.validate_address` | Address Validation API | Нормализация / verdict (deliverable?) — **Maps-5** |
| `google.maps.places_along_route` | Places Text Search + routing | POI вдоль маршрута — **Maps-5** |

---

### 4.6 Local helpers (no Google call)

| Tool | Что делает |
|------|------------|
| `google.maps.maps_link` | Собрать `google.com/maps` URL: search / dir / place — zero cost |

Полезно когда API не нужен, только ссылка пользователю.

---

## 5. Сводная таблица (все tools)

| # | Tool | Wave | Tags | API | Cache TTL |
|---|------|------|------|-----|-----------|
| 1 | `google.maps.geocode` | Maps-1 | `google`, `maps`, `geocoding`, `read` | Geocoding forward | 24h |
| 2 | `google.maps.reverse_geocode` | Maps-1 | `google`, `maps`, `geocoding`, `read` | Geocoding reverse | 24h |
| 3 | `google.maps.geocode_batch` | Maps-1 | `google`, `maps`, `geocoding`, `read` | Geocoding ×N | 24h |
| 4 | `google.maps.places_text_search` | Maps-2 | `google`, `maps`, `places`, `read` | Places searchText | 1h |
| 5 | `google.maps.places_nearby_search` | Maps-2 | `google`, `maps`, `places`, `read` | Places searchNearby | 1h |
| 6 | `google.maps.place_details` | Maps-2 | `google`, `maps`, `places`, `read` | Places get | 6h |
| 7 | `google.maps.place_photo` | Maps-2 | `google`, `maps`, `places`, `read` | Places photo media | 24h |
| 8 | `google.maps.places_autocomplete` | Maps-2 | `google`, `maps`, `places`, `read` | Places autocomplete | 10m |
| 9 | `google.maps.compute_routes` | Maps-3 | `google`, `maps`, `routes`, `read` | Routes computeRoutes | 30m |
| 10 | `google.maps.compute_route_matrix` | Maps-3 | `google`, `maps`, `routes`, `read` | Routes computeRouteMatrix | 30m |
| 11 | `google.maps.directions` | Maps-3 | `google`, `maps`, `routes`, `read` | sugar | 30m |
| 12 | `google.maps.travel_time` | Maps-3 | `google`, `maps`, `routes`, `read` | sugar | 30m |
| 13 | `google.maps.static_map` | Maps-4 | `google`, `maps`, `static`, `read` | Static Maps | 1h |
| 14 | `google.maps.street_view_metadata` | Maps-4 | `google`, `maps`, `static`, `read` | Street View metadata | 24h |
| 15 | `google.maps.street_view_image` | Maps-4 | `google`, `maps`, `static`, `read` | Street View static | 1h |
| 16 | `google.maps.timezone` | Maps-4 | `google`, `maps`, `geocoding`, `read` | Time Zone | 7d |
| 17 | `google.maps.elevation` | Maps-4 | `google`, `maps`, `read` | Elevation | 7d |
| 18 | `google.maps.maps_link` | Maps-1 | `google`, `maps`, `read` | local | — |
| 19 | `google.maps.validate_address` | Maps-5 | `google`, `maps`, `geocoding`, `read` | Address Validation | 24h |
| 20 | `google.maps.places_along_route` | Maps-5 | `google`, `maps`, `places`, `routes`, `read` | Places + Routes | 30m |

**Total: 20 maps tools** (14 core + 2 sugar + 1 local + 3 advanced)

---

## 6. Волны реализации

### Wave Maps-0 — infra

- [x] `GOOGLE_MAPS_*` в `config.py` + `.env.example`
- [x] `maps_client.py` — httpx geocode client, error mapping, `maps_api_call` logging
- [x] `maps_serialize.py` — compact geocode payloads
- [x] Guard: `GoogleMapsNotConfiguredError` if no API key
- [x] Rate limits: `MAPS_RATE_LIMIT_GEOCODE`, `MAPS_RATE_LIMIT_DEFAULT` in `phase4_config.py`
- [x] Register `google.maps.maps_link` + search_tools tag `google.maps`
- [x] Tests: `test_google_maps.py` (client mock + maps_link runtime)

**Deliverable:** config validated, geocode client tested (mock); live key → ready for Maps-1 tool registration.

---

### Wave Maps-1 — geocoding (4 tools)

Tools: `geocode`, `reverse_geocode`, `geocode_batch`, `maps_link`

- [x] `google.maps.geocode`
- [x] `google.maps.reverse_geocode`
- [x] `google.maps.geocode_batch`
- [x] `google.maps.maps_link` (Maps-0)

**Deliverable:** «где находится X», «что за адрес по координатам», ссылка на Google Maps.

Tests:

- [x] forward geocode (mock + runtime)
- [x] reverse geocode lat/lng
- [x] batch respects max 10
- [x] no API key → clear error
- [x] cache/rate limit wired via ToolSpec

---

### Wave Maps-2 — places (5 tools)

Tools: `places_text_search`, `places_nearby_search`, `place_details`, `place_photo`, `places_autocomplete`

- [x] all 5 tools registered with Places API (New)
- [x] field masks per detail_level / search
- [x] compact place serializer
- [x] rate limits + cache TTLs

**Deliverable:** «кафе рядом», «рейтинг ресторана», «открыто ли сейчас», photo URL.

Tests:

- [x] text search mock
- [x] compact_place serializer
- [x] catalog tag `google.maps.places` → 5 tools

---

### Wave Maps-3 — routes (4 tools)

Tools: `compute_routes`, `compute_route_matrix`, `directions`, `travel_time`

- [x] Routes API (New) client with field masks
- [x] DRIVE / WALK / TRANSIT modes
- [x] sugar: `directions` (with steps), `travel_time` (ETA only)
- [x] google_maps_uri in route response

**Deliverable:** «как доехать до аэропорта», «сколько ехать», matrix для нескольких точек.

Tests:

- [x] compute_routes DRIVE mock
- [x] travel_time strips steps
- [x] route serializer + registry catalog `google.maps.routes`

---

### Wave Maps-4 — static & misc (5 tools)

Tools: `static_map`, `street_view_metadata`, `street_view_image`, `timezone`, `elevation`

- [x] Static Maps URL builder (markers, path, map_type)
- [x] Street View metadata + image URL
- [x] Time Zone + Elevation API clients
- [x] Rate limit `MAPS_RATE_LIMIT_STATIC=5/60`

**Deliverable:** карта-картинка в Telegram, timezone для coords, elevation trivia.

Optional same wave:

- ~~Bot sends static_map as photo attachment~~ — **отложено**; v1 только URL в ответе агента

Tests:

- [x] static_map URL valid, markers render
- [x] street_view metadata false for ocean coords
- [x] timezone matches Asia/Tashkent for center coords

---

### Wave Maps-5 — advanced (2 tools, optional)

Tools: `validate_address`, `places_along_route`

**Deliverable:** «проверь адрес доставки», «заправки по пути».

Defer until Maps-1–4 in production use.

---

## 7. Agent prompt hints

```
- For maps/places/routes: search_tools with tags ["google","maps"] or ["google","maps","places"].
- Prefer sugar tools: directions / travel_time over raw compute_routes when user gives addresses.
- Prefer places_text_search for "find X"; places_nearby_search when user gave location or "near me".
- Always call place_details before claiming phone/hours/website.
- Default language ru, region uz unless user context says otherwise.
- Routes travel_mode: DRIVE (default), WALK, TRANSIT. If TRANSIT returns no route, retry DRIVE or WALK and tell the user.
- Use maps_link when user only needs a link, not live data.
- static_map for "show on map" — mention bot may attach image.
- Do not invent coordinates; geocode first if unsure.
- Calendar + Maps: geocode event location → optional static_map in event description (future).
```

---

## 8. Rate limits, cache, billing

### Per-user rate limits (starting point)

| Group | Limit | Window |
|-------|-------|--------|
| Geocoding | 30 | 1 min |
| Places search | 15 | 1 min |
| Place details | 20 | 1 min |
| Routes | 10 | 1 min |
| Static map | 5 | 1 min |
| **Total maps** | 60 | 1 hour |

Overrides via env `MAPS_RATE_LIMIT_*` — как exa overrides в `phase4_config.py`.

### Cache

| Tool group | TTL | Key |
|------------|-----|-----|
| Geocode | 24h | normalized address / rounded lat,lng |
| Place details | 6h | place_id + detail_level |
| Text/nearby search | 1h | query + location hash |
| Routes | 30m | origin+dest+mode+departure bucket |
| Static map | 1h | param hash |
| Timezone | 7d | lat,lng (rounded 3 decimals) |

### Billing alerts (GCP)

- [ ] Budget alert $10 / $25 / $50
- [ ] Daily quota cap in GCP console (Places, Routes)
- [ ] Telemetry dashboard: top tools by call count

**Rough cost awareness** (order of magnitude, check current pricing):

- Geocoding: ~$5 / 1000
- Places Text Search: ~$32 / 1000 (New, depends on fields)
- Routes computeRoutes: ~$5–15 / 1000 (tier)
- Static Maps: ~$2 / 1000

Личный бот при умеренном use — **$5–20/мес** если cache + rate limits.

---

## 9. Explicitly NOT in scope

| Feature | Reason |
|---------|--------|
| Maps JavaScript API | Browser-only, не для Telegram bot |
| Legacy Directions / Distance Matrix | Deprecated → Routes API |
| Legacy Places | Deprecated → Places (New) |
| Heatmap / Drawing (JS) | Deprecated May 2026 |
| Fleet Routing, Route Optimization | Enterprise logistics |
| Roads API (snap to roads) | Niche, GPS traces |
| Map Tiles API | Custom map rendering |
| Aerial View, Pollen, Solar, Weather | Separate products |
| Geolocation API (cell/WiFi) | Client-side, не server bot |
| User OAuth for Maps | API key достаточно для v1 |
| Real-time traffic **subscriptions** | Needs watch/polling — overkill |
| Store user home/work address | Memory graph phase — not Maps v1 |

---

## 10. Open decisions (for review)

### Решено (2026-07-03)

| Вопрос | Решение |
|--------|---------|
| GCP project | **Тот же проект**, что Calendar |
| Default location | **Tashkent** `41.2995, 69.2401` |
| Static map в чат | **Только URL** в тексте, без auto photo (Maps v1) |
| Maps users | все Telegram users (не уточнялось — default: все, rate limits per user) |
| **Travel modes v1** | **`DRIVE`, `WALK`, `TRANSIT`** — все три в schema и prompt |

### Ожидает решения

- [ ] **Places photos:** URL в ответе LLM vs bot download — default URL
- [ ] **Maps-5** в v1 или defer

#### Travel modes (v1)

| Mode | Включён | Когда |
|------|---------|-------|
| `DRIVE` | ✅ | default |
| `WALK` | ✅ | «пешком» |
| `TRANSIT` | ✅ | «на метро/автобусе», «общественный транспорт» |
| `BICYCLE` | ❌ v1 | отложено |
| `TWO_WHEELER` | ❌ v1 | отложено |

Prompt: если `TRANSIT` вернул пусто — fallback на `DRIVE` или `WALK` и сказать user.

---

## 11. Integration with Calendar (future, not Maps v1)

| Use case | Flow |
|----------|------|
| Event with location | create_event + geocode location → lat/lng in description |
| «Когда выехать на встречу» | calendar get_event → directions with departure_time |
| «Ресторан рядом с встречей» | get_event location → nearby_search |

Не блокирует Maps v1 — просто compound queries после обеих фич.

---

## 12. Checklist before coding

- [ ] Review this file
- [ ] Confirm wave order (Maps-0 → Maps-1 → … → Maps-4)
- [ ] Confirm tool names / 20-tool catalog
- [ ] Enable APIs in GCP + create restricted API key
- [ ] Set billing alerts
- [ ] Add `GOOGLE_MAPS_*` to config + env.example
- [ ] Decide admin-only vs all users

---

## 13. Статус

| | |
|---|---|
| **Статус** | **Maps-4 done** — static, street view, timezone, elevation |
| **Зависимости** | Calendar done ✓; OAuth not required |
| **Decisions** | Same GCP project; Tashkent default; static map = URL only; routes: DRIVE+WALK+TRANSIT |
| **Next step** | Maps-5 (optional): validate_address, places_along_route |

---

*Last updated: 2026-07-03*
