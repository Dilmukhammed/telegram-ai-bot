from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest

from config import get_settings, google_oauth_configured

logger = logging.getLogger(__name__)

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_EMAIL_IN_JSON_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)
_OAUTH_BLOCK_MARKERS = (
    "hasn't given you access",
    "has not given you access",
    "developer hasn't given you access",
    "only be accessed by developer-approved testers",
    "has not completed the google verification process",
    "access_denied",
    "error=403",
)


@dataclass(frozen=True)
class GoogleTestUserVerifyResult:
    ok: bool
    found: bool | None
    detail: str


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _load_verify_credentials():
    settings = get_settings()
    sa_path = settings.google_test_users_verify_sa_path.strip()
    if sa_path:
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_file(
            sa_path,
            scopes=[_CLOUD_PLATFORM_SCOPE],
        )

    adc_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if adc_path:
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_file(
            adc_path,
            scopes=[_CLOUD_PLATFORM_SCOPE],
        )

    try:
        import google.auth

        credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
        return credentials
    except Exception:
        return None


def _authorized_headers(credentials) -> dict[str, str]:
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleAuthRequest())
    elif credentials.expired:
        credentials.refresh(GoogleAuthRequest())
    token = credentials.token
    if not token:
        raise RuntimeError("Не удалось получить Google access token для проверки.")
    return {"Authorization": f"Bearer {token}"}


def _extract_emails_from_payload(payload: Any) -> set[str]:
    emails: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in {"email", "emails", "testusers", "test_users"}:
                    if isinstance(item, str) and "@" in item:
                        emails.add(_normalize_email(item))
                    elif isinstance(item, list):
                        for entry in item:
                            if isinstance(entry, str) and "@" in entry:
                                emails.add(_normalize_email(entry))
                            elif isinstance(entry, dict):
                                raw = entry.get("email") or entry.get("value")
                                if isinstance(raw, str) and "@" in raw:
                                    emails.add(_normalize_email(raw))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for match in _EMAIL_IN_JSON_RE.findall(value):
                emails.add(_normalize_email(match))

    walk(payload)
    return emails


def _fetch_test_user_emails_via_api(email: str) -> GoogleTestUserVerifyResult:
    settings = get_settings()
    project_id = settings.google_cloud_project_id.strip()
    if not project_id:
        return GoogleTestUserVerifyResult(
            ok=False,
            found=None,
            detail="GOOGLE_CLOUD_PROJECT_ID не задан — автопроверка через GCP API недоступна.",
        )

    credentials = _load_verify_credentials()
    if credentials is None:
        return GoogleTestUserVerifyResult(
            ok=False,
            found=None,
            detail=(
                "Нет GCP credentials для автопроверки. "
                "Задай GOOGLE_TEST_USERS_VERIFY_SA_PATH или GOOGLE_APPLICATION_CREDENTIALS."
            ),
        )

    try:
        headers = _authorized_headers(credentials)
    except Exception as exc:
        return GoogleTestUserVerifyResult(
            ok=False,
            found=None,
            detail=f"Не удалось авторизоваться в GCP: {exc}",
        )

    project_number = _lookup_project_number(project_id, headers)
    candidates = [
        f"https://oauthconfig.googleapis.com/v1/projects/{project_id}/testUsers",
        f"https://oauthconfig.googleapis.com/v1alpha1/projects/{project_id}/testUsers",
        f"https://oauthconfig.googleapis.com/v1/projects/{project_id}/oauth/testUsers",
    ]
    if project_number:
        candidates.extend(
            [
                f"https://oauthconfig.googleapis.com/v1/projects/{project_number}/testUsers",
                f"https://oauthconfig.googleapis.com/v1alpha1/projects/{project_number}/testUsers",
            ]
        )

    saw_api = False
    collected: set[str] = set()
    last_error = "GCP OAuth test users API недоступен."

    with httpx.Client(timeout=20.0) as client:
        for url in candidates:
            try:
                response = client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"HTTP ошибка при проверке: {exc}"
                continue

            if response.status_code in {401, 403}:
                return GoogleTestUserVerifyResult(
                    ok=False,
                    found=None,
                    detail=(
                        "Нет прав oauthconfig.testusers.get на проект. "
                        "Выдай service account роль roles/oauthconfig.viewer."
                    ),
                )
            if response.status_code == 404:
                continue

            saw_api = True
            if response.status_code >= 400:
                last_error = f"GCP API {response.status_code}: {response.text[:200]}"
                continue

            try:
                payload = response.json()
            except json.JSONDecodeError:
                payload = response.text
            collected.update(_extract_emails_from_payload(payload))

    if collected:
        normalized = _normalize_email(email)
        if normalized in collected:
            return GoogleTestUserVerifyResult(
                ok=True,
                found=True,
                detail="Email найден в Test users (GCP API).",
            )
        return GoogleTestUserVerifyResult(
            ok=True,
            found=False,
            detail="Email не найден в Test users Google Cloud Console.",
        )

    if saw_api:
        return GoogleTestUserVerifyResult(
            ok=False,
            found=None,
            detail=last_error,
        )

    oauth_probe = _probe_oauth_test_user_access(email)
    if oauth_probe.found is not None:
        return oauth_probe

    return GoogleTestUserVerifyResult(
        ok=False,
        found=None,
        detail=last_error,
    )


def _lookup_project_number(project_id: str, headers: dict[str, str]) -> str | None:
    url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{quote(project_id)}"
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, headers=headers)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None
    number = payload.get("projectNumber")
    return str(number) if number else None


def _probe_oauth_test_user_access(email: str) -> GoogleTestUserVerifyResult:
    if not google_oauth_configured():
        return GoogleTestUserVerifyResult(
            ok=False,
            found=None,
            detail="Google OAuth не настроен — OAuth-probe недоступен.",
        )

    settings = get_settings()
    scope = settings.google_oauth_scopes[0] if settings.google_oauth_scopes else "openid email profile"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": scope,
        "login_hint": _normalize_email(email),
        "prompt": "none",
        "include_granted_scopes": "false",
    }
    query = "&".join(f"{key}={quote(str(value))}" for key, value in params.items())
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        return GoogleTestUserVerifyResult(
            ok=False,
            found=None,
            detail=f"OAuth-probe не удался: {exc}",
        )

    haystack = f"{response.url}".lower() + response.text.lower()
    if any(marker in haystack for marker in _OAUTH_BLOCK_MARKERS):
        return GoogleTestUserVerifyResult(
            ok=True,
            found=False,
            detail="OAuth-probe: пользователь не в Test users.",
        )

    if "signin" in haystack or "service login" in haystack or "accountchooser" in haystack:
        return GoogleTestUserVerifyResult(
            ok=False,
            found=None,
            detail="OAuth-probe неоднозначен (нужен login). Настрой SA для точной проверки.",
        )

    return GoogleTestUserVerifyResult(
        ok=False,
        found=None,
        detail="OAuth-probe не дал однозначного ответа.",
    )


def _verify_with_trust_admin(email: str) -> GoogleTestUserVerifyResult:
    normalized = _normalize_email(email)
    if "@" not in normalized:
        return GoogleTestUserVerifyResult(
            ok=True,
            found=False,
            detail="Некорректный email.",
        )
    if not google_oauth_configured():
        return GoogleTestUserVerifyResult(
            ok=False,
            found=None,
            detail="Google OAuth не настроен на сервере.",
        )
    return GoogleTestUserVerifyResult(
        ok=True,
        found=True,
        detail="Подтверждено администратором (без GCP API).",
    )


def verify_google_test_user_email(email: str) -> GoogleTestUserVerifyResult:
    settings = get_settings()
    if settings.google_test_user_verify_trust_admin:
        api_result = _fetch_test_user_emails_via_api(email)
        if api_result.found is not None:
            return api_result
        if api_result.ok and api_result.found is False:
            return api_result
        logger.info("google test user verify falling back to trust-admin: %s", api_result.detail)
        return _verify_with_trust_admin(email)

    return _fetch_test_user_emails_via_api(email)
