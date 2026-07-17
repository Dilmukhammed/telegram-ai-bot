#!/usr/bin/env bash
set -euo pipefail
cd /opt/telegram-ai-bot
tar -xf /tmp/browser_cookies.tar
source .venv/bin/activate
python - <<'PY'
from tools.builtins.browser import BROWSER_TOOLS
print("tools", len(BROWSER_TOOLS))
print("has_import", any(t.name == "browser.profile.import_cookies" for t in BROWSER_TOOLS))
PY
systemctl restart telegram-ai-bot
sleep 4
systemctl is-active telegram-ai-bot
ss -tlnp | grep 8787 || true
grep -E 'HTTP server|Browser viewer|Bot started|Traceback' data/bot.stderr.log | tail -n 8
