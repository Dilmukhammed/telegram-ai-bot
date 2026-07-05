---
skill_id: yandex.music
description: Yandex Music — search, library, playlists, likes, radio, download (MarshalX API)
tags: yandex, music
---

# Yandex Music skill

Use when the user asks about **tracks, albums, artists, playlists, likes, recommendations, radio, or downloading music from Yandex Music**.

**Auth:** per-user **device OAuth** (not Google-style browser redirect). Check `yandex.auth.status` → `music_ready=true`. If not connected: tell user `/connect_yandex` in Telegram (auto-polls) or agent calls `yandex.auth.connect_start` + user confirms at `verification_url` with `user_code`.

**Language:** API responses follow `YANDEX_MUSIC_LANGUAGE` (default `ru`).

## Discovery

Load once per multi-step run: `skills.load` → `{"skill_id":"yandex.music"}`.

| Need | search_tools |
|------|----------------|
| Full catalog | `{"mode":"catalog","tags":["yandex","music"]}` |
| Auth tools | `{"mode":"catalog","tags":["yandex","auth"]}` |
| Rank by capability | `{"mode":"rank","query":"search tracks","tags":["yandex","music"]}` |

## Common workflows

### Search & play info

1. `yandex.music.search` — `text` query, optional `type_` (`track`, `album`, `artist`, `playlist`, …).
2. `yandex.music.tracks` / `yandex.music.albums` / `yandex.music.artists` — fetch by id(s).
3. Link format: `https://music.yandex.ru/album/{album_id}/track/{track_id}` (include in replies when helpful).

### User library (requires auth)

| Tool | When |
|------|------|
| `yandex.music.users_playlists_list` | List user playlists |
| `yandex.music.users_likes_tracks` | «Мне нравится» |
| `yandex.music.users_likes_albums` | Liked albums |
| `yandex.music.users_likes_artists` | Liked artists |
| `yandex.music.feed` | Home feed / recommendations |
| `yandex.music.playlists_personal` | Personal mixes |

### Download & send in Telegram

1. Resolve `track_id` (from search or user link). Format: `trackId` or `trackId:albumId`.
2. `yandex.music.track_download` — `track_id`, optional `codec` (`mp3`|`aac`).
3. Result includes `file_ref` → `telegram.send_file` with that `file_ref`. **Do not invent file_ref.**

### Radio / rotor

- `yandex.music.rotor_account_status`, `rotor_stations_dashboard`, `rotor_station_tracks` — personalized radio.
- Feedback tools (`rotor_station_feedback_*`) are **write** — use only when user explicitly wants to train/skip.

### Queues & history

- `yandex.music.queues_list`, `queue`, `queue_create` — playback queues (auth).
- `yandex.music.music_history` — listening history (auth).

## Tool surface

**148 agent tools total:**

- **141** `yandex.music.*` — thin wrappers over `ClientAsync` (MarshalX yandex-music-api).
- **4** `yandex.auth.*` — status, connect_start, poll_device, disconnect.
- **1** extra — `yandex.music.track_download` (bytes → run `file_ref`).

OAuth device methods (`request_device_code`, `poll_device_token`) are **not** exposed as music tools — use `yandex.auth.*` or `/connect_yandex`.

## Anti-patterns

- Do not guess track ids — search or parse from user URL first.
- Do not call write tools (likes add/remove, queue update, feedback) without explicit user intent.
- Do not use Exa for user's Yandex library — use authenticated `yandex.music.*` tools.
- For «скачай и пришли» always: `track_download` → `telegram.send_file`.

## Parameter notes

- API param `from` → pass as `"from"` in JSON (mapped to `from_` internally).
- Many methods accept comma-separated ids in string params — match API docs in tool schema.
- `additionalProperties: true` on schemas — pass through extra API kwargs when needed.
