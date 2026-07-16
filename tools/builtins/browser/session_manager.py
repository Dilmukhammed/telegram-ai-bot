from __future__ import annotations

import asyncio
import contextvars
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from config import browser_tools_enabled, get_settings
from tools.builtins.browser.errors import (
    BrowserNoSessionError,
    BrowserNotConfiguredError,
    BrowserProfileNotReadyError,
    BrowserSessionExpiredError,
)
from tools.builtins.browser.playwright_bridge import (
    PlaywrightSession,
    connect_session,
    disconnect_session,
)
from tools.builtins.browser.profile_store import (
    PROFILE_STATUS_ERROR,
    PROFILE_STATUS_READY,
    PROFILE_STATUS_UPLOADING,
    get_browser_profile_store,
)
from tools.builtins.browser.steel_client import get_steel_client

logger = logging.getLogger(__name__)

_browser_manager: contextvars.ContextVar["BrowserSessionManager | None"] = contextvars.ContextVar(
    "browser_session_manager",
    default=None,
)

# Login HITL sessions must outlive a single agent turn — park them here on run_end.
_HELD_LOGIN_LEASES: dict[int, BrowserLease] = {}
_HELD_LOCK = asyncio.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@dataclass
class BrowserLease:
    handle: str
    lease_id: str
    user_id: int
    run_id: str
    steel_session_id: str
    steel_profile_id: str | None
    purpose: str
    persist: bool
    debug_url: str
    websocket_url: str
    opened_at: float
    expires_at: float
    last_activity_at: float
    playwright: PlaywrightSession | None = None
    slot_held: bool = True
    closed: bool = False


@dataclass
class ProfilePollResult:
    ready: bool
    status: str
    attempts: int
    poll_elapsed_ms: int
    error: str | None = None


class BrowserSessionManager:
    def __init__(self, *, run_id: str, user_id: int | None) -> None:
        self.run_id = run_id
        self.user_id = user_id
        self._lease: BrowserLease | None = None
        self._lock = asyncio.Lock()

    @property
    def lease(self) -> BrowserLease | None:
        return self._lease

    def touch(self) -> None:
        if self._lease and not self._lease.closed:
            self._lease.last_activity_at = time.monotonic()

    def _require_user(self) -> int:
        if self.user_id is None:
            raise BrowserNotConfiguredError("Telegram user_id is required for browser tools")
        return self.user_id

    def _ensure_not_expired(self, lease: BrowserLease) -> None:
        if lease.closed or time.monotonic() >= lease.expires_at:
            raise BrowserSessionExpiredError("Browser session expired")

    def _reuse_payload(self, lease: BrowserLease) -> dict[str, Any]:
        return {
            "session_handle": lease.handle,
            "reused": True,
            "purpose": lease.purpose,
            "profile_id": lease.steel_profile_id,
            "persist": lease.persist,
            "expires_at": datetime.fromtimestamp(
                time.time() + (lease.expires_at - time.monotonic()),
                tz=timezone.utc,
            )
            .replace(tzinfo=None)
            .isoformat(),
            "login": None,
            "held_across_turns": lease.purpose == "login",
        }

    async def adopt_held_login_lease(self) -> bool:
        """Pull a parked login lease for this user into the current run manager."""
        if self.user_id is None:
            return False
        async with _HELD_LOCK:
            held = _HELD_LOGIN_LEASES.get(self.user_id)
            if held is None or held.closed:
                _HELD_LOGIN_LEASES.pop(self.user_id, None)
                return False
            if time.monotonic() >= held.expires_at:
                return False
            held.run_id = self.run_id
            self._lease = held
            _HELD_LOGIN_LEASES.pop(self.user_id, None)
            return True

    async def open(
        self,
        *,
        purpose: str = "automation",
        persist: bool | None = None,
        start_url: str | None = None,
    ) -> dict[str, Any]:
        if not browser_tools_enabled():
            raise BrowserNotConfiguredError(
                "Browser tools disabled or STEEL_API_KEY missing (set BROWSER_TOOLS_ENABLED=1)"
            )

        user_id = self._require_user()
        settings = get_settings()
        purpose = purpose if purpose in {"automation", "login"} else "automation"
        if purpose == "login":
            persist = True
        elif persist is None:
            persist = True

        async with self._lock:
            if self._lease is None:
                await self.adopt_held_login_lease()

            if self._lease and not self._lease.closed:
                self._ensure_not_expired(self._lease)
                self.touch()
                # Login reuse: keep same Steel session so the viewer link still works.
                return self._reuse_payload(self._lease)

            store = get_browser_profile_store()
            profile = store.get_profile(user_id)
            if purpose == "automation" and profile and profile.status in {
                PROFILE_STATUS_UPLOADING,
                PROFILE_STATUS_ERROR,
            }:
                try:
                    remote_status, err = await fetch_profile_status(profile.steel_profile_id)
                    if remote_status == PROFILE_STATUS_READY:
                        profile = store.upsert_profile(
                            telegram_user_id=user_id,
                            steel_profile_id=profile.steel_profile_id,
                            status=PROFILE_STATUS_READY,
                            last_snapshot_at=_iso(_utc_now()),
                            snapshot_error=None,
                            touch_used=False,
                        )
                    elif remote_status == PROFILE_STATUS_ERROR:
                        store.upsert_profile(
                            telegram_user_id=user_id,
                            steel_profile_id=profile.steel_profile_id,
                            status=PROFILE_STATUS_ERROR,
                            snapshot_error=err,
                            touch_used=False,
                        )
                except Exception as exc:
                    logger.warning("profile status refresh before open failed: %s", exc)

            if purpose == "automation" and profile and profile.status == PROFILE_STATUS_UPLOADING:
                raise BrowserProfileNotReadyError(
                    "Browser profile is still uploading from the last session; wait and check browser.profile.status"
                )

            client = get_steel_client()
            await client.acquire_session_slot()
            slot_held = True
            steel_session = None
            lease_id = secrets.token_hex(8)
            handle = f"bs_{lease_id}"
            try:
                create_kwargs: dict[str, Any] = {
                    "api_timeout": min(settings.browser_session_max_seconds, 900) * 1000,
                    "persist_profile": bool(persist),
                    "dimensions": {
                        "width": settings.browser_viewport_width,
                        "height": settings.browser_viewport_height,
                    },
                }
                if profile and profile.steel_profile_id and profile.status != "revoked":
                    create_kwargs["profile_id"] = profile.steel_profile_id

                steel_session = await client.create_session(**create_kwargs)
                session_id = _attr(steel_session, "id")
                websocket_url = _attr(steel_session, "websocket_url") or _attr(
                    steel_session, "websocketUrl"
                )
                debug_url = (
                    _attr(steel_session, "debug_url")
                    or _attr(steel_session, "debugUrl")
                    or _attr(steel_session, "session_viewer_url")
                    or _attr(steel_session, "sessionViewerUrl")
                    or ""
                )
                profile_id = _attr(steel_session, "profile_id") or _attr(
                    steel_session, "profileId"
                )
                if not session_id or not websocket_url:
                    raise BrowserNotConfiguredError("Steel session missing id/websocket_url")

                if profile_id:
                    store.upsert_profile(
                        telegram_user_id=user_id,
                        steel_profile_id=str(profile_id),
                        status=PROFILE_STATUS_UPLOADING if persist else (
                            profile.status if profile else PROFILE_STATUS_READY
                        ),
                    )

                pw = await connect_session(
                    websocket_url=str(websocket_url),
                    api_key=settings.steel_api_key,
                )
                from tools.builtins.browser.playwright_bridge import navigate

                initial_url = start_url
                if not initial_url and purpose == "login":
                    initial_url = "https://accounts.google.com/"
                if initial_url:
                    await navigate(pw, initial_url)

                now = time.monotonic()
                max_seconds = min(settings.browser_session_max_seconds, 900)
                lease = BrowserLease(
                    handle=handle,
                    lease_id=lease_id,
                    user_id=user_id,
                    run_id=self.run_id,
                    steel_session_id=str(session_id),
                    steel_profile_id=str(profile_id) if profile_id else None,
                    purpose=purpose,
                    persist=bool(persist),
                    debug_url=str(debug_url),
                    websocket_url=str(websocket_url),
                    opened_at=now,
                    expires_at=now + max_seconds,
                    last_activity_at=now,
                    playwright=pw,
                    slot_held=True,
                )
                store.open_session_audit(
                    lease_id=lease_id,
                    telegram_user_id=user_id,
                    run_id=self.run_id,
                    steel_session_id=str(session_id),
                    steel_profile_id=str(profile_id) if profile_id else None,
                    purpose=purpose,
                )
                self._lease = lease
                slot_held = False  # ownership transferred to lease

                expires_at = _iso(_utc_now() + timedelta(seconds=max_seconds))
                return {
                    "session_handle": handle,
                    "reused": False,
                    "purpose": purpose,
                    "profile_id": lease.steel_profile_id,
                    "persist": lease.persist,
                    "expires_at": expires_at,
                    "login": None,
                    "_debug_url_internal": lease.debug_url,  # stripped before tool return
                }
            except Exception:
                if steel_session is not None:
                    try:
                        await client.release_session(str(_attr(steel_session, "id")))
                    except Exception:
                        logger.exception("Failed to release Steel session after open error")
                if slot_held:
                    await client.release_session_slot()
                raise

    async def get_playwright(
        self,
        session_handle: str | None = None,
    ) -> tuple[BrowserLease, PlaywrightSession]:
        lease = self._lease
        if lease is None or lease.closed:
            raise BrowserNoSessionError("No active browser session; call browser.session_open first")
        if session_handle and session_handle != lease.handle:
            raise BrowserNoSessionError(f"Unknown session_handle: {session_handle}")
        self._ensure_not_expired(lease)
        if lease.playwright is None:
            raise BrowserNoSessionError("Playwright connection is missing")
        self.touch()
        return lease, lease.playwright

    async def close(
        self,
        *,
        session_handle: str | None = None,
        reason: str = "explicit",
    ) -> dict[str, Any]:
        async with self._lock:
            lease = self._lease
            if lease is None or lease.closed:
                return {
                    "released": False,
                    "profile_id": None,
                    "persist_applied": False,
                    "profile_status": None,
                    "profile_ready": False,
                    "poll_attempts": 0,
                    "poll_elapsed_ms": 0,
                }
            if session_handle and session_handle != lease.handle:
                raise BrowserNoSessionError(f"Unknown session_handle: {session_handle}")

            store = get_browser_profile_store()
            client = get_steel_client()
            release_ok = False
            release_error: str | None = None
            attempts = 0

            try:
                await disconnect_session(lease.playwright)
            except Exception:
                logger.debug("playwright disconnect failed", exc_info=True)
            finally:
                lease.playwright = None

            for attempts in range(1, 4):
                try:
                    await client.release_session(lease.steel_session_id)
                    release_ok = True
                    break
                except Exception as exc:
                    release_error = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "Steel release attempt %s failed for %s: %s",
                        attempts,
                        lease.steel_session_id,
                        exc,
                    )
                    await asyncio.sleep(0.5 * attempts)

            if lease.slot_held:
                await client.release_session_slot()
                lease.slot_held = False

            store.revoke_viewer_tokens_for_session(lease.steel_session_id)
            store.close_session_audit(
                lease.lease_id,
                close_reason=reason,
                release_ok=release_ok,
                error=release_error,
                release_attempts=attempts,
            )
            lease.closed = True
            self._lease = None

            poll = ProfilePollResult(
                ready=False,
                status="none",
                attempts=0,
                poll_elapsed_ms=0,
            )
            if lease.persist and lease.steel_profile_id and release_ok:
                poll = await poll_profile_ready(lease.steel_profile_id)
                status = (
                    PROFILE_STATUS_READY
                    if poll.ready
                    else (PROFILE_STATUS_ERROR if poll.status == "error" else PROFILE_STATUS_UPLOADING)
                )
                store.upsert_profile(
                    telegram_user_id=lease.user_id,
                    steel_profile_id=lease.steel_profile_id,
                    status=status,
                    last_snapshot_at=_iso(_utc_now()) if poll.ready else None,
                    snapshot_error=poll.error,
                    touch_used=True,
                )

            return {
                "released": release_ok,
                "profile_id": lease.steel_profile_id,
                "persist_applied": bool(lease.persist and release_ok),
                "profile_status": poll.status if lease.persist else None,
                "profile_ready": poll.ready,
                "poll_attempts": poll.attempts,
                "poll_elapsed_ms": poll.poll_elapsed_ms,
                "close_reason": reason,
                "error": release_error,
            }

    async def park_login_lease(self) -> bool:
        """Park a login HITL lease so viewer tokens survive agent run_end."""
        async with self._lock:
            lease = self._lease
            if lease is None or lease.closed or lease.purpose != "login":
                return False
            if time.monotonic() >= lease.expires_at:
                return False
            async with _HELD_LOCK:
                existing = _HELD_LOGIN_LEASES.get(lease.user_id)
                if existing is not None and existing.lease_id != lease.lease_id and not existing.closed:
                    # Keep the older held session; close the new one outside.
                    return False
                _HELD_LOGIN_LEASES[lease.user_id] = lease
            self._lease = None
            logger.info(
                "browser login session parked user_id=%s session_id=%s",
                lease.user_id,
                lease.steel_session_id,
            )
            return True

    async def close_all(self, *, reason: str = "run_end") -> None:
        try:
            if reason == "run_end":
                lease = self._lease
                if lease is not None and not lease.closed and lease.purpose == "login":
                    parked = await self.park_login_lease()
                    if parked:
                        return
            await self.close(reason=reason)
        except Exception:
            logger.exception("browser close_all failed reason=%s", reason)

    def idle_or_expired(self) -> str | None:
        lease = self._lease
        if lease is None or lease.closed:
            return None
        settings = get_settings()
        now = time.monotonic()
        if now >= lease.expires_at:
            return "steel_max_session"
        # Login HITL: give the user time to click the link; use session max, not short idle.
        idle_limit = settings.browser_session_idle_close_seconds
        if lease.purpose == "login":
            idle_limit = max(idle_limit, min(settings.browser_session_max_seconds, 900))
        if now - lease.last_activity_at >= idle_limit:
            return "idle"
        return None


def set_browser_session_manager(
    manager: BrowserSessionManager | None,
) -> contextvars.Token:
    return _browser_manager.set(manager)


def reset_browser_session_manager(token: contextvars.Token) -> None:
    _browser_manager.reset(token)


def get_browser_session_manager() -> BrowserSessionManager | None:
    return _browser_manager.get()


def require_browser_session_manager() -> BrowserSessionManager:
    manager = get_browser_session_manager()
    if manager is None:
        raise BrowserNoSessionError(
            "Browser session manager is not active (tool called outside agent run)"
        )
    return manager


async def close_browser_sessions_for_run(run_id: str, *, reason: str = "run_end") -> None:
    manager = get_browser_session_manager()
    if manager is None or manager.run_id != run_id:
        return
    await manager.close_all(reason=reason)


def normalize_steel_profile_status(raw: Any) -> str:
    status = str(_attr(raw, "status") or "").strip().upper()
    if status in {"READY", "OK", "ACTIVE", "COMPLETE", "COMPLETED"}:
        return PROFILE_STATUS_READY
    if status in {"FAILED", "ERROR", "FAIL"}:
        return PROFILE_STATUS_ERROR
    if status in {"UPLOADING", "PENDING", "PROCESSING", "CREATING"}:
        return PROFILE_STATUS_UPLOADING
    if not status:
        return PROFILE_STATUS_UPLOADING
    return status.lower()


async def fetch_profile_status(profile_id: str) -> tuple[str, str | None]:
    """Return (normalized_status, error_message)."""
    client = get_steel_client()
    prof = await client.retrieve_profile(profile_id)
    status = normalize_steel_profile_status(prof)
    err = None
    if status == PROFILE_STATUS_ERROR:
        err = str(_attr(prof, "error") or _attr(prof, "message") or "profile_error")
    return status, err


async def poll_profile_ready(profile_id: str) -> ProfilePollResult:
    settings = get_settings()
    deadline = time.monotonic() + settings.browser_profile_ready_timeout_seconds
    interval = max(0.5, float(settings.browser_profile_ready_poll_interval_seconds))
    attempts = 0
    started = time.monotonic()
    last_status = PROFILE_STATUS_UPLOADING
    last_error: str | None = None
    while time.monotonic() < deadline:
        attempts += 1
        try:
            status, err = await fetch_profile_status(profile_id)
            last_status = status
            last_error = err
            if status == PROFILE_STATUS_READY:
                return ProfilePollResult(
                    ready=True,
                    status=PROFILE_STATUS_READY,
                    attempts=attempts,
                    poll_elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            if status == PROFILE_STATUS_ERROR:
                return ProfilePollResult(
                    ready=False,
                    status=PROFILE_STATUS_ERROR,
                    attempts=attempts,
                    poll_elapsed_ms=int((time.monotonic() - started) * 1000),
                    error=err or "profile_error",
                )
        except Exception as exc:
            last_status = PROFILE_STATUS_UPLOADING
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("profile poll error profile_id=%s: %s", profile_id, last_error)
        await asyncio.sleep(interval)

    return ProfilePollResult(
        ready=False,
        status=last_status or PROFILE_STATUS_UPLOADING,
        attempts=attempts,
        poll_elapsed_ms=int((time.monotonic() - started) * 1000),
        error=last_error or "ready_poll_timeout",
    )


def _attr(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


# Process-wide managers for idle sweeper (weak tracking)
_ACTIVE_MANAGERS: set[BrowserSessionManager] = set()
_ACTIVE_LOCK = asyncio.Lock()


async def register_active_manager(manager: BrowserSessionManager) -> None:
    async with _ACTIVE_LOCK:
        _ACTIVE_MANAGERS.add(manager)


async def unregister_active_manager(manager: BrowserSessionManager) -> None:
    async with _ACTIVE_LOCK:
        _ACTIVE_MANAGERS.discard(manager)


def _held_lease_idle_or_expired(lease: BrowserLease) -> str | None:
    if lease.closed:
        return None
    settings = get_settings()
    now = time.monotonic()
    if now >= lease.expires_at:
        return "steel_max_session"
    idle_limit = max(
        settings.browser_session_idle_close_seconds,
        min(settings.browser_session_max_seconds, 900),
    )
    if now - lease.last_activity_at >= idle_limit:
        return "idle"
    return None


async def _close_held_login_lease(user_id: int, *, reason: str) -> None:
    async with _HELD_LOCK:
        lease = _HELD_LOGIN_LEASES.pop(user_id, None)
    if lease is None or lease.closed:
        return
    mgr = BrowserSessionManager(run_id=lease.run_id, user_id=user_id)
    mgr._lease = lease
    await mgr.close(reason=reason)


async def browser_maintenance_loop(stop_event: asyncio.Event) -> None:
    """Idle/max lifetime closer + orphan release retries."""
    while not stop_event.is_set():
        try:
            async with _ACTIVE_LOCK:
                managers = list(_ACTIVE_MANAGERS)
            for manager in managers:
                reason = manager.idle_or_expired()
                if reason:
                    await manager.close_all(reason=reason)

            async with _HELD_LOCK:
                held_items = list(_HELD_LOGIN_LEASES.items())
            for user_id, lease in held_items:
                reason = _held_lease_idle_or_expired(lease)
                if reason:
                    await _close_held_login_lease(user_id, reason=reason)

            store = get_browser_profile_store()
            client = None
            try:
                if browser_tools_enabled():
                    client = get_steel_client()
            except Exception:
                client = None
            if client is not None:
                for row in store.list_unreleased_audits():
                    if row.release_ok == 1:
                        continue
                    if row.release_attempts >= 3 and row.closed_at:
                        continue
                    try:
                        opened = datetime.fromisoformat(row.opened_at)
                        age = (_utc_now() - opened).total_seconds()
                    except Exception:
                        age = 9999
                    if age < 16 * 60 and row.closed_at is None:
                        # still potentially active; skip unless manager gone
                        continue
                    try:
                        await client.release_session(row.steel_session_id)
                        store.close_session_audit(
                            row.lease_id,
                            close_reason="orphan_sweeper",
                            release_ok=True,
                            release_attempts=row.release_attempts + 1,
                        )
                    except Exception as exc:
                        store.close_session_audit(
                            row.lease_id,
                            close_reason="orphan_sweeper",
                            release_ok=False,
                            error=str(exc),
                            release_attempts=row.release_attempts + 1,
                        )
        except Exception:
            logger.exception("browser maintenance loop error")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            continue
