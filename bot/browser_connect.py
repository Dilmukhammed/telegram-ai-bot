from __future__ import annotations

from config import browser_tools_enabled, browser_viewer_configured, steel_configured
from tools.builtins.browser.profile_store import get_browser_profile_store
from tools.builtins.browser.steel_client import get_steel_client


async def browser_status_text(user_id: int) -> str:
    if not steel_configured():
        return "Browser: STEEL_API_KEY not configured."
    if not browser_tools_enabled():
        return "Browser: tools disabled (BROWSER_TOOLS_ENABLED=0)."

    profile = get_browser_profile_store().get_profile(user_id)
    viewer = "yes" if browser_viewer_configured() else "NO (set BROWSER_VIEWER_PUBLIC_BASE)"
    if profile is None:
        return (
            "Browser: no saved profile.\n"
            f"HITL viewer: {viewer}\n"
            "Ask the agent to open a login session (browser.session_open purpose=login)."
        )
    return (
        "Browser profile:\n"
        f"- profile_id: {profile.steel_profile_id}\n"
        f"- status: {profile.status}\n"
        f"- last_used: {profile.last_used_at}\n"
        f"- last_snapshot: {profile.last_snapshot_at or '—'}\n"
        f"- snapshot_error: {profile.snapshot_error or '—'}\n"
        f"- HITL viewer: {viewer}"
    )


async def disconnect_browser(user_id: int, *, delete_remote: bool = True) -> str:
    store = get_browser_profile_store()
    profile = store.get_profile(user_id)
    if profile is None:
        return "Browser: no profile to disconnect."

    remote_deleted = False
    if delete_remote and steel_configured():
        try:
            client = get_steel_client()
            await client.delete_profile(profile.steel_profile_id)
            remote_deleted = True
        except Exception as exc:
            store.delete_profile(user_id)
            return (
                f"Local profile removed. Remote delete failed: {type(exc).__name__}: {exc}"
            )

    store.delete_profile(user_id)
    if remote_deleted:
        return "Browser profile disconnected (local + Steel remote deleted)."
    return "Browser profile disconnected (local only)."
