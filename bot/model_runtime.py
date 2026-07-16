from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from typing import TYPE_CHECKING

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data/runtime_model.json")
_lock = threading.RLock()
_override_model: str | None = None
_last_listed: list[str] = []
_loaded = False

CALLBACK_PREFIX = "mdl:"
CALLBACK_SET_PREFIX = "mdl:i:"
CALLBACK_RESET = "mdl:reset"
CALLBACK_REFRESH = "mdl:refresh"
_BUTTON_TEXT_MAX = 64


def _runtime_path() -> Path:
    return _DEFAULT_PATH


def _ensure_loaded() -> None:
    global _loaded, _override_model
    if _loaded:
        return
    path = _runtime_path()
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            model = str(raw.get("model") or "").strip()
            _override_model = model or None
    except Exception:
        logger.exception("runtime_model_load_failed path=%s", path)
        _override_model = None
    _loaded = True


def active_agent_model(default: str) -> str:
    with _lock:
        _ensure_loaded()
        return (_override_model or default).strip() or default


def current_override() -> str | None:
    with _lock:
        _ensure_loaded()
        return _override_model


def set_agent_model(model: str) -> str:
    cleaned = model.strip()
    if not cleaned:
        raise ValueError("model id is empty")
    with _lock:
        global _override_model, _loaded
        _override_model = cleaned
        _loaded = True
        _persist_unlocked()
    logger.info("runtime_agent_model_set model=%s", cleaned)
    return cleaned


def clear_agent_model() -> None:
    with _lock:
        global _override_model, _loaded
        _override_model = None
        _loaded = True
        path = _runtime_path()
        if path.is_file():
            path.unlink()
    logger.info("runtime_agent_model_cleared")


def last_listed_models() -> list[str]:
    with _lock:
        return list(_last_listed)


def remember_listed_models(models: list[str]) -> None:
    with _lock:
        global _last_listed
        _last_listed = list(models)


def resolve_model_arg(arg: str, *, default: str) -> str:
    """Resolve `/model` argument: exact id, or 1-based index from last list."""
    text = arg.strip()
    if not text:
        raise ValueError("empty model")
    if text.lower() in {"reset", "default", "env"}:
        clear_agent_model()
        return active_agent_model(default)
    if text.isdigit():
        idx = int(text)
        listed = last_listed_models()
        if not listed:
            raise ValueError("no model list yet — run /model list first")
        if idx < 1 or idx > len(listed):
            raise ValueError(f"index out of range 1..{len(listed)}")
        return set_agent_model(listed[idx - 1])
    return set_agent_model(text)


def _persist_unlocked() -> None:
    path = _runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model": _override_model}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def should_send_reasoning_effort(model: str) -> bool:
    """9router antigravity/mistral ids reject Fireworks-style reasoning_effort."""
    name = (model or "").strip().lower()
    return not (name.startswith("ag/") or name.startswith("mistral/"))


async def fetch_provider_models(*, base_url: str, api_key: str) -> list[str]:
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    page = await client.models.list()
    ids = sorted({item.id for item in page.data if getattr(item, "id", None)})
    remember_listed_models(ids)
    return ids


def model_button_label(model_id: str, *, active: bool) -> str:
    prefix = "✓ " if active else ""
    # Prefer the short suffix after provider prefix (ag/..., mistral/...).
    short = model_id.split("/", 1)[-1] if "/" in model_id else model_id
    label = f"{prefix}{short}"
    if len(label) <= _BUTTON_TEXT_MAX:
        return label
    keep = _BUTTON_TEXT_MAX - 1
    return label[:keep] + "…"


def build_model_keyboard(
    models: list[str],
    *,
    active: str,
) -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows: list[list[InlineKeyboardButton]] = []
    for idx, model_id in enumerate(models):
        rows.append(
            [
                InlineKeyboardButton(
                    text=model_button_label(model_id, active=(model_id == active)),
                    callback_data=f"{CALLBACK_SET_PREFIX}{idx}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="↻ Refresh", callback_data=CALLBACK_REFRESH),
            InlineKeyboardButton(text="↺ Reset env", callback_data=CALLBACK_RESET),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_model_callback(data: str) -> tuple[str, int | None] | None:
    text = (data or "").strip()
    if not text.startswith(CALLBACK_PREFIX):
        return None
    if text == CALLBACK_RESET:
        return ("reset", None)
    if text == CALLBACK_REFRESH:
        return ("refresh", None)
    if text.startswith(CALLBACK_SET_PREFIX):
        raw = text[len(CALLBACK_SET_PREFIX) :]
        if not raw.isdigit():
            return None
        return ("set", int(raw))
    return None


def format_model_picker(*, default_model: str, base_url: str, models: list[str]) -> str:
    active = active_agent_model(default_model)
    override = current_override()
    source = "runtime override" if override else "env OPENAI_MODEL"
    lines = [
        f"Active: `{active}`",
        f"Source: {source}",
        f"Env default: `{default_model}`",
        f"Base: `{base_url}`",
        "",
        f"Tap a model ({len(models)}):",
    ]
    return "\n".join(lines)


def format_model_status(*, default_model: str, base_url: str) -> str:
    active = active_agent_model(default_model)
    override = current_override()
    source = "runtime override" if override else "env OPENAI_MODEL"
    return (
        f"Active model: `{active}`\n"
        f"Source: {source}\n"
        f"Env default: `{default_model}`\n"
        f"Base URL: `{base_url}`\n\n"
        "Tap a button below, or:\n"
        "/model &lt;id&gt; — set by id\n"
        "/model reset — back to env default"
    )


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
