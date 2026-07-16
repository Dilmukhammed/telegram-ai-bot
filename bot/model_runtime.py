from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup
    from config import Settings

logger = logging.getLogger(__name__)

RoleName = Literal["agent", "summarize", "checker"]
ProviderId = Literal["fireworks", "9router", "openai"]

ROLES: tuple[RoleName, ...] = ("agent", "summarize", "checker")
PROVIDERS: tuple[ProviderId, ...] = ("fireworks", "9router", "openai")

ROLE_CODE: dict[RoleName, str] = {"agent": "a", "summarize": "s", "checker": "c"}
CODE_ROLE: dict[str, RoleName] = {v: k for k, v in ROLE_CODE.items()}
PROVIDER_CODE: dict[ProviderId, str] = {
    "fireworks": "fw",
    "9router": "nr",
    "openai": "oa",
}
CODE_PROVIDER: dict[str, ProviderId] = {v: k for k, v in PROVIDER_CODE.items()}

DEFAULT_FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
DEFAULT_NINEROUTER_BASE_URL = "http://127.0.0.1:20128/v1"
DEFAULT_FIREWORKS_AGENT_MODEL = "accounts/fireworks/models/glm-5p2"
DEFAULT_FIREWORKS_SUMMARIZE_MODEL = "accounts/fireworks/models/deepseek-v4-flash"

_DEFAULT_PATH = Path("data/runtime_models.json")
_LEGACY_PATH = Path("data/runtime_model.json")
_lock = threading.RLock()
_loaded = False
# role -> {provider?: str, model?: str}
_overrides: dict[str, dict[str, str]] = {}
# provider_id -> last listed model ids (for index pick)
_last_listed_by_provider: dict[str, list[str]] = {}

CALLBACK_PREFIX = "mdl:"
_BUTTON_TEXT_MAX = 64


@dataclass(frozen=True)
class ResolvedEndpoint:
    role: RoleName
    provider: ProviderId
    base_url: str
    api_key: str
    model: str
    source: str  # env | runtime


def _runtime_path() -> Path:
    return _DEFAULT_PATH


def _legacy_path() -> Path:
    return _LEGACY_PATH


def _ensure_loaded() -> None:
    global _loaded, _overrides
    if _loaded:
        return
    path = _runtime_path()
    legacy = _legacy_path()
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            _overrides = _normalize_payload(raw)
        elif legacy.is_file():
            raw = json.loads(legacy.read_text(encoding="utf-8"))
            model = str(raw.get("model") or "").strip()
            _overrides = {"agent": {"model": model}} if model else {}
            _persist_unlocked()
            try:
                legacy.unlink()
            except Exception:
                pass
        else:
            _overrides = {}
    except Exception:
        logger.exception("runtime_models_load_failed path=%s", path)
        _overrides = {}
    _loaded = True


def _normalize_payload(raw: Any) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not isinstance(raw, dict):
        return out
    # New format: {"roles": {"agent": {"provider": "...", "model": "..."}}}
    roles = raw.get("roles")
    if isinstance(roles, dict):
        for role in ROLES:
            entry = roles.get(role)
            if not isinstance(entry, dict):
                continue
            cleaned: dict[str, str] = {}
            provider = str(entry.get("provider") or "").strip().lower()
            model = str(entry.get("model") or "").strip()
            if provider in PROVIDERS:
                cleaned["provider"] = provider
            if model:
                cleaned["model"] = model
            if cleaned:
                out[role] = cleaned
        return out
    # Legacy single-model file migrated into this shape already handled separately.
    model = str(raw.get("model") or "").strip()
    if model:
        out["agent"] = {"model": model}
    return out


def _persist_unlocked() -> None:
    path = _runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"roles": {role: dict(_overrides.get(role, {})) for role in ROLES if _overrides.get(role)}}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _role_override(role: RoleName) -> dict[str, str]:
    with _lock:
        _ensure_loaded()
        return dict(_overrides.get(role) or {})


def set_role_model(role: RoleName, model: str) -> str:
    cleaned = model.strip()
    if not cleaned:
        raise ValueError("model id is empty")
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    with _lock:
        global _loaded
        _ensure_loaded()
        entry = dict(_overrides.get(role) or {})
        entry["model"] = cleaned
        _overrides[role] = entry
        _loaded = True
        _persist_unlocked()
    logger.info("runtime_model_set role=%s model=%s", role, cleaned)
    return cleaned


def set_role_provider(role: RoleName, provider: ProviderId) -> ProviderId:
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    with _lock:
        global _loaded
        _ensure_loaded()
        entry = dict(_overrides.get(role) or {})
        entry["provider"] = provider
        # Clear model when switching provider — list again for that backend.
        entry.pop("model", None)
        _overrides[role] = entry
        _loaded = True
        _persist_unlocked()
    logger.info("runtime_provider_set role=%s provider=%s", role, provider)
    return provider


def clear_role(role: RoleName) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    with _lock:
        global _loaded
        _ensure_loaded()
        _overrides.pop(role, None)
        _loaded = True
        if any(_overrides.values()):
            _persist_unlocked()
        else:
            path = _runtime_path()
            if path.is_file():
                path.unlink()
    logger.info("runtime_role_cleared role=%s", role)


def clear_agent_model() -> None:
    """Backward-compatible alias."""
    clear_role("agent")


def set_agent_model(model: str) -> str:
    return set_role_model("agent", model)


def current_override() -> str | None:
    """Backward-compatible: agent model override only."""
    return _role_override("agent").get("model")


def active_agent_model(default: str) -> str:
    return active_model("agent", default)


def active_model(role: RoleName, default: str) -> str:
    override = _role_override(role).get("model")
    return (override or default).strip() or default


def active_provider(role: RoleName, default: ProviderId) -> ProviderId:
    override = _role_override(role).get("provider")
    if override in PROVIDERS:
        return override  # type: ignore[return-value]
    return default


def remember_listed_models(models: list[str], *, provider: ProviderId | None = None) -> None:
    with _lock:
        key = provider or "_default"
        _last_listed_by_provider[key] = list(models)


def last_listed_models(*, provider: ProviderId | None = None) -> list[str]:
    with _lock:
        key = provider or "_default"
        return list(_last_listed_by_provider.get(key) or [])


def infer_provider_from_base_url(base_url: str) -> ProviderId:
    text = (base_url or "").lower()
    if "fireworks.ai" in text:
        return "fireworks"
    if "20128" in text or "9router" in text:
        return "9router"
    return "openai"


def provider_credentials(settings: "Settings", provider: ProviderId) -> tuple[str, str]:
    """Return (base_url, api_key) for a named provider."""
    if provider == "fireworks":
        base = (settings.fireworks_base_url or DEFAULT_FIREWORKS_BASE_URL).rstrip("/")
        key = settings.fireworks_api_key or settings.openai_api_key
        return base, key
    if provider == "9router":
        base = (settings.ninerouter_base_url or DEFAULT_NINEROUTER_BASE_URL).rstrip("/")
        key = settings.ninerouter_api_key or settings.openai_api_key
        return base, key
    # openai / custom — OPENAI_* triplet as configured in .env
    return settings.openai_base_url.rstrip("/"), settings.openai_api_key


def default_provider_for_role(settings: "Settings", role: RoleName) -> ProviderId:
    if role == "agent":
        return infer_provider_from_base_url(settings.openai_base_url)
    if role == "summarize":
        return infer_provider_from_base_url(settings.summarize_base_url)
    return infer_provider_from_base_url(settings.checker_base_url)


def default_model_for_role(settings: "Settings", role: RoleName) -> str:
    if role == "agent":
        return settings.openai_model
    if role == "summarize":
        return settings.summarize_model
    return settings.checker_model


def default_model_for_provider(provider: ProviderId, role: RoleName) -> str | None:
    if provider == "fireworks":
        if role == "agent":
            return DEFAULT_FIREWORKS_AGENT_MODEL
        return DEFAULT_FIREWORKS_SUMMARIZE_MODEL
    return None


def resolve_endpoint(settings: "Settings", role: RoleName) -> ResolvedEndpoint:
    """Resolve provider/base/key/model for an LLM role (runtime overrides win)."""
    # Checker follows summarize unless checker has its own runtime override.
    if role == "checker" and not _role_override("checker"):
        followed = _resolve_endpoint_for_role(settings, "summarize")
        return ResolvedEndpoint(
            role="checker",
            provider=followed.provider,
            base_url=followed.base_url,
            api_key=followed.api_key,
            model=followed.model,
            source=f"follow-summarize/{followed.source}",
        )
    return _resolve_endpoint_for_role(settings, role)


def _resolve_endpoint_for_role(settings: "Settings", role: RoleName) -> ResolvedEndpoint:
    provider = active_provider(role, default_provider_for_role(settings, role))
    base_url, api_key = provider_credentials(settings, provider)
    env_model = default_model_for_role(settings, role)
    model_override = _role_override(role).get("model")
    if model_override:
        model = model_override
        source = "runtime"
    else:
        env_provider = default_provider_for_role(settings, role)
        if provider != env_provider:
            model = default_model_for_provider(provider, role) or env_model
            source = "provider-default"
        else:
            model = env_model
            source = "env"
    return ResolvedEndpoint(
        role=role,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        source=source,
    )


def profile_to_role(profile: str) -> RoleName:
    if profile in {"summarize", "coach", "extraction"}:
        return "summarize"
    if profile == "checker":
        return "checker"
    return "agent"


def resolve_model_arg(arg: str, *, role: RoleName, default: str, provider: ProviderId) -> str:
    text = arg.strip()
    if not text:
        raise ValueError("empty model")
    if text.lower() in {"reset", "default", "env"}:
        clear_role(role)
        return active_model(role, default)
    if text.isdigit():
        idx = int(text)
        listed = last_listed_models(provider=provider)
        if not listed:
            raise ValueError("no model list yet — run /model list first")
        if idx < 1 or idx > len(listed):
            raise ValueError(f"index out of range 1..{len(listed)}")
        return set_role_model(role, listed[idx - 1])
    return set_role_model(role, text)


def should_send_reasoning_effort(model: str) -> bool:
    """9router antigravity/mistral ids reject Fireworks-style reasoning_effort."""
    name = (model or "").strip().lower()
    return not (name.startswith("ag/") or name.startswith("mistral/"))


async def fetch_provider_models(*, base_url: str, api_key: str, provider: ProviderId | None = None) -> list[str]:
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    page = await client.models.list()
    ids = sorted({item.id for item in page.data if getattr(item, "id", None)})
    remember_listed_models(ids, provider=provider or infer_provider_from_base_url(base_url))
    return ids


def model_button_label(model_id: str, *, active: bool) -> str:
    prefix = "✓ " if active else ""
    short = model_id.split("/", 1)[-1] if "/" in model_id else model_id
    # Fireworks long ids: keep last two segments when useful
    if model_id.startswith("accounts/fireworks/models/"):
        short = model_id.rsplit("/", 1)[-1]
    label = f"{prefix}{short}"
    if len(label) <= _BUTTON_TEXT_MAX:
        return label
    keep = _BUTTON_TEXT_MAX - 1
    return label[:keep] + "…"


def build_model_keyboard(
    models: list[str],
    *,
    active: str,
    role: RoleName,
    provider: ProviderId,
) -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rc = ROLE_CODE[role]
    rows: list[list[InlineKeyboardButton]] = []

    # Role switcher
    role_row: list[InlineKeyboardButton] = []
    for r in ROLES:
        mark = "·" if r != role else "●"
        role_row.append(
            InlineKeyboardButton(
                text=f"{mark} {r}",
                callback_data=f"mdl:{ROLE_CODE[r]}:role",
            )
        )
    rows.append(role_row)

    # Provider switcher
    prov_row: list[InlineKeyboardButton] = []
    for p in PROVIDERS:
        mark = "✓" if p == provider else ""
        label = f"{mark}{p}"[:16]
        prov_row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"mdl:{rc}:p:{PROVIDER_CODE[p]}",
            )
        )
    rows.append(prov_row)

    for idx, model_id in enumerate(models):
        rows.append(
            [
                InlineKeyboardButton(
                    text=model_button_label(model_id, active=(model_id == active)),
                    callback_data=f"mdl:{rc}:i:{idx}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="↻ Refresh", callback_data=f"mdl:{rc}:refresh"),
            InlineKeyboardButton(text="↺ Reset env", callback_data=f"mdl:{rc}:reset"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_model_callback(data: str) -> dict[str, Any] | None:
    """Parse callback into {role, action, index?, provider?}."""
    text = (data or "").strip()
    if not text.startswith(CALLBACK_PREFIX):
        return None
    parts = text.split(":")
    # mdl:<rolecode>:<action>[:payload]
    if len(parts) < 3:
        return None
    role = CODE_ROLE.get(parts[1])
    if role is None:
        return None
    action = parts[2]
    if action == "role":
        return {"role": role, "action": "role"}
    if action == "refresh":
        return {"role": role, "action": "refresh"}
    if action == "reset":
        return {"role": role, "action": "reset"}
    if action == "i" and len(parts) >= 4 and parts[3].isdigit():
        return {"role": role, "action": "set", "index": int(parts[3])}
    if action == "p" and len(parts) >= 4:
        provider = CODE_PROVIDER.get(parts[3])
        if provider is None:
            return None
        return {"role": role, "action": "provider", "provider": provider}
    return None


def format_model_picker(
    *,
    settings: "Settings",
    role: RoleName,
    models: list[str],
) -> str:
    ep = resolve_endpoint(settings, role)
    lines = [
        f"Role: `{role}`",
        f"Provider: `{ep.provider}`",
        f"Active model: `{ep.model}`",
        f"Source: {ep.source}",
        f"Base: `{ep.base_url}`",
        "",
        f"Tap a model ({len(models)}):",
        "",
        "Commands:",
        f"/model {role} &lt;id|N|reset&gt;",
        f"/provider {role} fireworks|9router|openai",
    ]
    return "\n".join(lines)


def format_model_status(*, settings: "Settings") -> str:
    lines = ["LLM roles:"]
    for role in ROLES:
        ep = resolve_endpoint(settings, role)
        lines.append(f"• `{role}`: `{ep.model}` @ `{ep.provider}` ({ep.source})")
    lines.append("")
    lines.append("/model [agent|summarize|checker] — picker")
    lines.append("/provider [role] fireworks|9router|openai")
    return "\n".join(lines)


def format_model_list(models: list[str], *, active: str) -> str:
    if not models:
        return "Provider returned no models."
    lines = [f"Models ({len(models)}):"]
    for i, model_id in enumerate(models, start=1):
        mark = " ←" if model_id == active else ""
        lines.append(f"{i}. `{model_id}`{mark}")
    lines.append("")
    lines.append("Or tap a button / use /model <N>")
    return "\n".join(lines)


def parse_role_arg(text: str) -> RoleName | None:
    cleaned = (text or "").strip().lower()
    aliases = {
        "agent": "agent",
        "a": "agent",
        "main": "agent",
        "summarize": "summarize",
        "summary": "summarize",
        "s": "summarize",
        "util": "summarize",
        "checker": "checker",
        "check": "checker",
        "c": "checker",
    }
    role = aliases.get(cleaned)
    return role  # type: ignore[return-value]


def parse_provider_arg(text: str) -> ProviderId | None:
    cleaned = (text or "").strip().lower()
    aliases = {
        "fireworks": "fireworks",
        "fw": "fireworks",
        "9router": "9router",
        "ninerouter": "9router",
        "nr": "9router",
        "openai": "openai",
        "oa": "openai",
        "custom": "openai",
    }
    provider = aliases.get(cleaned)
    return provider  # type: ignore[return-value]
