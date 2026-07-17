#!/usr/bin/env bash
set -euo pipefail
cd /opt/telegram-ai-bot
tar -xf /tmp/agent_wait_deploy.tar
source .venv/bin/activate
python - <<'PY'
from tools.builtins import BUILTIN_TOOLS
assert any(t.name == "agent.wait" for t in BUILTIN_TOOLS)
print("agent.wait ok")
PY
systemctl restart telegram-ai-bot
sleep 3
systemctl is-active telegram-ai-bot
