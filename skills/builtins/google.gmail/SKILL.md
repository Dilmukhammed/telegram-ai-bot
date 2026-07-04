---
skill_id: google.gmail
description: Gmail — inbox, search, read/send, threads, labels, drafts, filters, attachments (OAuth)
tags: google, gmail
---

# Google Gmail skill

Use when the user asks about **Gmail inbox, emails, threads, search, reply/send, labels, drafts, filters, vacation reply, or attachments** — not Calendar events or Drive files.

**Auth:** user OAuth — `google.auth.status` → `gmail_ready=true`. Same `/connect_google` as Calendar/Drive. If `gmail_ready=false` → user must re-run `/connect_google` (Gmail scopes added after initial connect).

**Read pattern:** list/search returns **ids + snippets only** → `get_message` or `get_thread` for full body (truncated for LLM).

**Not Gmail:** meetings → `google.calendar.*`; file storage → `google.drive.*`; web pages → `exa.web_search` (never for mail already in user's Gmail).

## Discovery

Load once per run: `skills.load` → `skill_id: "google.gmail"`.

`search_tools` tags (AND):

| Need | search_tools |
|------|----------------|
| Full Gmail catalog (45 tools) | `{"mode":"catalog","tags":["google","gmail"]}` |
| Read mail | `{"mode":"catalog","tags":["google","gmail","read"]}` |
| Send / reply / trash | `{"mode":"catalog","tags":["google","gmail","write"]}` |
| Labels | `{"mode":"catalog","tags":["google","gmail","labels"]}` |
| Drafts | `{"mode":"catalog","tags":["google","gmail","drafts"]}` |
| Filters / vacation / aliases | `{"mode":"catalog","tags":["google","gmail","settings"]}` |
| Rank by task | `{"mode":"rank","query":"reply to latest email","tags":["google","gmail"]}` |

## Standard flows

### Browse & search

| User intent | Tool |
|-------------|------|
| Inbox | `list_inbox` |
| Unread | `list_unread` |
| Keyword / sender / date search | `search_messages` (`q` — Gmail syntax) |
| By label | `list_messages` (`label_ids`) |
| Conversation list | `list_threads` (optional `q`, `label_ids`) |
| One message | `get_message` (`message_id`) |
| Full thread | `get_thread` (`thread_id`) |
| Mailbox stats | `get_profile` |

**Gmail `q` examples:**
- `from:user@example.com`
- `subject:invoice`
- `is:unread`
- `has:attachment`
- `after:2026/07/01`
- `label:work newer_than:7d`

Prefer sugar tools (`list_inbox`, `list_unread`) over raw `list_messages` for common views.

### Send / reply / forward

| User intent | Tool |
|-------------|------|
| New email | `send_message` (`to`, `subject`, `body_text` / `body_html`) |
| Reply | `reply_to_message` (`message_id`, `body_text`; `reply_all=true` for all) |
| Forward | `forward_message` (`message_id`, `to`, optional `body_text` note) |
| Save without sending | `create_draft` → later `send_draft` |
| Edit draft | `list_drafts` → `get_draft` → `update_draft` |

### Organize (labels, read state, archive, trash)

| User intent | Tool |
|-------------|------|
| Mark read / unread | `mark_read` / `mark_unread` (`message_id` **or** `thread_id`) |
| Archive (remove from inbox) | `archive_message` |
| Move to trash | `trash_message` / `trash_thread` |
| Restore from trash | `untrash_message` / `untrash_thread` |
| Star / custom label on one | `modify_message` (`add_label_ids` / `remove_label_ids`) |
| Label whole thread | `modify_thread` |
| Bulk label/read | `batch_modify_messages` (up to 1000 ids) |
| Create/rename/delete user label | `create_label` / `update_label` / `delete_label` |
| Label ids & counts | `list_labels` / `get_label` |

System labels (`INBOX`, `UNREAD`, `STARRED`, `TRASH`) cannot be deleted.

### Attachments → Telegram

```
1. get_message(message_id)  → attachment metadata (attachment_id)
2. get_attachment(message_id, attachment_id)  → file_ref
3. telegram.send_file(file_ref=...)
```

Do not invent `file_ref` — only from `get_attachment` in current turn.

### Drafts

| Tool | When |
|------|------|
| `list_drafts` | Unsent drafts |
| `get_draft` | Read one draft |
| `create_draft` | New draft (same fields as send; `to` optional) |
| `update_draft` | Replace draft content |
| `send_draft` | Send by `draft_id` |
| `delete_draft` | Discard draft |

### Settings (filters, OOO, send-as)

| Tool | When |
|------|------|
| `list_filters` / `get_filter` | View mail rules |
| `create_filter` | Auto-label/archive/forward (`criteria` + `action`) |
| `delete_filter` | Remove rule |
| `get_vacation_settings` / `update_vacation_settings` | Out-of-office auto-reply |
| `list_send_as` / `get_send_as` / `patch_send_as` | Send-from aliases |
| `import_message` | Import copy (migration) — **does not send** |

## Destructive actions

| Tool | Guard |
|------|-------|
| `delete_message` | **`confirm=true`** — permanent, NOT trash |
| `batch_delete_messages` | **`confirm=true`** — up to 1000 ids |
| `delete_draft` | permanent (no confirm param) |
| `delete_label` | user labels only |
| `delete_filter` | immediate |

**Trash vs permanent:** `trash_message` is recoverable; `delete_message` is irreversible.

Warn user before `confirm=true` permanent delete.

## Links in replies

When the user should open a thread or search in Gmail:
- Put `mail.google.com` URL in the **final reply** (plain or `[label](url)`, up to 5).
- Inline buttons; stripped from visible text.
- URLs only in tool JSON → collapsed «Ссылки» — paste in reply if user should tap.

## Limits

- List/search `max_results` capped (typically 50 per call); use `page_token` for more.
- `get_message` / `get_thread` body truncated (`gmail_max_body_chars` in config).
- Write rate ~30/min.

## Anti-patterns

| Wrong | Right |
|-------|-------|
| `get_message` without prior search/list id | `search_messages` / `list_inbox` first |
| `list_messages` for «unread» | `list_unread` or `search_messages` `is:unread` |
| `send_message` to reply in thread | `reply_to_message` (sets threading headers) |
| `delete_message` to clean inbox | `trash_message` or `archive_message` |
| Exa for «письмо от банка» in Gmail | `search_messages` |
| `import_message` to send mail | `send_message` |
| Guess `message_id` | From list/search/get_thread |
| Raw attachment bytes in reply | `get_attachment` → `telegram.send_file` |

## Typical user requests

| User says | Flow |
|-----------|------|
| «Что в инбоксе?» | `list_inbox` → summarize snippets |
| «Непрочитанные» | `list_unread` |
| «Найди письмо от X» | `search_messages` → `get_message` |
| «Прочитай переписку» | `list_threads` or search → `get_thread` |
| «Ответь на последнее» | find `message_id` → `reply_to_message` |
| «Отправь письмо на …» | `send_message` |
| «Перешли коллеге» | `forward_message` |
| «В архив» | `archive_message` |
| «Удали» (обычно) | `trash_message` |
| «Скачай вложение» | `get_message` → `get_attachment` → `telegram.send_file` |
| «Создай фильтр» | `create_filter` |
| «Включи автоответ» | `update_vacation_settings` |

## All 45 tools (prefix `google.gmail.`)

**Mail-1 — read core:** `get_profile`, `list_labels`, `get_label`, `search_messages`, `list_messages`, `get_message`, `list_inbox`, `list_unread`, `list_threads`, `get_thread`, `get_attachment`

**Mail-2 — organize & send:** `modify_message`, `modify_thread`, `mark_read`, `mark_unread`, `archive_message`, `trash_message`, `untrash_message`, `trash_thread`, `untrash_thread`, `send_message`, `reply_to_message`, `forward_message`, `create_label`, `update_label`, `delete_label`, `batch_modify_messages`

**Mail-3 — drafts & permanent delete:** `list_drafts`, `get_draft`, `create_draft`, `update_draft`, `delete_draft`, `send_draft`, `delete_message`, `batch_delete_messages`

**Mail-4 — settings & import:** `list_filters`, `get_filter`, `create_filter`, `delete_filter`, `get_vacation_settings`, `update_vacation_settings`, `list_send_as`, `get_send_as`, `patch_send_as`, `import_message`
