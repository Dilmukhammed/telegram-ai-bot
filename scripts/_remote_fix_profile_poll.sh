#!/usr/bin/env bash
set -euo pipefail
cd /opt/telegram-ai-bot
tar -xf /tmp/profile_poll_fix.tar
source .venv/bin/activate

# Bump poll timeout on server env
if grep -q '^BROWSER_PROFILE_READY_TIMEOUT_SECONDS=' .env; then
  sed -i 's/^BROWSER_PROFILE_READY_TIMEOUT_SECONDS=.*/BROWSER_PROFILE_READY_TIMEOUT_SECONDS=180/' .env
else
  echo 'BROWSER_PROFILE_READY_TIMEOUT_SECONDS=180' >> .env
fi

python - <<'PY'
import asyncio
from tools.builtins.browser.profile_store import (
    PROFILE_STATUS_READY,
    get_browser_profile_store,
)
from tools.builtins.browser.session_manager import fetch_profile_status
from tools.builtins.browser.steel_client import reset_steel_client_for_tests
from datetime import datetime, timezone

async def main() -> None:
    reset_steel_client_for_tests()
    store = get_browser_profile_store()
    profile = store.get_profile(8464921092)
    print("local_before", None if profile is None else (profile.status, profile.snapshot_error))
    if profile is None:
        return
    status, err = await fetch_profile_status(profile.steel_profile_id)
    print("steel_status", status, err)
    if status == PROFILE_STATUS_READY:
        store.upsert_profile(
            telegram_user_id=8464921092,
            steel_profile_id=profile.steel_profile_id,
            status=PROFILE_STATUS_READY,
            last_snapshot_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            snapshot_error=None,
            touch_used=False,
        )
        print("local_updated_ready")
    after = store.get_profile(8464921092)
    print("local_after", after.status if after else None, after.snapshot_error if after else None)

asyncio.run(main())
PY

systemctl restart telegram-ai-bot
sleep 3
systemctl is-active telegram-ai-bot
