---
skill_id: browser
description: Steel cloud browser — cookies, tabs, snapshot/refs, forms, files, evaluate
tags: browser, web
---

# Browser skill (Steel)

Use for **interactive websites** that need a real browser (JS apps, logged-in pages).  
Do **not** use for plain news/search → `exa.web_search` / `exa.web_fetch`.  
Do **not** replace Google API OAuth → `google.auth.*` / `/connect_google` (APIs).  
Google **web UI** login inside Steel is often blocked (`browser may not be secure`) — use **cookie seed**.

## Discovery

`skills.load` → `skill_id: "browser"`

| Need | search_tools |
|------|----------------|
| Full browser catalog | `{"mode":"catalog","tags":["browser","web"]}` |
| Login / profile / cookies | `{"mode":"catalog","tags":["browser","auth"]}` |
| Tabs | `{"mode":"catalog","tags":["browser","tabs"]}` |
| Downloads / uploads | `{"mode":"catalog","tags":["browser","files"]}` |

## Google / hard sites: cookie seed (preferred)

User logs in on **their real Chrome**, exports cookies, sends the JSON file in Telegram (workspace `uploads/…`).

```
1. browser.profile.import_cookies({path:"uploads/google_cookies.json"})
   # or file_ref / cookies_json
2. browser.navigate({url:"https://mail.google.com/"})  # or screenshot to verify
3. browser.session_close()  # REQUIRED — snapshots cookies into Steel profile
4. Later: browser.session_open({purpose:"automation"}) reuses profile
```

### How the user exports cookies (Chrome)

1. Install **Cookie-Editor** or **EditThisCookie**
2. Open `https://mail.google.com` while logged in
3. Export cookies as JSON (include `.google.com` / `accounts.google.com`)
4. Send the `.json` file to the bot in Telegram
5. Ask: "import these cookies into browser and open Gmail"

Do **not** paste huge cookie JSON in chat if a file upload works — use workspace path.

## HITL login (other sites)

Works for many non-Google sites. Google sign-in page often fails.

```
1. browser.session_open({purpose:"login"})
2. User completes login via Telegram one-time viewer link
3. browser.session_close()
```

## Automate (with saved profile)

```
1. browser.session_open({purpose:"automation"})
2. browser.navigate → snapshot → click/type/fill/select_option/check
3. Tabs: tabs.list / tabs.new / tabs.switch / tabs.close; back/forward/reload
4. Wait: browser.wait | wait_for_url | wait_for_load (DOM); agent.wait (wall clock)
5. Inspect: get_attribute / get_value / is_visible / is_enabled
6. Files: upload (path/file_ref) | download (click ref → file_ref)
7. Frames: frame_switch; JS: evaluate / evaluate_on_ref (capped)
8. Cookies: cookies.get/set/clear/export (session); profile.import_cookies (persist seed)
9. browser.screenshot / get_content / pdf → telegram.send_file({file_ref})
10. browser.session_close()  # ALWAYS
```

## Rules

- One active session per user; login sessions may park across turns.
- After cookie import, always `session_close` to persist.
- Re-snapshot after navigation (refs go stale).
- Prefer refs over raw CSS/JS when possible.
- Launch sessions max ~15 minutes.
