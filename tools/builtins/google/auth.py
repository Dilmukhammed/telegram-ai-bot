from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import google_auth_oauthlib.flow
import googleapiclient.discovery
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import get_settings, google_oauth_configured
from tools.builtins.google.errors import (
    DriveScopeMissingError,
    GmailScopeMissingError,
    GoogleNotConnectedError,
    GoogleOAuthNotConfiguredError,
    SheetsScopeMissingError,
    TasksScopeMissingError,
)
from tools.builtins.google.oauth_pending_store import get_oauth_pending_store
from tools.builtins.google.token_store import StoredGoogleToken, get_token_store

GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_FULL_SCOPE = "https://mail.google.com/"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"

_LOCALHOST_CALLBACK_RE = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?/[^\s)\"'<>]*",
    re.IGNORECASE,
)


def _client_config() -> dict[str, Any]:
    settings = get_settings()
    if not google_oauth_configured():
        raise GoogleOAuthNotConfiguredError(
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )
    client_type = settings.google_oauth_client_type
    if client_type not in {"web", "installed"}:
        client_type = "installed"
    return {
        client_type: {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def _scopes() -> list[str]:
    return list(get_settings().google_oauth_scopes)


def create_oauth_flow() -> google_auth_oauthlib.flow.Flow:
    settings = get_settings()
    return google_auth_oauthlib.flow.Flow.from_client_config(
        _client_config(),
        scopes=_scopes(),
        redirect_uri=settings.google_redirect_uri,
    )


def looks_like_manual_oauth_callback(text: str) -> bool:
    lowered = text.lower()
    if "code=" not in lowered:
        return False
    return "localhost" in lowered or "127.0.0.1" in lowered


def _extract_callback_url(text: str) -> str:
    match = _LOCALHOST_CALLBACK_RE.search(text)
    return match.group(0).rstrip(".,;") if match else text.strip()


def extract_oauth_code_from_text(text: str) -> str | None:
    raw = _extract_callback_url(text)
    if not raw or ("code=" not in raw and "error=" not in raw):
        return None

    if raw.startswith("http://") or raw.startswith("https://"):
        query = urlparse(raw).query
    elif raw.startswith("?"):
        query = raw[1:]
    elif "code=" in raw and "&" in raw:
        query = raw
    else:
        return None

    params = parse_qs(query, keep_blank_values=False)
    if params.get("error"):
        raise RuntimeError(f"Google OAuth error: {params['error'][0]}")
    codes = params.get("code")
    if not codes or not codes[0].strip():
        return None
    return codes[0].strip()


def extract_oauth_state_from_text(text: str) -> int | None:
    raw = _extract_callback_url(text)
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        query = urlparse(raw).query
    else:
        return None
    states = parse_qs(query, keep_blank_values=False).get("state")
    if not states or not states[0].isdigit():
        return None
    return int(states[0])


def missing_oauth_scopes(stored: StoredGoogleToken | None) -> list[str]:
    if stored is None:
        return []
    required = set(_scopes())
    granted = set(stored.scopes or ())
    return sorted(required - granted)


def build_authorization_url(telegram_user_id: int) -> str:
    flow = create_oauth_flow()
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="false",
        state=str(telegram_user_id),
    )
    if flow.code_verifier:
        get_oauth_pending_store().save_verifier(telegram_user_id, flow.code_verifier)
    return authorization_url


def exchange_authorization_code(telegram_user_id: int, code: str) -> Credentials:
    code_verifier = get_oauth_pending_store().pop_verifier(telegram_user_id)
    if not code_verifier:
        raise RuntimeError(
            "OAuth session expired or missing PKCE verifier. Run /connect_google again."
        )
    flow = create_oauth_flow()
    # Google may return extra scopes (e.g. openid) beyond the auth request.
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    flow.fetch_token(code=code, code_verifier=code_verifier)
    credentials = flow.credentials
    if not credentials.refresh_token:
        raise RuntimeError("Google did not return a refresh token. Try /connect_google again.")
    return credentials


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """google-auth compares expiry with naive utcnow(); keep expiry naive UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def credentials_from_stored(stored: StoredGoogleToken) -> Credentials:
    settings = get_settings()
    expiry = _to_naive_utc(stored.token_expiry)
    return Credentials(
        token=stored.access_token,
        refresh_token=stored.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=list(stored.scopes) or _scopes(),
        expiry=expiry,
    )


def refresh_credentials(credentials: Credentials) -> None:
    credentials.refresh(Request())


def build_calendar_service(credentials: Credentials):
    return googleapiclient.discovery.build(
        "calendar",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def build_gmail_service(credentials: Credentials):
    return googleapiclient.discovery.build(
        "gmail",
        "v1",
        credentials=credentials,
        cache_discovery=False,
    )


def build_drive_service(credentials: Credentials):
    return googleapiclient.discovery.build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def build_sheets_service(credentials: Credentials):
    return googleapiclient.discovery.build(
        "sheets",
        "v4",
        credentials=credentials,
        cache_discovery=False,
    )


def build_tasks_service(credentials: Credentials):
    return googleapiclient.discovery.build(
        "tasks",
        "v1",
        credentials=credentials,
        cache_discovery=False,
    )


def user_has_gmail_scope(stored: StoredGoogleToken | None) -> bool:
    if stored is None:
        return False
    scopes = set(stored.scopes or ())
    return GMAIL_MODIFY_SCOPE in scopes or GMAIL_FULL_SCOPE in scopes


def user_has_drive_scope(stored: StoredGoogleToken | None) -> bool:
    if stored is None:
        return False
    return DRIVE_SCOPE in set(stored.scopes or ())


def user_has_sheets_scope(stored: StoredGoogleToken | None) -> bool:
    if stored is None:
        return False
    return SHEETS_SCOPE in set(stored.scopes or ())


def user_has_tasks_scope(stored: StoredGoogleToken | None) -> bool:
    if stored is None:
        return False
    return TASKS_SCOPE in set(stored.scopes or ())


async def fetch_google_email(credentials: Credentials) -> str | None:
    def _fetch() -> str | None:
        try:
            oauth2 = googleapiclient.discovery.build(
                "oauth2",
                "v2",
                credentials=credentials,
                cache_discovery=False,
            )
            profile = oauth2.userinfo().get().execute()
            email = profile.get("email")
            if email:
                return email
        except Exception:
            pass

        try:
            calendar = build_calendar_service(credentials)
            primary = calendar.calendars().get(calendarId="primary").execute()
            calendar_id = primary.get("id") or ""
            if "@" in calendar_id:
                return calendar_id
        except Exception:
            pass
        return None

    return await asyncio.to_thread(_fetch)


def save_credentials(telegram_user_id: int, credentials: Credentials, email: str | None) -> None:
    expiry = _to_naive_utc(credentials.expiry)
    if credentials.refresh_token:
        refresh_token = credentials.refresh_token
    else:
        existing = get_token_store().get(telegram_user_id)
        refresh_token = existing.refresh_token if existing else None
    if not refresh_token:
        raise RuntimeError("Missing Google refresh token")
    get_token_store().save(
        telegram_user_id=telegram_user_id,
        email=email,
        refresh_token=refresh_token,
        access_token=credentials.token,
        token_expiry=expiry,
        scopes=tuple(credentials.scopes or _scopes()),
    )


async def complete_oauth(telegram_user_id: int, code: str) -> StoredGoogleToken:
    credentials = await asyncio.to_thread(exchange_authorization_code, telegram_user_id, code)
    if not credentials.token:
        raise RuntimeError("Google did not return an access token. Try /connect_google again.")
    email = await fetch_google_email(credentials)
    save_credentials(telegram_user_id, credentials, email)
    stored = get_token_store().get(telegram_user_id)
    if stored is None:
        raise RuntimeError("Failed to persist Google credentials")
    return stored


async def get_credentials_for_user(telegram_user_id: int) -> Credentials:
    stored = get_token_store().get(telegram_user_id)
    if stored is None:
        raise GoogleNotConnectedError(
            "Google is not connected. Use /connect_google or google.auth.connect_url."
        )
    credentials = credentials_from_stored(stored)
    if credentials.expired and credentials.refresh_token:
        await asyncio.to_thread(refresh_credentials, credentials)
        save_credentials(telegram_user_id, credentials, stored.email)
    return credentials


async def get_calendar_service(telegram_user_id: int):
    credentials = await get_credentials_for_user(telegram_user_id)
    return await asyncio.to_thread(build_calendar_service, credentials)


async def get_gmail_service(telegram_user_id: int):
    stored = get_token_store().get(telegram_user_id)
    if stored is None:
        raise GoogleNotConnectedError(
            "Google is not connected. Use /connect_google or google.auth.connect_url."
        )
    if not user_has_gmail_scope(stored):
        raise GmailScopeMissingError(
            "Gmail access is not granted. Run /connect_google again to approve Gmail scopes."
        )
    credentials = await get_credentials_for_user(telegram_user_id)
    return await asyncio.to_thread(build_gmail_service, credentials)


async def get_drive_service(telegram_user_id: int):
    stored = get_token_store().get(telegram_user_id)
    if stored is None:
        raise GoogleNotConnectedError(
            "Google is not connected. Use /connect_google or google.auth.connect_url."
        )
    if not user_has_drive_scope(stored):
        raise DriveScopeMissingError(
            "Drive access is not granted. Run /connect_google again to approve Drive scopes."
        )
    credentials = await get_credentials_for_user(telegram_user_id)
    return await asyncio.to_thread(build_drive_service, credentials)


async def get_sheets_service(telegram_user_id: int):
    stored = get_token_store().get(telegram_user_id)
    if stored is None:
        raise GoogleNotConnectedError(
            "Google is not connected. Use /connect_google or google.auth.connect_url."
        )
    if not user_has_sheets_scope(stored):
        raise SheetsScopeMissingError(
            "Sheets access is not granted. Run /connect_google again to approve Sheets scopes."
        )
    credentials = await get_credentials_for_user(telegram_user_id)
    return await asyncio.to_thread(build_sheets_service, credentials)


async def get_tasks_service(telegram_user_id: int):
    stored = get_token_store().get(telegram_user_id)
    if stored is None:
        raise GoogleNotConnectedError(
            "Google is not connected. Use /connect_google or google.auth.connect_url."
        )
    if not user_has_tasks_scope(stored):
        raise TasksScopeMissingError(
            "Tasks access is not granted. Run /connect_google again to approve Tasks scopes."
        )
    credentials = await get_credentials_for_user(telegram_user_id)
    return await asyncio.to_thread(build_tasks_service, credentials)


async def revoke_and_delete(telegram_user_id: int) -> bool:
    stored = get_token_store().get(telegram_user_id)
    if stored is None:
        return False
    credentials = credentials_from_stored(stored)
    try:
        await asyncio.to_thread(credentials.revoke, Request())
    except Exception:
        pass
    return get_token_store().delete(telegram_user_id)


def auth_status_payload(telegram_user_id: int) -> dict[str, Any]:
    if not google_oauth_configured():
        return {
            "configured": False,
            "connected": False,
            "email": None,
            "scopes": [],
            "gmail_ready": False,
            "drive_ready": False,
            "sheets_ready": False,
            "tasks_ready": False,
        }
    stored = get_token_store().get(telegram_user_id)
    return {
        "configured": True,
        "connected": stored is not None,
        "email": stored.email if stored else None,
        "scopes": list(stored.scopes) if stored else list(_scopes()),
        "gmail_ready": user_has_gmail_scope(stored),
        "drive_ready": user_has_drive_scope(stored),
        "sheets_ready": user_has_sheets_scope(stored),
        "tasks_ready": user_has_tasks_scope(stored),
    }
