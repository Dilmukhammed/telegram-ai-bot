#!/usr/bin/env bash
set -eu
cd /opt/telegram-ai-bot
source .venv/bin/activate


echo "=== ddddocr ==="
pip install -q 'ddddocr>=1.5.0'
python - <<'PY'
import ddddocr
print("ddddocr_ok")
PY

echo "=== captcha tools ==="
python - <<'PY'
from tools.builtins.browser import BROWSER_TOOLS
names = [t.name for t in BROWSER_TOOLS if "captcha" in t.name]
print("tool_count", len(BROWSER_TOOLS))
print("captcha_tools", names)
from config import get_settings
s = get_settings()
print("captcha_ocr_enabled", s.captcha_ocr_enabled)
print("capsolver_set", bool((s.capsolver_api_key or "").strip()))
print("timeout", s.captcha_solver_timeout_seconds)
PY

# ensure env keys exist
python - <<'PY'
from pathlib import Path
p = Path(".env")
text = p.read_text(encoding="utf-8")
needed = {
    "CAPSOLVER_API_KEY": "",
    "CAPTCHA_OCR_ENABLED": "1",
    "CAPTCHA_SOLVER_TIMEOUT_SECONDS": "120",
}
lines = text.splitlines()
seen = set()
out = []
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        k = line.split("=", 1)[0].strip()
        if k in needed:
            seen.add(k)
            existing = line.split("=", 1)[1]
            if k == "CAPSOLVER_API_KEY" and existing.strip():
                out.append(line)
            else:
                out.append(f"{k}={needed[k] if k != 'CAPSOLVER_API_KEY' else existing}")
            continue
    out.append(line)
for k, v in needed.items():
    if k not in seen:
        out.append(f"{k}={v}")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
print("env_ok")
PY

systemctl restart telegram-ai-bot.service
sleep 2
systemctl is-active telegram-ai-bot.service
echo DONE
