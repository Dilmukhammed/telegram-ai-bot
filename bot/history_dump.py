from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.loop import Agent
from config import Settings, get_settings
from skills.collapse import SKILL_LOADED_PREFIX, sanitize_expanded_skills_for_context
from skills.session import SkillSessionStore

logger = logging.getLogger(__name__)

DEFAULT_DUMP_PATH = Path("data/context_dump.json")
_PREVIEW_CHARS = 200


def _content_to_text(content: Any) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif block.get("type") == "image_url":
                    parts.append("[image]")
                else:
                    parts.append(f"[{block.get('type', 'block')}]")
        return " ".join(parts)
    return str(content or "")


def _message_chars(message: dict[str, Any]) -> int:
    content = message.get("content")
    total = len(_content_to_text(content))
    tool_calls = message.get("tool_calls") or []
    for call in tool_calls:
        total += len(json.dumps(call, ensure_ascii=False))
    return total


def _message_flags(message: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    role = message.get("role")
    content = _content_to_text(message.get("content"))
    if role == "user" and content.startswith(SKILL_LOADED_PREFIX):
        flags.append("skill_loaded")
    if role == "assistant" and message.get("tool_calls"):
        flags.append("tool_calls")
    if role == "tool":
        flags.append("tool_result")
        if _message_chars(message) > 20_000:
            flags.append("large_tool_result")
    if _message_chars(message) > 50_000:
        flags.append("very_large")
    return flags


def _preview(content: Any) -> str:
    text = _content_to_text(content)
    collapsed = " ".join(text.split())
    if len(collapsed) <= _PREVIEW_CHARS:
        return collapsed
    return f"{collapsed[: _PREVIEW_CHARS - 1]}…"


def _count_turns(messages: list[dict[str, Any]]) -> int:
    return sum(1 for message in messages if message.get("role") == "user")


def analyze_history(messages: list[dict[str, Any]]) -> dict[str, Any]:
    chars_by_role: dict[str, int] = {}
    message_sizes: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        role = str(message.get("role", "?"))
        chars = _message_chars(message)
        chars_by_role[role] = chars_by_role.get(role, 0) + chars
        entry: dict[str, Any] = {
            "index": index,
            "role": role,
            "chars": chars,
            "flags": _message_flags(message),
        }
        if message.get("tool_calls"):
            entry["tool_calls"] = [
                call.get("function", {}).get("name", "?")
                for call in message.get("tool_calls") or []
            ]
        preview = _preview(message.get("content"))
        if preview:
            entry["preview"] = preview
        message_sizes.append(entry)

    message_sizes.sort(key=lambda item: item["chars"], reverse=True)
    return {
        "messages": len(messages),
        "user_turns": _count_turns(messages),
        "chars_total": sum(chars_by_role.values()),
        "chars_by_role": chars_by_role,
        "largest_messages": message_sizes[:15],
    }


def build_history_dump_payload(
    *,
    user_id: int,
    history: list[dict[str, Any]],
    agent: Agent,
    settings: Settings,
    prompt_tokens: int | None = None,
) -> dict[str, Any]:
    sanitized = sanitize_expanded_skills_for_context(history)
    skill_state = SkillSessionStore.get(user_id)
    worker_messages = agent._build_messages("", history)

    system_message = worker_messages[0] if worker_messages else {}
    system_chars = len(_content_to_text(system_message.get("content")))

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "model": settings.openai_model,
        "reasoning_effort": settings.reasoning_effort,
        "chat_max_history": settings.chat_max_history,
        "llm_context_window_tokens": settings.llm_context_window_tokens,
        "prompt_tokens": prompt_tokens,
        "skill_session": {
            "expanded_skill_id": skill_state.expanded_skill_id,
        },
        "summary": {
            **analyze_history(history),
            "sanitized_chars_total": sum(_message_chars(m) for m in sanitized),
            "system_prompt_chars": system_chars,
            "worker_message_count": len(worker_messages),
        },
        "persistent_history": history,
    }


def save_history_dump(payload: dict[str, Any], path: Path | None = None) -> Path:
    target = path or DEFAULT_DUMP_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("context_dump_saved path=%s user_id=%s bytes=%s", target, payload.get("user_id"), target.stat().st_size)
    return target


async def dump_user_context(
    *,
    user_id: int,
    history: list[dict[str, Any]],
    agent: Agent,
    path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    settings = get_settings()
    prompt_tokens: int | None = None
    try:
        worker_messages = agent._build_messages("", history)
        from tools.meta_tools import META_TOOL_DEFINITIONS

        prompt_tokens = await agent._llm.count_prompt_tokens(
            worker_messages,
            tools=META_TOOL_DEFINITIONS,
        )
    except Exception:
        logger.exception("context_dump token count failed user_id=%s", user_id)

    payload = build_history_dump_payload(
        user_id=user_id,
        history=history,
        agent=agent,
        settings=settings,
        prompt_tokens=prompt_tokens,
    )
    saved = save_history_dump(payload, path=path)
    return saved, payload
