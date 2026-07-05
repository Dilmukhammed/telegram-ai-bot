# Yandex Music integration

Final single-version integration: full [MarshalX/yandex-music-api](https://github.com/MarshalX/yandex-music-api) `ClientAsync` surface + auth + download + bot connect.

## Scope

| Component | Count / path |
|-----------|----------------|
| Music API tools | 141 × `yandex.music.{method}` |
| Download | `yandex.music.track_download` |
| Auth tools | 4 × `yandex.auth.*` |
| **Total registered** | **146** |
| Skill | `skills/builtins/yandex.music/SKILL.md` |
| Token store | `data/yandex_tokens.sqlite` |
| Dependency | `yandex-music[async]>=3.0.0` |

Excluded from music namespace (use auth flow instead): `device_auth`, `request_device_code`, `poll_device_token`.

## Auth (device OAuth)

Same UX pattern as Google connect — user runs a bot command, bot polls until linked.

```
/connect_yandex   → URL + user_code + background poll
/yandex_status    → connected / pending / disconnected
/disconnect_yandex
```

Agent tools: `yandex.auth.status`, `connect_start`, `poll_device`, `disconnect`.

Implementation: `tools/builtins/yandex/auth.py`, `token_store.py`, `bot/yandex_connect.py`.

**Note:** Yandex uses device OAuth (code at yandex.ru/device), not Google-style redirect URI. Refresh tokens are stored; automatic refresh on expiry is a future hardening item.

## Download pipeline

```
yandex.music.track_download(track_id, codec=mp3)
  → RunFileStore.save(bytes)
  → { file_ref, title, url, track }
telegram.send_file(file_ref=...)
```

Requires connected account for full tracks (`require_auth=true` default).

## Registry generation

```powershell
.venv\Scripts\python.exe scripts\generate_yandex_music_registry.py
```

Introspects `ClientAsync`, sets `auth`/`write` heuristics, emits `music_tool_registry.py`. Re-run after yandex-music library upgrades.

## Config (.env)

```
YANDEX_TOKEN_DB_PATH=data/yandex_tokens.sqlite
YANDEX_MUSIC_LANGUAGE=ru
YANDEX_MUSIC_RATE_LIMIT_READ=60/60
YANDEX_MUSIC_RATE_LIMIT_WRITE=30/60
```

Rate limits applied via `tools/phase4_config.py` prefix `yandex.music.*`.

## Agent integration

- System prompt: `agent/prompts.py` — Yandex Music + tag table
- Auto skill load: `skills/skill_map.py` — `yandex.music.*` → `yandex.music`
- Search hints: `agent/tool_search_hints.py` — tags `yandex,music` / `yandex,auth`
- Bootstrap: `tools/bootstrap.py` registers `YANDEX_TOOLS`

## File layout

```
tools/builtins/yandex/
  music_tool_registry.py   # generated
  music_tools.py           # factory + auth + track_download
  music_client.py          # ClientAsync, call_method, download
  music_serialize.py       # compact API responses
  auth.py, token_store.py, errors.py, tool_hints.py
  maps_urls.py             # (existing Maps transit links — separate)
bot/yandex_connect.py
scripts/generate_yandex_music_registry.py
test_yandex_music.py
```

## Tests

```powershell
.venv\Scripts\python.exe -m pytest test_yandex_music.py test_tool_search_hints.py test_skills.py -q
```

## Not in scope (deferred)

- Rich reply blocks with embedded album art
- Inline music buttons / URL stripping for music.yandex.ru
- Token refresh on 401
