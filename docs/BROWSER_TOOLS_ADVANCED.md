# Browser tools — advanced expansion

Status: P3 live on DO (`10479c8`, 69 `browser.*` tools) + captcha detect/solve (71). Advanced plan complete.  
Backend: Steel Cloud + Playwright CDP. Prefix: `browser.*`.  
Existing core stays: session/profile/cookies import, navigate/snapshot/click/type/fill/press/scroll/wait, get_content/screenshot/pdf, `agent.wait`.

Shared rules for all new tools:
- `cache_ttl_seconds=None`, `parallel_safe=False`
- Prefer `ref` from `browser.snapshot`; optional CSS only when necessary
- Size-cap / redact secrets in results
- Never expose CDP URL, API key, raw Steel debug URLs

---

## Already shipped (baseline)

| Tool | Notes |
|------|--------|
| `browser.profile.status` | + Steel refresh when uploading/error |
| `browser.profile.import_cookies` | Chrome cookie seed |
| `browser.profile.disconnect` | |
| `browser.session_open` / `browser.session_close` | login parks across runs |
| `browser.navigate` | |
| `browser.snapshot` | a11y refs |
| `browser.click` / `type` / `fill` / `press` / `scroll` / `wait` | |
| `browser.get_content` / `screenshot` / `pdf` | |

---

## P1 — must (implement first)

### Tabs / history
| Tool | Args (sketch) | Returns |
|------|---------------|---------|
| `browser.tabs.list` | `{}` | `{tabs:[{id,index,url,title,active}], active_index}` |
| `browser.tabs.new` | `{url?}` | `{tab_id,index,url}` |
| `browser.tabs.switch` | `{index}` or `{tab_id}` | `{tab_id,index,url,title}` |
| `browser.tabs.close` | `{index?}` / `{tab_id?}` (default active) | `{closed, active_index}` |
| `browser.back` | `{}` | `{url,title}` |
| `browser.forward` | `{}` | `{url,title}` |
| `browser.reload` | `{wait_until?}` | `{url,title}` |

### Interaction
| Tool | Args | Returns |
|------|------|---------|
| `browser.hover` | `{ref}` | `{ref,url}` |
| `browser.select_option` | `{ref, value?\|label?\|index?}` | `{ref, selected}` |
| `browser.check` | `{ref}` | `{ref, checked:true}` |
| `browser.uncheck` | `{ref}` | `{ref, checked:false}` |
| `browser.clear` | `{ref}` | `{ref}` |

### Files
| Tool | Args | Returns |
|------|------|---------|
| `browser.upload` | `{ref, path?\|file_ref?}` | `{ref, filename, size}` |
| `browser.download` | `{ref?}` click trigger optional; or wait after action | `{file_ref,filename,mime,size}` |
| `browser.wait_for_download` | `{timeout_ms?}` | `{file_ref,filename,mime,size}` |

### Wait / inspect
| Tool | Args | Returns |
|------|------|---------|
| `browser.wait_for_url` | `{url\|glob\|regex, timeout_ms?}` | `{url, matched}` |
| `browser.wait_for_load` | `{wait_until?, timeout_ms?}` | `{url,title}` |
| `browser.get_attribute` | `{ref, name}` | `{ref, name, value}` |
| `browser.get_value` | `{ref}` | `{ref, value}` |
| `browser.is_visible` | `{ref}` | `{ref, visible}` |
| `browser.is_enabled` | `{ref}` | `{ref, enabled}` |

### Cookies / frames / evaluate
| Tool | Args | Returns |
|------|------|---------|
| `browser.cookies.get` | `{urls?}` | `{cookies:[…]}` (values ok; no secrets in logs) |
| `browser.cookies.set` | `{cookies:[…]}` | `{set:n}` |
| `browser.cookies.clear` | `{url?}` | `{cleared:true}` |
| `browser.cookies.export` | `{urls?}` | `{file_ref}` or capped JSON |
| `browser.frame_switch` | `{name?\|url?\|index?\|main:true}` | `{frame, url}` |
| `browser.evaluate` | `{expression, timeout_ms?}` | `{result}` capped JSON/string |
| `browser.evaluate_on_ref` | `{ref, expression}` | `{result}` capped |

---

## P2 — power (implementing)

| Tool | Notes |
|------|--------|
| `browser.drag` | `{source_ref, target_ref}` |
| `browser.focus` | `{ref}` |
| `browser.keydown` / `browser.keyup` | `{key}` |
| `browser.mouse_move` / `mouse_down` / `mouse_up` | coords or ref |
| `browser.storage.get` / `storage.set` | `{area:local\|session, key, value?}` |
| `browser.set_viewport` | `{width,height}` |
| `browser.set_geolocation` | `{latitude,longitude}` |
| `browser.set_locale` / `browser.set_timezone` | CDP Emulation overrides |
| `browser.grant_permissions` / `clear_permissions` | |
| `browser.network.last` | last N reqs; metadata only |
| `browser.network.wait` | url / glob / regex |
| `browser.console` / `browser.page_errors` | diagnostics |

---

## P3 — optional / careful (done)

| Tool | Notes |
|------|--------|
| `browser.route` / `browser.unroute` | abort/fulfill only; max 20 routes; fulfill body ≤64k |
| `browser.clipboard_read` / `clipboard_write` | permission grant best-effort; text capped |
| `browser.emulate_media` | media screen/print; color_scheme; reduced_motion |
| `browser.perf` | compact navigation timings |

### Captcha (post-P3)

| Tool | Notes |
|------|--------|
| `browser.captcha.detect` | Turnstile / reCAPTCHA / hCaptcha / image / slider heuristics |
| `browser.captcha.solve` | `auto\|ocr\|token\|hitl` — ddddocr + CapSolver + existing viewer HITL |

Env: `CAPSOLVER_API_KEY`, `CAPTCHA_OCR_ENABLED`, `CAPTCHA_SOLVER_TIMEOUT_SECONDS`.

---

## Explicit non-goals

- Raw CDP / websocket / Steel admin APIs as tools
- Unbounded evaluate / huge network body dumps
- Multiple parallel Steel sessions per user
- Browser extension install

---

## Implementation order

1. **P1** — tabs, history, hover/select/check/clear, upload/download/waits, attrs, cookies get/set/clear/export, frame_switch, evaluate*
2. Update `skills/builtins/browser/SKILL.md` + `agent/prompts.py` + search aliases
3. Unit tests (mocked Playwright) + deploy DO
4. **P2** after P1 is live and used

## Wiring

- Code: `tools/builtins/browser/` — `playwright_bridge.py` + `tab_tools.py`, `interaction_tools.py`, `file_tools.py`, `inspect_tools.py`, `cookie_tools.py`, `frame_eval_tools.py`
- Register in `BROWSER_TOOLS` (71 = P1–P3 + captcha detect/solve)
- Modules: `+ power_tools.py`, `state_tools.py`, `diagnostics_tools.py`, `advanced_tools.py`, `captcha_tools.py`
- Discovery: tags `browser`/`web` (+ `tabs`, `files`, `cookies`/`auth`, `network`, `storage`, `clipboard`, `captcha`)
- Skill: `skills/builtins/browser/SKILL.md`
