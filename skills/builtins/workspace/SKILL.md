---
skill_id: workspace
description: Agent workspace — per-user sandbox for uploads, files, grep, zip (server-side)
tags: workspace, filesystem
---

# Agent workspace skill

Use when the user works with **files on the server sandbox** — Telegram uploads, reading/writing text, grep, archives — not Google Drive cloud files.

**Layout** (per user, relative paths):
- `uploads/` — photos/documents from Telegram (`path=…` in user message)
- `agent/` — agent-created notes, scripts, exports
- `exports/` — persisted downloads

**Not workspace:** user's Google Drive → `google.drive.*`. Deliver file to chat → `telegram.send_file`.

## Discovery

Load once per run: `skills.load` → `skill_id: "workspace"`.

`search_tools` tags (AND):

| Need | search_tools |
|------|----------------|
| Full workspace catalog (16 tools) | `{"mode":"catalog","tags":["workspace","filesystem"]}` |
| Read only | `{"mode":"catalog","tags":["workspace","read","filesystem"]}` |
| Write only | `{"mode":"catalog","tags":["workspace","write","filesystem"]}` |
| Rank by task | `{"mode":"rank","query":"grep log file","tags":["workspace"]}` |

## Standard flow

```
1. workspace.stat(path) or workspace.list_dir
2. workspace.read_file (preview ~30 lines) or workspace.read_lines (range)
3. workspace.write_file / append_file / …
4. telegram.send_file(path=…) to deliver to user
```

## Read

| Tool | When |
|------|------|
| `list_dir` | Browse folder (`path`, optional `recursive`) |
| `stat` | Exists, size, mime, mtime |
| `read_file` | Preview text or **load image into vision** |
| `read_lines` | Specific line range (`start_line`, `end_line`) |
| `find` | Glob search (`pattern`) |
| `grep` | Regex in text files |
| `usage` | Quota / disk usage |

**Trap:** `read_file` is preview only — use `read_lines` for long files.

## Write & maintain

| Tool | When |
|------|------|
| `write_file` | Create/overwrite (`content_text` or `content_base64`) |
| `append_file` | Append text |
| `mkdir` | New directory |
| `move` / `copy` | Rename or relocate within sandbox |
| `unzip` | Extract archive |
| `import_from_file_ref` | Save Drive/Gmail `file_ref` into workspace |
| `delete` | Remove file/dir — **`confirm=true`** |
| `clear` | Wipe zone (`agent`/`exports`/`uploads`/`all`) — **`confirm=true`** |

## Send to Telegram

- From workspace: `telegram.send_file` with `path` (relative).
- From Drive/Gmail download: `file_ref` directly (no workspace needed unless persisting).

## Upload to Google Drive

- `google.drive.upload_file` with the same workspace `path` (e.g. from user `[file uploaded: path=…]`).
- Do not invent paths; do not base64 the file when `path` works.

## Anti-patterns

| Wrong | Right |
|-------|-------|
| `google.drive.download_file` for user upload in chat | path from user message → `workspace.read_file` |
| `read_file` for 500-line log | `read_lines` with range |
| `workspace.delete` without confirm | `confirm=true` |
| Invent paths | From `list_dir`, user `path=`, or tool result |

## All 16 tools (prefix `workspace.`)

**Read:** `list_dir`, `stat`, `read_file`, `read_lines`, `usage`, `find`, `grep`

**Write:** `write_file`, `append_file`, `mkdir`, `move`, `copy`, `unzip`, `import_from_file_ref`, `delete`, `clear`
