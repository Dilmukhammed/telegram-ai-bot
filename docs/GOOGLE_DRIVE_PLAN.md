# Google Drive — план интеграции

Полный каталог tools, волны реализации, расширение OAuth и технические детали.  
Файл для ревью перед кодом. **Не MVP** — целевой scope «готов к продаже»: агент управляет файлами, папками, доступом и shared drives через **Drive API v3** так же полно, как сейчас Gmail и Calendar.

---

## 1. Цель

Telegram-бот (Hermes Agent) получает **полный доступ к Google Drive** пользователя через **тот же Google OAuth 2.0**, что Calendar и Gmail.

Агент вызывает tools через существний flow: `search_tools` → `use_tool`.  
Tool graph — **позже** (curated edges: `search_files` → `get_file` → `download_file` / `export_file` → `share_file`).

```json
{"mode": "catalog", "tags": ["google", "drive", "read"]}
{"mode": "rank", "query": "find pdf in folder", "tags": ["google", "drive"]}
{"mode": "rank", "query": "share file with email", "tags": ["google", "drive", "permissions"]}
```

Пользователь может:

- искать и листать файлы / папки (Drive query `q`)
- читать метаданные, скачивать бинарники, экспортировать Google Docs/Sheets/Slides в text/PDF
- создавать папки, загружать файлы, копировать, перемещать, переименовывать
- trash / restore / permanent delete (с guard)
- делиться файлами (permissions: reader/writer/commenter)
- комментарии и replies на файлах
- revisions (для blob-файлов)
- отслеживать changes (incremental sync)
- shared drives (Team Drives): list/create/update/delete/hide
- labels на файлах (Drive labels API)
- *(опционально, Workspace)* access proposals и file approvals

**Связь с Sheets:** таблицы — это Drive-файлы (`mimeType` Google Sheet). На старте: **`export_file`** → CSV/text для LLM. Отдельный **Sheets API** — следующий план (`GOOGLE_SHEETS_PLAN.md`).

---

## 2. Auth — расширение существующего OAuth

Сейчас: Calendar + Gmail scopes. Drive API **не** доступен без `drive` scope.

### 2.1 Целевые OAuth scopes (единый consent)

| Scope | Зачем |
|-------|-------|
| `https://www.googleapis.com/auth/calendar` | уже есть — Calendar |
| `https://www.googleapis.com/auth/gmail.modify` | уже есть — Gmail |
| `https://www.googleapis.com/auth/gmail.settings.basic` | уже есть — Gmail settings |
| `https://www.googleapis.com/auth/drive` | **новый** — полный read/write Drive (My Drive + shared drives user can access) |

**Почему `drive`, а не `drive.file` / `drive.readonly`:**

| Scope | Ограничение | Подходит? |
|-------|-------------|-----------|
| `drive.readonly` | только чтение | нет — нужен upload/share |
| `drive.file` | только файлы, созданные/открытые приложением | нет — агент должен искать **существующие** файлы пользователя |
| `drive.metadata.readonly` | без content | нет |
| **`drive`** | полный доступ к файлам пользователя | **да** |

**Не используем по умолчанию:**

| Scope | Зачем |
|-------|-------|
| `drive.appdata` | hidden app folder — не нужен чат-боту |
| `drive.photos.readonly` | Google Photos — отдельный продукт, restricted |

**Env (comma-separated):**

```env
GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/gmail.settings.basic,https://www.googleapis.com/auth/drive
```

→ `config.py`, `.env.example`, `DEFAULT_GOOGLE_OAUTH_SCOPES`

### 2.2 Re-consent для существующих пользователей

- Старый refresh token **без** `drive` → Drive tools: `{ok: false, error: "Drive scope missing — run /connect_google again"}`
- `/connect_google` с `prompt=consent` → consent screen: Calendar + Gmail + **Drive**
- `google.auth.status` → `drive_ready: true/false` (аналог `gmail_ready`)

### 2.3 Bot commands (без изменений имён)

| Command | Действие |
|---------|----------|
| `/connect_google` | OAuth (Calendar + Gmail + **Drive**) |
| `/disconnect_google` | Revoke + delete token (всё) |
| `/google_status` | connected, email, scopes, `gmail_ready`, **`drive_ready`** |

Текст `/connect_google` и `/google_status` обновить: «Google Calendar, Gmail и Drive».

### 2.4 Auth tools (3) — расширение

| Tool | Изменение |
|------|-----------|
| `google.auth.status` | + `drive_ready`, полный список scopes |
| `google.auth.connect_url` | тот же URL, больше scopes |
| `google.auth.disconnect` | без изменений |

### 2.5 Инфраструктура (новое)

```
tools/builtins/google/
  auth.py                    # + build_drive_service(), get_drive_service()
  token_store.py             # без изменений схемы
  drive_client.py            # async wrapper, supportsAllDrives=true по умолчанию
  drive_serialize.py         # File/Permission/Comment → compact dict для LLM
  drive_files.py             # list/get/download/export/create/update/copy
  drive_upload.py            # multipart / resumable helpers
  drive_permissions.py
  drive_comments.py
  drive_revisions.py
  drive_changes.py
  drive_shared.py            # shared drives (drives.*)
  drive_labels.py
  drive_workspace.py         # accessproposals + approvals (optional)
  drive_tools.py             # ToolSpec registrations
```

**GCP:** Enable **Google Drive API** в том же проекте.

**OAuth consent screen:** добавить scope `drive` (Sensitive scope — Testing mode + test users, как Gmail).

---

## 3. Схема тегов

| Tag | Когда |
|-----|-------|
| `google` | **Все** Google tools |
| `drive` | **Все** `google.drive.*` |
| `read` | list, get, search, download, export |
| `write` | create, upload, update, copy, move, trash, delete |
| `permissions` | share, ACL |
| `comments` | comments + replies |
| `revisions` | file version history |
| `changes` | incremental change feed |
| `shared_drives` | Team / shared drives CRUD |
| `labels` | file labels |
| `workspace` | access proposals, approvals (Google Workspace) |
| `settings` | about, apps list |
| `auth` | OAuth tools |

**Фильтр:** `tags=["google", "drive", "read"]` → AND по всем tags.

**Catalog:** при 60+ drive tools **всегда** с узкими tags (`read` / `write` / `permissions`), не `tags=["google","drive"]` alone (truncation 50).

Добавить в `tools/search_enrichment.py`:

```python
TAG_HINT_PROFILES += (
    ("google", "drive"),
    ("google", "drive", "read"),
    ("google", "drive", "write"),
)
```

---

## 4. Окончательный каталог tools — **62 core** (+ 11 optional Workspace)

Naming: `google.drive.<action>`  
Все handlers: `supportsAllDrives=True`, `includeItemsFromAllDrives=True` где API поддерживает.

**Не реализуем** (не для Telegram-бота):

| API method | Причина skip |
|------------|--------------|
| `files.watch`, `changes.watch` | Webhooks / push channels |
| `channels.stop` | companion to watch |
| `files.generateCseToken` | Client-side encryption enterprise |
| `operations.get` | только для long-running ops — добавим если понадобится resumable download UI |

---

### 4.1 About (1)

#### `google.drive.get_about`

| | |
|---|---|
| **API** | `about.get` |
| **Описание** | User, storage quota, max upload size, Drive capabilities |
| **Returns** | `{user, storage_quota, max_import_sizes, can_create_drives, ...}` compact |
| **Tags** | `google`, `drive`, `settings`, `read` |
| **Wave** | Drive-1 |

---

### 4.2 Files — чтение (10)

#### `google.drive.search_files`

| | |
|---|---|
| **API** | `files.list` + `q` |
| **Описание** | Главный search tool. Drive query syntax |
| **Параметры** | `q` (required), `page_size` (default 10, max 100), `page_token`, `order_by`, `corpora` (`user`\|`drive`\|`allDrives`), `drive_id`, `include_trashed` (default false) |
| **Returns** | `{count, files: [compact_file_summary, ...], next_page_token}` — **без content** |
| **Wave** | Drive-1 |
| **Note** | «найди PDF от бухгалтерии» → `q="fullText contains 'invoice' and mimeType='application/pdf'"` |

#### `google.drive.list_files`

| | |
|---|---|
| **API** | `files.list` без q или с folder filter |
| **Параметры** | `folder_id` (optional — `'<id>' in parents`), `page_size`, `page_token`, `order_by` |
| **Wave** | Drive-1 |

#### `google.drive.get_file`

| | |
|---|---|
| **API** | `files.get` |
| **Параметры** | `file_id` (required), `fields` optional preset |
| **Returns** | compact metadata: id, name, mimeType, size, parents, starred, trashed, webViewLink, webContentLink, owners, modifiedTime, shortcutDetails |
| **Wave** | Drive-1 |

#### `google.drive.download_file`

| | |
|---|---|
| **API** | `files.get` alt=media **или** `files.download` (POST) |
| **Параметры** | `file_id` |
| **Returns** | `{filename, mime_type, size, text}` или `{text_base64}` для binary; `{ok: false, error: "too large"}` если > cap |
| **Wave** | Drive-1 |
| **Guard** | `DRIVE_MAX_DOWNLOAD_BYTES` default 10 MB; text decode UTF-8 / latin-1 fallback |

#### `google.drive.export_file`

| | |
|---|---|
| **API** | `files.export` |
| **Параметры** | `file_id`, `mime_type` (default `text/plain` for Docs; `text/csv` for Sheets) |
| **Returns** | `{mime_type, text}` truncated `DRIVE_MAX_EXPORT_CHARS` |
| **Wave** | Drive-1 |
| **Note** | Google Docs/Sheets/Slides **не** скачиваются через download — только export |

#### `google.drive.list_folder`

| | |
|---|---|
| **API** | Sugar → `files.list` q=`'<folder_id>' in parents and trashed=false` |
| **Параметры** | `folder_id` (default root / `root`) |
| **Wave** | Drive-1 |

#### `google.drive.list_starred`

| | |
|---|---|
| **API** | Sugar → `q="starred=true and trashed=false"` |
| **Wave** | Drive-1 |

#### `google.drive.list_trash`

| | |
|---|---|
| **API** | Sugar → `q="trashed=true"` |
| **Wave** | Drive-1 |

#### `google.drive.list_shared_with_me`

| | |
|---|---|
| **API** | Sugar → `q="sharedWithMe=true and trashed=false"` |
| **Wave** | Drive-1 |

#### `google.drive.list_recent`

| | |
|---|---|
| **API** | Sugar → `files.list` orderBy=`viewedByMeTime desc` |
| **Параметры** | `page_size` (default 10) |
| **Wave** | Drive-1 |

---

### 4.3 Files — запись (15)

#### `google.drive.create_folder`

| | |
|---|---|
| **API** | `files.create` mimeType=`application/vnd.google-apps.folder` |
| **Параметры** | `name` (required), `parent_id` (optional) |
| **Wave** | Drive-2 |

#### `google.drive.create_file`

| | |
|---|---|
| **API** | `files.create` metadata-only (empty Google Doc optional via mimeType) |
| **Параметры** | `name`, `mime_type`, `parent_id`, `description` |
| **Wave** | Drive-2 |

#### `google.drive.upload_file`

| | |
|---|---|
| **API** | `files.create` multipart или `files.update` upload |
| **Параметры** | `name`, `parent_id`, `mime_type`, `content_text` **или** `content_base64` |
| **Returns** | `{id, name, webViewLink, size}` |
| **Wave** | Drive-2 |
| **Guard** | max upload size from about + config cap |

#### `google.drive.update_file_metadata`

| | |
|---|---|
| **API** | `files.update` metadata only |
| **Параметры** | `file_id`, `name`, `description`, `starred`, `properties` (dict) |
| **Wave** | Drive-2 |

#### `google.drive.update_file_content`

| | |
|---|---|
| **API** | `files.update` with media |
| **Параметры** | `file_id`, `content_text` or `content_base64`, `mime_type` |
| **Wave** | Drive-2 |
| **Note** | Не для Google Workspace native types (Docs/Sheets) — для них Sheets/Docs API или export→edit→re-upload |

#### `google.drive.copy_file`

| | |
|---|---|
| **API** | `files.copy` |
| **Параметры** | `file_id`, `name` (optional), `parent_id` (optional) |
| **Wave** | Drive-2 |

#### `google.drive.move_file`

| | |
|---|---|
| **API** | Sugar → `files.update` addParents + removeParents |
| **Параметры** | `file_id`, `new_parent_id`, `remove_parent_id` (optional) |
| **Wave** | Drive-2 |

#### `google.drive.rename_file`

| | |
|---|---|
| **API** | Sugar → `files.update` name |
| **Параметры** | `file_id`, `name` |
| **Wave** | Drive-2 |

#### `google.drive.star_file` / `google.drive.unstar_file`

| | |
|---|---|
| **API** | Sugar → update `starred=true/false` |
| **Wave** | Drive-2 |

#### `google.drive.trash_file`

| | |
|---|---|
| **API** | Sugar → `files.update` trashed=true |
| **Wave** | Drive-2 |

#### `google.drive.untrash_file`

| | |
|---|---|
| **API** | Sugar → trashed=false |
| **Wave** | Drive-2 |

#### `google.drive.delete_file`

| | |
|---|---|
| **API** | `files.delete` |
| **Параметры** | `file_id`, **`confirm=true`** (required) |
| **Wave** | Drive-2 |
| **Guard** | permanent delete, не корзина |

#### `google.drive.empty_trash`

| | |
|---|---|
| **API** | `files.emptyTrash` |
| **Параметры** | **`confirm=true`** (required) |
| **Wave** | Drive-2 |

#### `google.drive.create_shortcut`

| | |
|---|---|
| **API** | `files.create` mimeType=`application/vnd.google-apps.shortcut` |
| **Параметры** | `name`, `target_file_id`, `parent_id` |
| **Wave** | Drive-2 |

#### `google.drive.generate_file_ids`

| | |
|---|---|
| **API** | `files.generateIds` |
| **Параметры** | `count` (default 1, max 10) |
| **Wave** | Drive-2 |

---

### 4.4 Permissions / sharing (5)

#### `google.drive.list_permissions`

| | |
|---|---|
| **API** | `permissions.list` |
| **Параметры** | `file_id` |
| **Returns** | `{count, permissions: [{id, type, role, emailAddress, domain, displayName}]}` |
| **Wave** | Drive-3 |

#### `google.drive.get_permission`

| | |
|---|---|
| **API** | `permissions.get` |
| **Wave** | Drive-3 |

#### `google.drive.share_file`

| | |
|---|---|
| **API** | Sugar → `permissions.create` |
| **Параметры** | `file_id`, `role` (`reader`\|`writer`\|`commenter`), `type` (`user`\|`group`\|`domain`\|`anyone`), `email` (if user/group), `send_notification` (default true) |
| **Wave** | Drive-3 |

#### `google.drive.update_permission`

| | |
|---|---|
| **API** | `permissions.update` |
| **Параметры** | `file_id`, `permission_id`, `role` |
| **Wave** | Drive-3 |

#### `google.drive.remove_permission`

| | |
|---|---|
| **API** | `permissions.delete` |
| **Параметры** | `file_id`, `permission_id` |
| **Wave** | Drive-3 |

---

### 4.5 Comments (5)

#### `google.drive.list_comments`

| | |
|---|---|
| **API** | `comments.list` |
| **Параметры** | `file_id`, `page_size`, `include_deleted` |
| **Wave** | Drive-4 |

#### `google.drive.get_comment`

| | |
|---|---|
| **API** | `comments.get` |
| **Wave** | Drive-4 |

#### `google.drive.create_comment`

| | |
|---|---|
| **API** | `comments.create` |
| **Параметры** | `file_id`, `content` (plain text) |
| **Wave** | Drive-4 |

#### `google.drive.update_comment`

| | |
|---|---|
| **API** | `comments.update` |
| **Wave** | Drive-4 |

#### `google.drive.delete_comment`

| | |
|---|---|
| **API** | `comments.delete` |
| **Wave** | Drive-4 |

---

### 4.6 Replies (5)

#### `google.drive.list_replies`

| | |
|---|---|
| **API** | `replies.list` |
| **Параметры** | `file_id`, `comment_id` |
| **Wave** | Drive-4 |

#### `google.drive.get_reply`

| | |
|---|---|
| **API** | `replies.get` |
| **Wave** | Drive-4 |

#### `google.drive.create_reply`

| | |
|---|---|
| **API** | `replies.create` |
| **Wave** | Drive-4 |

#### `google.drive.update_reply`

| | |
|---|---|
| **API** | `replies.update` |
| **Wave** | Drive-4 |

#### `google.drive.delete_reply`

| | |
|---|---|
| **API** | `replies.delete` |
| **Wave** | Drive-4 |

---

### 4.7 Revisions (4)

#### `google.drive.list_revisions`

| | |
|---|---|
| **API** | `revisions.list` |
| **Параметры** | `file_id` |
| **Note** | Для native Google Docs revisions list может быть incomplete — document in tool description |
| **Wave** | Drive-5 |

#### `google.drive.get_revision`

| | |
|---|---|
| **API** | `revisions.get` |
| **Wave** | Drive-5 |

#### `google.drive.update_revision`

| | |
|---|---|
| **API** | `revisions.update` |
| **Параметры** | `file_id`, `revision_id`, `keep_forever` |
| **Wave** | Drive-5 |

#### `google.drive.delete_revision`

| | |
|---|---|
| **API** | `revisions.delete` |
| **Параметры** | `file_id`, `revision_id`, **`confirm=true`** |
| **Wave** | Drive-5 |

---

### 4.8 Changes (2)

#### `google.drive.get_changes_start_token`

| | |
|---|---|
| **API** | `changes.getStartPageToken` |
| **Returns** | `{start_page_token}` |
| **Wave** | Drive-5 |

#### `google.drive.list_changes`

| | |
|---|---|
| **API** | `changes.list` |
| **Параметры** | `page_token`, `drive_id` (optional shared drive), `page_size` |
| **Returns** | `{changes: [compact], next_page_token, new_start_page_token}` |
| **Wave** | Drive-5 |

---

### 4.9 Shared drives (7)

#### `google.drive.list_shared_drives`

| | |
|---|---|
| **API** | `drives.list` |
| **Wave** | Drive-6 |

#### `google.drive.get_shared_drive`

| | |
|---|---|
| **API** | `drives.get` |
| **Wave** | Drive-6 |

#### `google.drive.create_shared_drive`

| | |
|---|---|
| **API** | `drives.create` |
| **Параметры** | `name`, `request_id` (uuid — idempotency) |
| **Wave** | Drive-6 |

#### `google.drive.update_shared_drive`

| | |
|---|---|
| **API** | `drives.update` |
| **Wave** | Drive-6 |

#### `google.drive.delete_shared_drive`

| | |
|---|---|
| **API** | `drives.delete` |
| **Параметры** | `drive_id`, **`confirm=true`** |
| **Wave** | Drive-6 |

#### `google.drive.hide_shared_drive`

| | |
|---|---|
| **API** | `drives.hide` |
| **Wave** | Drive-6 |

#### `google.drive.unhide_shared_drive`

| | |
|---|---|
| **API** | `drives.unhide` |
| **Wave** | Drive-6 |

---

### 4.10 Labels (2)

#### `google.drive.list_file_labels`

| | |
|---|---|
| **API** | `files.listLabels` |
| **Параметры** | `file_id` |
| **Wave** | Drive-7 |

#### `google.drive.modify_file_labels`

| | |
|---|---|
| **API** | `files.modifyLabels` |
| **Параметры** | `file_id`, `add_labels[]`, `remove_labels[]` |
| **Wave** | Drive-7 |

---

### 4.11 Apps (2)

#### `google.drive.list_apps`

| | |
|---|---|
| **API** | `apps.list` |
| **Описание** | Connected Drive apps — редко нужно агенту |
| **Wave** | Drive-7 |

#### `google.drive.get_app`

| | |
|---|---|
| **API** | `apps.get` |
| **Wave** | Drive-7 |

---

### 4.12 Workspace-only — optional (11)

> Требуют Google Workspace / specific policies. Реализовать **Drive-8** только если есть реальный use case.

| Tool | API | Wave |
|------|-----|------|
| `google.drive.list_access_proposals` | `accessproposals.list` | Drive-8 |
| `google.drive.get_access_proposal` | `accessproposals.get` | Drive-8 |
| `google.drive.resolve_access_proposal` | `accessproposals.resolve` | Drive-8 |
| `google.drive.list_approvals` | `approvals.list` | Drive-8 |
| `google.drive.get_approval` | `approvals.get` | Drive-8 |
| `google.drive.start_approval` | `approvals.start` | Drive-8 |
| `google.drive.approve_file` | `approvals.approve` | Drive-8 |
| `google.drive.decline_approval` | `approvals.decline` | Drive-8 |
| `google.drive.cancel_approval` | `approvals.cancel` | Drive-8 |
| `google.drive.comment_approval` | `approvals.comment` | Drive-8 |
| `google.drive.reassign_approval` | `approvals.reassign` | Drive-8 |

**Core total: 62 tools.** With Workspace optional: **73 tools.**

---

## 5. Сводная таблица (62 core)

| # | Tool | Wave | R/W | Tags | API |
|---|------|------|-----|------|-----|
| 1 | `google.drive.get_about` | Drive-1 | R | drive, settings, read | about.get |
| 2 | `google.drive.search_files` | Drive-1 | R | drive, read | files.list |
| 3 | `google.drive.list_files` | Drive-1 | R | drive, read | files.list |
| 4 | `google.drive.get_file` | Drive-1 | R | drive, read | files.get |
| 5 | `google.drive.download_file` | Drive-1 | R | drive, read | files.download / get media |
| 6 | `google.drive.export_file` | Drive-1 | R | drive, read | files.export |
| 7 | `google.drive.list_folder` | Drive-1 | R | drive, read | sugar |
| 8 | `google.drive.list_starred` | Drive-1 | R | drive, read | sugar |
| 9 | `google.drive.list_trash` | Drive-1 | R | drive, read | sugar |
| 10 | `google.drive.list_shared_with_me` | Drive-1 | R | drive, read | sugar |
| 11 | `google.drive.list_recent` | Drive-1 | R | drive, read | sugar |
| 12 | `google.drive.create_folder` | Drive-2 | W | drive, write | files.create |
| 13 | `google.drive.create_file` | Drive-2 | W | drive, write | files.create |
| 14 | `google.drive.upload_file` | Drive-2 | W | drive, write | files.create upload |
| 15 | `google.drive.update_file_metadata` | Drive-2 | W | drive, write | files.update |
| 16 | `google.drive.update_file_content` | Drive-2 | W | drive, write | files.update media |
| 17 | `google.drive.copy_file` | Drive-2 | W | drive, write | files.copy |
| 18 | `google.drive.move_file` | Drive-2 | W | drive, write | sugar |
| 19 | `google.drive.rename_file` | Drive-2 | W | drive, write | sugar |
| 20 | `google.drive.star_file` | Drive-2 | W | drive, write | sugar |
| 21 | `google.drive.unstar_file` | Drive-2 | W | drive, write | sugar |
| 22 | `google.drive.trash_file` | Drive-2 | W | drive, write | sugar |
| 23 | `google.drive.untrash_file` | Drive-2 | W | drive, write | sugar |
| 24 | `google.drive.delete_file` | Drive-2 | W | drive, write | files.delete |
| 25 | `google.drive.empty_trash` | Drive-2 | W | drive, write | files.emptyTrash |
| 26 | `google.drive.create_shortcut` | Drive-2 | W | drive, write | files.create |
| 27 | `google.drive.generate_file_ids` | Drive-2 | W | drive, write | files.generateIds |
| 28 | `google.drive.list_permissions` | Drive-3 | R | drive, permissions, read | permissions.list |
| 29 | `google.drive.get_permission` | Drive-3 | R | drive, permissions, read | permissions.get |
| 30 | `google.drive.share_file` | Drive-3 | W | drive, permissions, write | permissions.create |
| 31 | `google.drive.update_permission` | Drive-3 | W | drive, permissions, write | permissions.update |
| 32 | `google.drive.remove_permission` | Drive-3 | W | drive, permissions, write | permissions.delete |
| 33–37 | comments ×5 | Drive-4 | mixed | drive, comments | comments.* |
| 38–42 | replies ×5 | Drive-4 | mixed | drive, comments | replies.* |
| 43–46 | revisions ×4 | Drive-5 | mixed | drive, revisions | revisions.* |
| 47–48 | changes ×2 | Drive-5 | R | drive, changes, read | changes.* |
| 49–55 | shared drives ×7 | Drive-6 | mixed | drive, shared_drives | drives.* |
| 56–57 | labels ×2 | Drive-7 | mixed | drive, labels | files.listLabels/modifyLabels |
| 58–59 | apps ×2 | Drive-7 | R | drive, settings, read | apps.* |

*(Comments/replies/revisions rows collapsed in table for brevity — full names in §4.)*

---

## 6. Волны реализации

### Drive-0 — OAuth + infra

1. GCP: Enable Drive API
2. OAuth consent: add `drive` scope
3. `.env` / `config.py`: расширить `GOOGLE_OAUTH_SCOPES`
4. `auth.py`: `get_drive_service()`, `drive_ready` check
5. `drive_client.py`, `drive_serialize.py` skeleton
6. `/connect_google`, `/google_status` copy update
7. Re-connect test user

**Deliverable:** OAuth готов, tools return scope error until Drive-1.

---

### Drive-1 — Read core (11 tools) ✅

Tools: §4.1 + §4.2 (about + all read/list/export/download).

**Deliverable:** «найди файл X», «покажи содержимое doc/pdf», «что в папке Y».

---

### Drive-2 — Write files (16 tools) ✅

Tools: §4.3 (create, upload, move, trash, delete, …).

1. `drive_upload.py` — multipart for small files
2. Guards: `confirm=true` on permanent delete / empty_trash
3. Agent prompt block для Drive

**Deliverable:** «создай папку», «загрузи заметку», «перемести в архив».

---

### Drive-3 — Permissions (5 tools) ✅

**Deliverable:** «поделись с email@… read-only».

---

### Drive-4 — Comments + replies (10 tools) ✅

**Deliverable:** «оставь комментарий на документе».

---

### Drive-5 — Revisions + changes (6 tools) ✅

**Deliverable:** «что изменилось с прошлого раза», version control для PDF.

---

### Drive-6 — Shared drives (7 tools) ✅

**Deliverable:** работа с Team Drive корпоративного аккаунта.

---

### Drive-7 — Labels + apps (4 tools) ✅

**Deliverable:** edge admin/metadata.

---

### Drive-8 — Workspace optional (11 tools) ✅

Only if needed. Tag: `workspace`.

---

## 7. Технические детали

### 7.1 Serialize для LLM

```python
# drive_serialize.py
compact_file_summary(file) -> {
  "id": "...",
  "name": "...",
  "mime_type": "...",
  "size": 12345,
  "modified_time": "2026-07-03T10:00:00Z",
  "parents": ["folderId"],
  "starred": false,
  "trashed": false,
  "web_view_link": "https://drive.google.com/...",
  "owners": ["user@example.com"],
  "shortcut_target_id": null,
}
```

- **Не** отдавать raw binary в JSON без cap
- `webViewLink` — для финального ответа агента (inline buttons из текста, как Gmail)

### 7.2 MIME types для export

| Google type | Default export |
|-------------|----------------|
| Google Doc | `text/plain` |
| Google Sheet | `text/csv` |
| Google Slides | `text/plain` |
| Google Drawing | `image/png` (optional, size cap) |

### 7.3 Drive query `q` — примеры для prompt

```
name contains 'report'
fullText contains 'invoice'
'<folderId>' in parents
mimeType = 'application/pdf'
modifiedTime > '2026-01-01T00:00:00'
trashed = false
starred = true
sharedWithMe
```

### 7.4 Errors

| Error | Когда |
|-------|-------|
| `GoogleNotConnectedError` | нет token |
| `DriveScopeMissingError` | token без drive scope |
| `DriveNotConfiguredError` | Drive API disabled in GCP |

Reuse / extend `tools/builtins/google/errors.py`.

### 7.5 Rate limits & cache

| Group | cache_ttl | rate_limit |
|-------|-----------|------------|
| list/search/get metadata | 30–60s | 60/min per user |
| download/export | 120s | 20/min per user |
| write/upload/share | none | 30/min per user |
| changes.list | 15s | 30/min |

Drive API quota: 20k queries/100s/user — personal bot OK.

### 7.6 Env (новое)

```env
DRIVE_MAX_DOWNLOAD_BYTES=10485760
DRIVE_MAX_EXPORT_CHARS=50000
DRIVE_DEFAULT_MAX_RESULTS=10
DRIVE_MAX_UPLOAD_BYTES=10485760
DRIVE_RATE_LIMIT_READ=60/60
DRIVE_RATE_LIMIT_WRITE=30/60
```

---

## 8. Agent prompt hints (добавить в `agent/prompts.py`)

- **Google Drive** — OAuth same bundle as Calendar/Gmail; `tags: ["google", "drive"]`.
- Find files: `search_files` with Drive `q` — not Exa web search.
- Read flow: `search_files` → `get_file` → `export_file` (Google Docs/Sheets) **or** `download_file` (pdf/txt/binary).
- Folder listing: `list_folder` or `search_files` with `'folderId' in parents`.
- Write: `create_folder` → `upload_file`; move = `move_file`.
- Share: `share_file` with role reader/writer — not email send (that's Gmail).
- Trash vs delete: `trash_file` recoverable; `delete_file` permanent + **`confirm=true`**.
- For spreadsheets **cell edits** — future Sheets API; now export CSV → summarize only.
- Include `drive.google.com` / `webViewLink` in final reply when user should open file (becomes inline button).

---

## 9. Tool graph edges (curated, Phase 2)

```yaml
google.drive.search_files:
  - google.drive.get_file
  - google.drive.export_file
  - google.drive.download_file
google.drive.get_file:
  - google.drive.export_file
  - google.drive.download_file
  - google.drive.share_file
  - google.drive.move_file
google.drive.create_folder:
  - google.drive.upload_file
  - google.drive.create_file
google.drive.export_file:
  - google.drive.share_file
```

---

## 10. Регистрация

```
tools/builtins/google/__init__.py   # GOOGLE_TOOLS += GOOGLE_DRIVE_TOOLS
tools/search_enrichment.py          # TAG_HINT_PROFILES += drive profiles
agent/prompts.py                    # Drive workflow block
config.py                           # DRIVE_* env, OAuth scopes
```

После регистрации: embedding index rebuild, `search_tools(tags=["google","drive","read"])`.

**Не трогаем** Maps (API key). **Sheets API** — отдельный план, отдельный scope `spreadsheets`.

---

## 11. Guards & safety

| Action | Guard |
|--------|-------|
| `delete_file`, `empty_trash`, `delete_revision`, `delete_shared_drive` | `confirm=true` |
| `share_file` with `type=anyone` | optional warn in description |
| download/export | size caps |
| upload | max bytes |

---

## 12. Google OAuth verification

Scope `https://www.googleapis.com/auth/drive` — **Sensitive** (full file access).

| Mode | Кто | Drive |
|------|-----|-------|
| **Testing** | test users | OK для личного бота |
| **Production** | anyone | verification + privacy policy |

**Сейчас:** Testing mode. Calendar + Gmail + Drive на одном consent screen.

---

## 13. Связь с Calendar и Gmail

| | Calendar | Gmail | Drive |
|---|----------|-------|-------|
| Auth | OAuth per user | **тот же token** | **тот же token** |
| Scope | calendar | gmail.* | **+ drive** |
| Disconnect | `/disconnect_google` revokes **всё** | | |
| Tools prefix | `google.calendar.*` | `google.gmail.*` | `google.drive.*` |
| Inline buttons | — | final reply URLs | final reply URLs (webViewLink) |

**Один `/connect_google` → Calendar + Gmail + Drive.**

---

## 14. Checklist перед Drive-1

- [x] GCP: Enable Google Drive API *(вручную в Console)*
- [x] OAuth consent: add `drive` scope *(вручную в Console)*
- [x] `.env`: расширить `GOOGLE_OAUTH_SCOPES`
- [ ] Re-connect test user
- [x] `auth.py`: `get_drive_service()`, `drive_ready`
- [x] `drive_client.py`, `drive_serialize.py` skeleton
- [x] `drive_tools.py` empty registry hook
- [x] `/connect_google`, `/google_status` — Calendar + Gmail + Drive
- [x] `test_google_drive.py` auth smoke
- [x] `TAG_HINT_PROFILES` + `("google", "drive")`
- [ ] BOT_STATUS.md после Drive-1

---

## 15. После Drive — Sheets

| | Drive | Sheets API |
|---|-------|------------|
| Scope | `drive` | `spreadsheets` |
| Read table | export CSV | `values.get` — точнее |
| Write cells | re-upload CSV hack | `values.update` |
| Tools | ~62 | ~40–50 (отдельный план) |

Рекомендация: **Drive-1…2 first** (find + read files), затем **Sheets plan** для cell-level ops.

---

*Документ для ревью. После OK — начинаем **Drive-0** (OAuth) → **Drive-1** (read core).*

*Составлено: **3 июля 2026, 14:00** (UTC+2)*
