# Agent Workspace — план

Локальная песочница на сервере: агент работает **только внутри одной папки на пользователя** — создаёт/читает/удаляет файлы, получает inbound из Telegram, отправляет через `telegram.send_file`.

Файл для ревью перед кодом. Стиль как `GOOGLE_DRIVE_PLAN.md`.

---

## 1. Цель

| Сейчас | После workspace |
|--------|-----------------|
| Фото → base64 в LLM, без path | Фото/файл → `data/workspaces/{user_id}/uploads/…` + path в контексте агента |
| Документ от юзера → не обрабатывается | Сохраняется в `uploads/`, агент может `workspace.read_file` |
| Google download → ephemeral `RunFileStore` | Опционально копия в `exports/`; path + `file_ref` |
| Агент не создаёт локальные файлы | `workspace.write_file`, `mkdir`, … |

**Не цель v1:** shell, произвольные пути вне sandbox, доступ к системным файлам, Python exec.

---

## 2. Модель данных

### 2.1 Корень (per-user, persistent)

```
data/workspaces/{telegram_user_id}/
  uploads/       # inbound из Telegram (+ agent read/write)
  agent/         # файлы, созданные агентом
  exports/       # опционально: кэш из Drive/Gmail (Wave 2)
```

Создаётся lazily при первом обращении. `uploads/`, `agent/`, `exports/` — pre-create при init.

### 2.2 Идентификаторы

| ID | Где используется | Пример |
|----|------------------|--------|
| **`path`** | Все `workspace.*` tools — относительный путь от корня user | `agent/report.md`, `uploads/photo.jpg` |
| **`file_ref`** | `telegram.send_file`, binary read results | `ws:a1b2c3d4:003` (opaque, scoped run+user) |

**Правило:** агент в prompts оперирует **`path`**. `file_ref` — для send и когда binary слишком большой для inline text.

### 2.3 Связь с RunFileStore

| Store | Lifetime | Источник |
|-------|----------|----------|
| **RunFileStore** (есть) | Один agent run, temp dir | Google download, Gmail attachment |
| **Workspace** (новый) | Между сообщениями, disk | Telegram inbound, agent writes |

**Wave 1:** оба параллельно. `telegram.send_file` принимает `file_ref` из любого store.

**Wave 2 (optional):** `google.drive.download_file` → опция `save_to_workspace: true` → path в `exports/`.

---

## 3. Безопасность

### 3.1 Path resolution

```python
def resolve_workspace_path(user_id: int, relative: str) -> Path:
    root = WORKSPACE_ROOT / str(user_id)
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):  # py3.11+
        raise WorkspacePathError("path escapes workspace")
    return target
```

- Запрет: `..`, absolute paths, `\`, null bytes, control chars
- Нормализация: `agent/foo//bar` → `agent/foo/bar`
- Symlinks: не создавать; при resolve если symlink points outside → reject

### 3.2 Зоны

| Зона | Read | Write | Delete |
|------|------|-------|--------|
| `uploads/` | ✅ | ✅ | ✅ |
| `agent/` | ✅ | ✅ | ✅ |
| `exports/` | ✅ | ✅ | ✅ |

Единый sandbox — без read-only зон. Path traversal guard остаётся единственным барьером.

### 3.3 Лимиты (`config.py`)

| Setting | Default (draft) | Env |
|---------|-----------------|-----|
| `WORKSPACE_ROOT` | `data/workspaces` | `WORKSPACE_ROOT` |
| `WORKSPACE_MAX_BYTES_PER_USER` | 500 MB | `WORKSPACE_MAX_BYTES` |
| `WORKSPACE_MAX_FILE_BYTES` | 50 MB | `WORKSPACE_MAX_FILE_BYTES` |
| `WORKSPACE_MAX_FILES_PER_USER` | 1000 | `WORKSPACE_MAX_FILES` |
| `WORKSPACE_READ_PREVIEW_LINES` | 30 | `WORKSPACE_READ_PREVIEW_LINES` |
| `WORKSPACE_READ_LINES_MAX` | 500 | `WORKSPACE_READ_LINES_MAX` |
| `WORKSPACE_UPLOAD_MAX_BYTES` | 20 MB | `WORKSPACE_UPLOAD_MAX_BYTES` |
| `WORKSPACE_TTL_DAYS` | 0 (no auto) | `WORKSPACE_TTL_DAYS` |
| `WORKSPACE_GREP_MAX_MATCHES` | 200 | `WORKSPACE_GREP_MAX_MATCHES` |
| `WORKSPACE_GREP_MAX_FILES` | 100 | `WORKSPACE_GREP_MAX_FILES` |
| `WORKSPACE_UNZIP_MAX_FILES` | 500 | `WORKSPACE_UNZIP_MAX_FILES` |
| `WORKSPACE_UNZIP_MAX_BYTES` | 200 MB | `WORKSPACE_UNZIP_MAX_BYTES` |

Image reads reuse `IMAGE_MAX_BYTES` (same cap as Telegram inbound vision).

Telegram inbound лимит ≤ Bot API (50 MB doc, 10 MB photo compress).

### 3.4 Rate limits

| Class | Limit |
|-------|-------|
| read | 60/min per user |
| write | 30/min per user |
| delete | 10/min per user |

---

## 4. Inbound Telegram (Wave 1b)

| Handler | Действие |
|---------|----------|
| `F.document` | download → `uploads/{message_id}_{safe_filename}` → user message дополняется блоком `[file uploaded: path=…, size=…, mime=…]` |
| `F.photo` | Save → `uploads/{message_id}_photo.jpg` **+** vision inline (data_url как сейчас). User message: path + `[image]` |

Имя файла: sanitize + `ensure_filename_extension` + collision suffix `_2`.

Bot command (optional Wave 1): `/workspace` — usage + top-level list.

`/reset` history — **не** чистит workspace (отдельно `/clear_workspace` в WS-3).

---

## 5. Каталог tools

Naming: `workspace.{action}`. Tags: `workspace`, `read` | `write` | `filesystem`.

### 5.1 Wave WS-1 — read + list (6 tools)

#### `workspace.list_dir`

| | |
|---|---|
| **Параметры** | `path` (default `"."`), `recursive` (default false), `max_entries` (default 100) |
| **Returns** | `{path, type:"directory", entry_count, entries: [{name, type, path, size_bytes, mime_type?, modified_at, created_at}], truncated?}` |
| **Tags** | workspace, read |
| **Note** | Non-recursive: one level like `ls -l`. Each entry has same core fields as `stat` (without `file_ref`). Sorted: dirs first, then name |

#### `workspace.stat`

| | |
|---|---|
| **Параметры** | `path` (required) |
| **Returns** | см. ниже — **terminal-style metadata**, без чтения содержимого |
| **Tags** | workspace, read |

**`stat` = `ls -l` + `file` + exists check.** Агент вызывает перед read/send, чтобы понять что там.

**File:**
```json
{
  "ok": true,
  "path": "uploads/123_report.pdf",
  "exists": true,
  "type": "file",
  "zone": "uploads",
  "size_bytes": 1048576,
  "size_human": "1.0 MB",
  "mime_type": "application/pdf",
  "extension": ".pdf",
  "created_at": "2026-07-03T18:42:11+00:00",
  "modified_at": "2026-07-03T18:42:11+00:00",
  "accessed_at": "2026-07-04T10:01:00+00:00",
  "readable": true,
  "writable": true,
  "kind": "binary",
  "file_ref": "ws:…"
}
```

**Directory:**
```json
{
  "ok": true,
  "path": "agent",
  "exists": true,
  "type": "directory",
  "zone": "agent",
  "entry_count": 12,
  "size_bytes": null,
  "created_at": "…",
  "modified_at": "…",
  "readable": true,
  "writable": true
}
```

**Missing path:** `{ok: false, path, exists: false, error: "not_found"}` — не exception, чтобы агент мог проверить доступ.

**Text file extras (cheap):** `kind: "text"`, `total_lines` (line count without loading content — stream count), `preview_available: true`.

**Timestamps:** `Path.stat()` → ISO UTC. Windows: `st_birthtime` if available else `st_ctime` for `created_at`; `st_mtime` → `modified_at`.

**No separate `access` tool** — `stat` covers exists/readable/writable. Permissions are always R/W inside sandbox (§3.2).

#### `workspace.read_file`

| | |
|---|---|
| **Параметры** | `path`, `preview_lines` (optional, default from config, max 50) |
| **Returns** | **Text:** `{ok, path, kind:"text", mime_type, size, total_lines, preview_lines, lines: [{n, text}], hint}` — **preview only**, never full file. **Image:** `{ok, path, kind:"image", …}` — §5.5. **Binary:** `{ok, path, kind:"binary", mime_type, size, file_ref}` |
| **Tags** | workspace, read |

**Text — preview, не whole file:**
- Возвращает **только первые N строк** (default `WORKSPACE_READ_PREVIEW_LINES` = 30).
- Всегда включает `total_lines` (если файл text) и `hint`: «Use workspace.read_lines for lines X–Y».
- Файл 15 строк → все 15 в preview (это ok, файл маленький).
- Файл 10 000 строк → 30 строк + `total_lines: 10000`, без остального контента.
- **Никогда** не inline-ить весь файл в контекст, даже если он < 100 KB.

**Image branch** — без изменений (§5.5).

**Text detection:** reuse `tools/text_file_encoding.is_probably_text_file` + Drive-style decode.

#### `workspace.read_lines`

| | |
|---|---|
| **Параметры** | `path`, `start_line` (1-based, required), `end_line` (1-based, inclusive) **xor** `limit` (default 200) |
| **Returns** | `{ok, path, start_line, end_line, lines: [{n, text}], total_lines}` |
| **Tags** | workspace, read |
| **Guard** | Span `(end_line - start_line + 1)` ≤ `WORKSPACE_READ_LINES_MAX` (500). Example: lines 20–145 → `start_line=20, end_line=145` |
| **Note** | **Primary way** to read file content. `grep` → `read_lines` on hits |

#### `workspace.find`

| | |
|---|---|
| **Параметры** | `pattern` (glob, e.g. `agent/**/*.md`), `max_results` (default 50) |
| **Returns** | `{matches: [{path, size, modified_at}]}` |
| **Tags** | workspace, read |

#### `workspace.grep`

| | |
|---|---|
| **Параметры** | `pattern` (required, regex), `path` (file or dir, default `"."`), `glob` (optional, e.g. `*.py`), `ignore_case` (default false), `max_matches` (default 200), `context_lines` (default 0, max 3) |
| **Returns** | `{pattern, path, matches: [{path, line, text, context_before?, context_after?}], files_scanned, truncated}` |
| **Tags** | workspace, read |
| **Note** | Only **text** files (same heuristic as `read_file`). Skips binary. Walk dir with `WORKSPACE_GREP_MAX_FILES` cap. No ripgrep subprocess — stdlib `re` line-by-line |

#### `workspace.usage`

| | |
|---|---|
| **Параметры** | — |
| **Returns** | `{bytes_used, bytes_limit, file_count, file_limit, paths: {uploads, agent, exports}}` |
| **Tags** | workspace, read |

---

### 5.2 Wave WS-2 — write + structure (5 tools)

#### `workspace.write_file`

| | |
|---|---|
| **Параметры** | `path`, `content_text` **xor** `content_base64`, `mime_type` (optional), `overwrite` (default true) |
| **Returns** | `{ok, path, size, mime_type, file_ref, created}` |
| **Tags** | workspace, write |
| **Guard** | quota check; path must stay inside user root |

#### `workspace.append_file`

| | |
|---|---|
| **Параметры** | `path`, `content_text` |
| **Returns** | `{ok, path, size}` |
| **Tags** | workspace, write |
| **Note** | Только text; для логов |

#### `workspace.mkdir`

| | |
|---|---|
| **Параметры** | `path`, `parents` (default true) |
| **Returns** | `{ok, path, created}` |
| **Tags** | workspace, write |

#### `workspace.move`

| | |
|---|---|
| **Параметры** | `from_path`, `to_path`, `overwrite` (default false) |
| **Returns** | `{ok, from_path, to_path}` |
| **Tags** | workspace, write |

#### `workspace.copy`

| | |
|---|---|
| **Параметры** | `from_path`, `to_path`, `overwrite` (default false) |
| **Returns** | `{ok, from_path, to_path}` |
| **Tags** | workspace, write |

---

### 5.3 Wave WS-3 — delete + maintenance (3 tools)

#### `workspace.delete`

| | |
|---|---|
| **Параметры** | `path`, `recursive` (default false for dirs), `confirm` (required true for dir/non-empty) |
| **Returns** | `{ok, path, deleted}` |
| **Tags** | workspace, write |
| **Guard** | `confirm=true` required; quota update after delete |

#### `workspace.clear`

| | |
|---|---|
| **Параметры** | `zone` (`agent` \| `exports` \| `all`), `confirm` (required true) |
| **Returns** | `{ok, bytes_freed, files_removed}` |
| **Tags** | workspace, write |
| **Note** | Bot command `/clear_workspace` → same |

#### `workspace.import_from_file_ref`

| | |
|---|---|
| **Параметры** | `file_ref`, `path` (destination under workspace) |
| **Returns** | `{ok, path, size}` |
| **Tags** | workspace, write |
| **Note** | Копирует из RunFileStore текущего run → workspace (Drive download persist) |

#### `workspace.unzip`

| | |
|---|---|
| **Параметры** | `path` (`.zip` in workspace), `dest` (optional dir, default `{zip_stem}/`), `overwrite` (default false) |
| **Returns** | `{ok, path, dest, files_extracted, bytes_extracted, entries: [{path, size}]}` |
| **Tags** | workspace, write |
| **Guard** | Zip-slip blocked (every member resolves under `dest`). Totals capped: `WORKSPACE_UNZIP_MAX_FILES`, `WORKSPACE_UNZIP_MAX_BYTES` (sum uncompressed). Reject encrypted zip. Stdlib `zipfile` only — no shell |

---

### 5.4 Delivery (расширение существующего)

#### `telegram.send_file` (extend)

Добавить optional `path` (workspace relative) **xor** `file_ref`:

```json
{"path": "agent/report.pdf", "caption": "..."}
```

Resolver: path → read bytes → queue (BOM + extension как сейчас).

---

### 5.5 Vision injection (workspace images)

Когда `workspace.read_file` возвращает `kind:"image"`, pipeline:

```
use_tool(workspace.read_file, {path: "uploads/photo.jpg"})
  → tool JSON (metadata only)
  → agent/loop.py: pending_vision from RunContext or parse tool result
  → messages += user multipart [text + image_url data_url]
  → next LLM turn sees image like Telegram inbound
```

Shared code:
- `tools/workspace/vision.py` — `load_workspace_image_data_url(user_id, path) -> str`
- Reuse `bot/vision.build_user_message_content`, `image_max_bytes()`

Prompts: «To analyze a saved image, call `workspace.read_file` on its path — vision loads automatically.»

**Text workflow in prompts:**
1. `read_file` — peek (first ~30 lines + `total_lines`)
2. `read_lines` — read range, e.g. `{start_line: 20, end_line: 145}`
3. `grep` — find line numbers, then `read_lines` around matches

---

## 6. Tool graph (prompts)

```
Inbound Telegram file     →  workspace.stat → read_file (preview) | read_lines
workspace.find            →  workspace.read_file (preview) → workspace.read_lines
uploads/*.jpg             →  workspace.read_file → vision inject (§5.5)
workspace.grep            →  workspace.read_file (narrow files)
workspace.unzip             →  workspace.list_dir → workspace.read_file
workspace.write_file        →  telegram.send_file(path=…)
google.drive.export_file    →  workspace.import_from_file_ref (Wave 2) → edit → telegram.send_file
workspace.read_lines        →  workspace.append_file (logs)
```

search_tools tags:

```json
{"mode": "catalog", "tags": ["workspace"]}
{"mode": "catalog", "tags": ["workspace", "read"]}
{"mode": "rank", "query": "list files in sandbox", "tags": ["workspace"]}
```

---

## 7. Реализация — файлы

```
tools/workspace/
  paths.py              # resolve, sanitize, zone checks
  store.py              # list, read, write, delete, quota, unzip, grep
  refs.py               # workspace file_ref registry (per run or persistent index)
  mime.py               # reuse filename_utils, text_file_encoding
  vision.py             # workspace image → data_url (IMAGE_MAX_BYTES)

tools/builtins/workspace/
  read_tools.py         # list_dir, stat, read_file, read_lines, find, grep, usage
  write_tools.py        # write, append, mkdir, move, copy
  maintain_tools.py     # delete, clear, import_from_file_ref, unzip
  __init__.py           # WORKSPACE_TOOLS tuple

agent/loop.py           # after tool turn: inject vision user message for image reads
bot/inbound_files.py    # save telegram document/photo
bot/workspace_notify.py # format [file uploaded: …] for agent user message

config.py               # WORKSPACE_* constants + Settings fields
agent/prompts.py        # Workspace workflow section
agent/tool_search_hints.py  # workspace.* → tags ["workspace"]
test_workspace_*.py
```

### 7.1 Waves implementation

| Wave | Deliverable |
|------|-------------|
| **WS-0** | `paths.py`, `store.py`, config, tests path security |
| **WS-1a** | read tools (list, stat, read_file preview, read_lines, usage) |
| **WS-1b** | inbound `F.document` + photo save + vision |
| **WS-2** | write tools (write, append, mkdir, move) |
| **WS-3** | find, grep, copy, clear, import_from_file_ref, unzip, extend send_file |
| **WS-4** | TTL cleanup job, `/clear_workspace`, Drive→exports hook |

---

## 8. Решения (зафиксировано)

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | Lifetime | **Per-user persistent** — файлы живут между сообщениями |
| 2 | `uploads/` | **Read-write** — агент пишет в любую зону sandbox |
| 3 | Фото inbound | **Save в `uploads/` + vision inline** (оба) |
| 4 | `/reset` | **Не чистит workspace** — отдельно `/clear_workspace` (WS-3) |
| 5 | RunFileStore | **Раздельно** на v1; `import_from_file_ref` для копирования при необходимости |
| 6 | Workspace image read | **`read_file` → vision inject** (user multipart, как Telegram), не base64 в tool JSON |
| 7 | Search in files | **`workspace.grep`** (regex, text files only) |
| 8 | Text read model | **`read_file` = preview only**; full/range via **`read_lines`** (`start_line` + `end_line`) |
| 9 | File metadata | **`workspace.stat`** = exists, size, mime, created/modified, readable/writable, line count; **`list_dir`** = same per entry |
| 10 | Archives | **`workspace.unzip`** (zip-slip safe, stdlib) |

Wave 1 scope: **WS-0 + WS-1a + WS-1b + WS-2** (read + inbound + write базовый).

---

## 9. Итого tools

| # | Tool | Wave | R/W |
|---|------|------|-----|
| 1 | `workspace.list_dir` | WS-1 | R |
| 2 | `workspace.stat` | WS-1 | R |
| 3 | `workspace.read_file` | WS-1 | R |
| 4 | `workspace.read_lines` | WS-1 | R |
| 5 | `workspace.usage` | WS-1 | R |
| 6 | `workspace.find` | WS-3 | R |
| 7 | `workspace.grep` | WS-3 | R |
| 8 | `workspace.write_file` | WS-2 | W |
| 9 | `workspace.append_file` | WS-2 | W |
| 10 | `workspace.mkdir` | WS-2 | W |
| 11 | `workspace.move` | WS-2 | W |
| 12 | `workspace.copy` | WS-3 | W |
| 13 | `workspace.delete` | WS-3 | W |
| 14 | `workspace.clear` | WS-3 | W |
| 15 | `workspace.import_from_file_ref` | WS-3 | W |
| 16 | `workspace.unzip` | WS-3 | W |
| — | `telegram.send_file` (+ `path`) | WS-3 | delivery |

**Total: 16 new + 1 extended.**

**`read_file` image vision:** not a separate tool — built into read + agent loop (§5.5).

---

## 10. Tests (minimum)

- Path traversal blocked (`../etc/passwd`, symlink escape)
- Quota enforced (file size, total bytes, file count)
- Path resolve: all zones writable, no escape
- UTF-8 BOM on text send from workspace
- Extension added on send (.pdf, .md)
- Inbound document saved with safe name
- `file_ref` roundtrip read → send
- `read_file` on `.jpg` → tool JSON `kind:image` + synthetic user message with `image_url` (vision)
- `grep` finds pattern in text files, skips binary
- `unzip` extracts under dest, rejects zip-slip and over quota

---

## 11. Done criteria v1

- [ ] User sends `.pdf` → agent sees path, can `read_file` / `stat`, `telegram.send_file(path=…)` back
- [ ] Agent creates `agent/notes.md`, reads it next turn
- [ ] Agent reads `uploads/photo.jpg` next turn → vision works like Telegram photo
- [ ] `workspace.grep` + `workspace.unzip` work in sandbox
- [ ] No access outside `data/workspaces/{user_id}/`
- [ ] Prompts + search tags documented
- [ ] Tests green
