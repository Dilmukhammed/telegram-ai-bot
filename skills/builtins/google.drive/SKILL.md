---
skill_id: google.drive
description: Google Drive — search, read, upload, share, comments, shared drives, revisions (OAuth)
tags: google, drive
---

# Google Drive skill

Use when the user asks about **files, folders, Drive search, upload/download, sharing, comments, trash, shared drives (Team Drives), or sending a Drive file in Telegram**.

**Auth:** user OAuth — same as Calendar/Gmail. Check `google.auth.status` → `drive_ready=true`. If false: `/connect_google` or `google.auth.connect_url`. Drive scope is included in the standard connect flow.

**Not Drive:** Gmail attachments → `google.gmail.*`. Spreadsheet **cells** → `google.sheets.*` (find file id via Drive search first).

## Discovery

Load once per run: `skills.load` → `skill_id: "google.drive"`.

`search_tools` — always pass tags (AND):

| Need | search_tools |
|------|----------------|
| Full Drive catalog (~70 tools) | `{"mode":"catalog","tags":["google","drive"]}` |
| Read / search only | `{"mode":"catalog","tags":["google","drive","read"]}` |
| Create / upload / move | `{"mode":"catalog","tags":["google","drive","write"]}` |
| Share / permissions | `{"mode":"catalog","tags":["google","drive","permissions"]}` |
| Comments | `{"mode":"catalog","tags":["google","drive","comments"]}` |
| Revisions | `{"mode":"catalog","tags":["google","drive","revisions"]}` |
| Changes sync | `{"mode":"catalog","tags":["google","drive","changes"]}` |
| Shared drives | `{"mode":"catalog","tags":["google","drive","shared_drives"]}` |
| Labels (Workspace) | `{"mode":"catalog","tags":["google","drive","labels"]}` |
| Approvals / proposals | `{"mode":"catalog","tags":["google","drive","workspace"]}` |
| Rank by task | `{"mode":"rank","query":"share file with email","tags":["google","drive"]}` |

## Core workflows

### Find a file

1. `google.drive.search_files` with Drive **`q`** (not Exa web search).
2. Or browse: `list_folder` (default root), `list_starred`, `list_recent`, `list_shared_with_me`, `list_trash`.
3. Details: `get_file` with `file_id`.

**`q` examples:**
- `name contains 'report'`
- `mimeType='application/pdf'`
- `fullText contains 'budget'`
- `'FOLDER_ID' in parents`
- `mimeType='application/vnd.google-apps.spreadsheet'` → then use Sheets tools for cells

**Shared drive search:** `corpora=allDrives` or `corpora=drive` + `drive_id` from `list_shared_drives`.

### Read file content

| File type | Tool |
|-----------|------|
| Google Docs / Slides / Sheets (snapshot) | `export_file` — pick `mime_type` (text/plain, pdf, csv for sheets) |
| PDF, images, binary uploads | `download_file` |
| Metadata only | `get_file` |

**Rules:**
- Native Google files → **`export_file`**, not `download_file`.
- `export_file` / `download_file` return **`file_ref`** (server-side) — not raw bytes in chat.
- To send in Telegram: `telegram.send_file` with that `file_ref`.
- Export text capped (~50k chars); large exports may hit server limits — tell user to open Drive link instead.
- **Cell-level spreadsheet work** → `google.sheets.get_values` / `update_values`, not Drive export.

### Upload / create

1. `create_folder` (optional parent `folder_id`).
2. `upload_file` — prefer **`path`** for Telegram/workspace files (e.g. `uploads/123_report.pdf`); else `content_text` / `content_base64`. Exactly one body source. `name` optional when `path` is set.
3. Or `create_file` for empty Google Docs/Sheets/Slides.
4. Organize: `move_file`, `rename_file`, `copy_file`, `star_file` / `unstar_file`.

**Telegram upload → Drive:** use the `path=…` from the user message — do not re-download or invent paths.

### Trash vs permanent delete

| Action | Tool | Recoverable? |
|--------|------|--------------|
| Move to trash | `trash_file` | Yes — `untrash_file`, `list_trash` |
| Permanent delete | `delete_file` | **No** — requires `confirm=true` |
| Empty trash | `empty_trash` | **No** — requires `confirm=true` |

Warn the user before `confirm=true` deletes.

### Share / permissions

1. `search_files` or `get_file` → `file_id`.
2. `share_file` — email + role `reader` / `writer` / `commenter`, or `type=anyone` for link access.
3. Audit: `list_permissions` → `update_permission` / `remove_permission`.

**Warning:** `type=anyone` makes a public link — confirm intent with user.

Do **not** use Gmail `send_message` to share Drive files — use Drive permissions.

### Comments (Docs/Sheets/Slides)

`list_comments` → `create_comment` / `create_reply` / `update_comment` / `delete_comment`.  
Drive comments ≠ Gmail threads.

### Revisions (uploaded blobs, e.g. PDF)

`list_revisions` → `get_revision`. `delete_revision` needs `confirm=true`.  
Google Docs native revision history may be incomplete via API.

### Changes sync (incremental)

`get_changes_start_token` → `list_changes(page_token)` → save `new_start_page_token` for next poll.

### Shared drives (Team Drives)

`list_shared_drives` → `drive_id` for search/list with `corpora=drive`.  
Create/update/hide/delete shared drives — `delete_shared_drive` requires `confirm=true`.

### Labels & Workspace extras

- **Labels:** `list_file_labels` / `modify_file_labels` (Workspace).
- **Approvals / access proposals:** tags `workspace` — formal workflows; rare in chat.

### Account info

`get_about` — storage quota, user, limits.

## Tool map (70 tools, by prefix)

All names: `google.drive.<action>`.

| Family | Examples |
|--------|----------|
| Read | `search_files`, `list_files`, `get_file`, `list_folder`, `list_starred`, `list_trash`, `list_shared_with_me`, `list_recent`, `download_file`, `export_file` |
| Write | `create_folder`, `create_file`, `upload_file`, `update_file_metadata`, `update_file_content`, `copy_file`, `move_file`, `rename_file`, `star_file`, `trash_file`, `untrash_file`, `delete_file`, `empty_trash`, `create_shortcut` |
| Permissions | `list_permissions`, `share_file`, `update_permission`, `remove_permission` |
| Comments | `list_comments`, `create_comment`, `create_reply`, … |
| Revisions | `list_revisions`, `get_revision`, `delete_revision` |
| Changes | `get_changes_start_token`, `list_changes` |
| Shared drives | `list_shared_drives`, `create_shared_drive`, `hide_shared_drive`, … |
| Labels | `list_file_labels`, `modify_file_labels` |
| Workspace | `list_access_proposals`, `start_approval`, `approve_file`, … |
| Settings | `get_about`, `list_apps`, `get_app`, `generate_file_ids` |

## Telegram reply rules

1. When the user should open a file, add **`web_view_link`** or drive.google.com / docs.google.com URL in the **final reply** (plain or `[filename](url)`) — up to 5 inline buttons, stripped from visible text.
2. Tool-only links appear in collapsed «Ссылки» unless repeated in final answer.
3. Spreadsheet URLs: docs.google.com/spreadsheets — same button rules.
4. After `download_file` / `export_file`, offer `telegram.send_file` if user wanted the file in chat.
5. Telegram limits: document 50 MB, photo 10 MB — if `telegram.send_file` fails, give Drive link.

## Limits (server defaults)

- Read rate: ~60/min; write: ~30/min.
- Upload per file: check `drive_max_upload_bytes` (default 10 MB in bot config).
- Export output: max ~10 MB / 50k chars for LLM context.
- Do not invent `file_ref` — only from tool results in current turn.

## Anti-patterns

- Do not use `exa.web_search` to find user's Drive files.
- Do not use `download_file` on Google Docs/Sheets/Slides — use `export_file`.
- Do not use Drive export for spreadsheet cell edits — use `google.sheets.*`.
- Do not share via Gmail when user meant Drive sharing.
- Do not skip OAuth check — all `google.drive.*` need `drive_ready=true`.
- Do not permanent-delete without `confirm=true` and user awareness.

## Typical user requests

| User says | Flow |
|-----------|------|
| «Найди PDF invoice в Drive» | `search_files` q=mimeType pdf + name |
| «Скинь мне этот файл» | `export_file` or `download_file` → `telegram.send_file` |
| «Создай папку Projects» | `create_folder` |
| «Поделись с user@mail.com» | `share_file` reader/writer |
| «Что в корзине?» | `list_trash` |
| «Открой таблицу бюджет» | `search_files` spreadsheet mime → link in reply; cells → sheets tools |
