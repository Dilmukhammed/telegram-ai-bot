---
skill_id: google.calendar
description: Google Calendar — events, scheduling, free/busy, secondary calendars (OAuth)
tags: google, calendar
---

# Google Calendar skill

Use when the user asks about **Google Calendar events, meetings, schedule, availability, recurring events, or managing calendars** — not Apple Calendar, Outlook local, or Google Tasks todos.

**Auth:** user OAuth — `google.auth.status` → `connected=true` (Calendar is in the base OAuth bundle). Same `/connect_google` as Gmail/Drive. If not connected: `google.auth.connect_url` or tell user `/connect_google`.

**Default calendar:** `calendar_id: "primary"` unless user names another calendar → `list_calendars` first.

**Not Calendar:** todos/checklists → `google.tasks.*`. Spreadsheet data → `google.sheets.*`. Finding files → `google.drive.*`.

## Discovery

Load once per run: `skills.load` → `skill_id: "google.calendar"`.

`search_tools` tags (AND):

| Need | search_tools |
|------|----------------|
| Full Calendar catalog (23 tools) | `{"mode":"catalog","tags":["google","calendar"]}` |
| Read events | `{"mode":"catalog","tags":["google","calendar","read"]}` |
| Create/edit/delete events | `{"mode":"catalog","tags":["google","calendar","write"]}` |
| Free/busy & slots | `{"mode":"catalog","tags":["google","calendar","scheduling"]}` |
| Calendar list CRUD | `{"mode":"catalog","tags":["google","calendar","calendars"]}` |
| Colors | `{"mode":"catalog","tags":["google","calendar","colors"]}` |
| Rank by task | `{"mode":"rank","query":"create meeting tomorrow","tags":["google","calendar"]}` |

## Standard flows

### What's on my schedule?

| User intent | Tool |
|-------------|------|
| Today | `list_today` |
| Coming up / next N events | `list_upcoming` (`count`, `days_ahead`) |
| Explicit date range | `list_events` (`time_min` required, optional `time_max`) |
| Search by keyword | `search_events` (`query`; defaults next 30 days) |
| One event by id | `get_event` |

### Create / change / delete events

| User intent | Tool |
|-------------|------|
| Simple NL: «обед завтра в 13:00» | `quick_add_event` (`text`) |
| Full control: attendees, recurrence, reminders | `create_event` |
| Small edit (time, title, location) | `patch_event` — only pass changed fields |
| Replace entire event | `update_event` — **omitted fields are cleared** |
| Cancel meeting | `delete_event` |
| Move to another calendar | `move_event` + `destination_calendar_id` from `list_calendars` |
| Recurring series occurrences | `list_instances` (`event_id`, `time_min`, `time_max`) |
| Import without sending invites | `import_event` (not for normal new meetings) |

### Availability

| User intent | Tool |
|-------------|------|
| Raw busy blocks | `freebusy` (`time_min`, `time_max`, optional `calendar_ids`) |
| Suggest bookable slots | `find_free_slots` (`duration_minutes`, working hours, `max_slots`) |

Prefer `find_free_slots` when user asks «когда свободен?» / «найди время для встречи».

### Calendars (not events)

| Tool | When |
|------|------|
| `list_calendars` | Get all calendar ids (work, personal, shared) |
| `get_calendar` | Metadata for one calendar (timezone, title) |
| `create_calendar` | New secondary calendar |
| `update_calendar` | Rename / timezone / description |
| `delete_calendar` | Delete **secondary** only — primary forbidden |
| `clear_calendar` | Wipe all events from secondary — **`confirm=true`** |

## Event time format

**Timed event:**
```json
"start": {"datetime": "2026-07-05T15:00:00", "time_zone": "Europe/Moscow"},
"end":   {"datetime": "2026-07-05T16:00:00", "time_zone": "Europe/Moscow"}
```

**All-day:**
```json
"start": {"date": "2026-07-05"},
"end":   {"date": "2026-07-06"}
```
(All-day `end.date` is exclusive — next day for single-day events.)

**Recurrence:** `recurrence: ["RRULE:FREQ=WEEKLY;BYDAY=MO"]` on `create_event` / `patch_event`.

## Attendees & notifications

`send_updates` on create/patch/update/delete/move:
- `none` (default) — no emails
- `all` — notify all attendees
- `externalOnly` — only non-Google guests

Use `all` when user explicitly wants invites sent.

## Colors

1. `list_colors` → `event_colors` and `calendar_colors` palettes
2. `color_id` on `create_event` / `patch_event` (event colors 1–11)
3. `set_calendar_color` for calendar list display color

## Links in replies

When the user should open an event or calendar:
- Put `htmlLink` from tool result or `calendar.google.com` URL in the **final reply** (plain or `[title](url)`, up to 5).
- These become inline buttons; stripped from visible text.
- URLs only in tool JSON appear in collapsed «Ссылки» — paste in reply if user should tap.

## Destructive actions

| Action | Guard |
|--------|-------|
| `clear_calendar` | `confirm=true`; secondary only |
| `delete_calendar` | secondary only; primary blocked |
| `delete_event` | prefer confirming with user first |

## Anti-patterns

| Wrong | Right |
|-------|-------|
| `google.tasks.*` for a meeting | `create_event` / `quick_add_event` |
| `list_events` without `time_min` for «today» | `list_today` |
| `list_upcoming` for keyword search | `search_events` |
| `freebusy` when user wants slot suggestions | `find_free_slots` |
| `update_event` for small time change | `patch_event` |
| `create_event` for «lunch tomorrow 1pm» | `quick_add_event` |
| `import_event` for normal meeting with guests | `create_event` + `send_updates` |
| Exa web search for user's schedule | `list_today` / `search_events` |
| Delete/clear `primary` calendar | impossible — use `delete_event` per event |

## Typical user requests

| User says | Flow |
|-----------|------|
| «Что у меня сегодня?» | `list_today` |
| «Ближайшие встречи» | `list_upcoming` |
| «Найди встречу с Алексом» | `search_events` |
| «Создай созвон завтра в 15:00» | `quick_add_event` or `create_event` |
| «Перенеси на час позже» | `search_events` or prior `event_id` → `patch_event` |
| «Отмени встречу» | find event → `delete_event` |
| «Когда свободен во вторник?» | `find_free_slots` |
| «Покажи все мои календари» | `list_calendars` |
| «Создай календарь Проект X» | `create_calendar` |

## All 23 tools (prefix `google.calendar.`)

**Read:** `get_calendar`, `list_events`, `get_event`, `search_events`, `list_upcoming`, `list_today`, `list_colors`, `freebusy`

**Write events:** `create_event`, `quick_add_event`, `patch_event`, `delete_event`, `update_event`, `move_event`, `import_event`

**Scheduling:** `find_free_slots`, `list_instances`

**Calendars:** `list_calendars`, `create_calendar`, `update_calendar`, `delete_calendar`, `clear_calendar`, `set_calendar_color`
