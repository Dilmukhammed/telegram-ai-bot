#!/usr/bin/env bash
set -euo pipefail
cd /opt/telegram-ai-bot
source .venv/bin/activate

pip install -q 'steel-sdk>=0.11.0' 'playwright>=1.49.0'
python -c "import steel, playwright; print('imports_ok')"

if ! grep -q '^STEEL_API_KEY=' .env; then
  cat >> .env <<'EOF'

# --- Steel cloud browser ---
STEEL_API_KEY=
BROWSER_TOOLS_ENABLED=1
BROWSER_PROFILE_DB_PATH=data/browser_profiles.sqlite
BROWSER_VIEWER_PUBLIC_BASE=http://209.38.249.198:8787
GOOGLE_OAUTH_HOST=0.0.0.0
GOOGLE_OAUTH_PORT=8787
EOF
else
  if grep -q '^BROWSER_TOOLS_ENABLED=' .env; then
    sed -i 's/^BROWSER_TOOLS_ENABLED=.*/BROWSER_TOOLS_ENABLED=1/' .env
  else
    echo 'BROWSER_TOOLS_ENABLED=1' >> .env
  fi
  grep -q '^BROWSER_VIEWER_PUBLIC_BASE=' .env || echo 'BROWSER_VIEWER_PUBLIC_BASE=http://209.38.249.198:8787' >> .env
  grep -q '^BROWSER_PROFILE_DB_PATH=' .env || echo 'BROWSER_PROFILE_DB_PATH=data/browser_profiles.sqlite' >> .env
  grep -q '^GOOGLE_OAUTH_HOST=' .env || echo 'GOOGLE_OAUTH_HOST=0.0.0.0' >> .env
  grep -q '^GOOGLE_OAUTH_PORT=' .env || echo 'GOOGLE_OAUTH_PORT=8787' >> .env
fi

if command -v ufw >/dev/null 2>&1 && ufw status | grep -qi active; then
  ufw allow 8787/tcp || true
fi
iptables -C INPUT -p tcp --dport 8787 -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport 8787 -j ACCEPT || true

echo '--- env ---'
grep -E '^(STEEL_API_KEY|BROWSER_|GOOGLE_OAUTH_HOST|GOOGLE_OAUTH_PORT)=' .env | sed 's/^\(STEEL_API_KEY=\).*/\1***/'

echo '--- checks ---'
python - <<'PY'
from config import get_settings
from skills.registry import get_skill
from agent.prompts import AGENT_SYSTEM_PROMPT
s = get_settings()
print("browser_tools_enabled", s.browser_tools_enabled)
print("steel_key_set", bool(s.steel_api_key))
print("viewer", s.browser_viewer_public_base)
skill = get_skill("browser")
print("skill", None if skill is None else skill.skill_id)
print("prompt_has_browser", "Cloud browser" in AGENT_SYSTEM_PROMPT)
PY

systemctl restart telegram-ai-bot
sleep 3
systemctl is-active telegram-ai-bot
echo '--- stderr ---'
tail -n 40 data/bot.stderr.log || true
echo '--- stdout ---'
tail -n 50 data/bot.stdout.log || true
