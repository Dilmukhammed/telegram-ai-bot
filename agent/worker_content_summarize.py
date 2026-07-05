from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

from config import Settings
from llm import LLMClient

logger = logging.getLogger(__name__)

_MIN_CONTENT_CHARS = 24
_MAX_CONTENT_CHARS = 2000
_DEFAULT_TRUNCATE_LIMIT = 200
_COLLAPSE_STUB_PREFIX = "[Collapsed duplicate tool call"

_SYSTEM_PROMPT = """\
You compress an internal agent planning note written before tool calls.
Output: ONLY a single line of text — a brief Russian note, past tense, ≤120 characters.
Keep tool names when useful (e.g. yandex.music.users_likes_tracks).
No markdown, no quotes, no extra commentary.
"""


def _should_summarize_assistant_content(message: dict[str, Any]) -> bool:
    if message.get("role") != "assistant":
        return False
    tool_calls = message.get("tool_calls")
    if not tool_calls:
        return False
    content = message.get("content")
    if not isinstance(content, str):
        return False
    text = content.strip()
    if len(text) < _MIN_CONTENT_CHARS:
        return False
    if text.startswith(_COLLAPSE_STUB_PREFIX):
        return False
    return True


def _truncate_fallback(text: str, limit: int = _DEFAULT_TRUNCATE_LIMIT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


async def _summarize_single(
    content: str, *, llm: LLMClient, truncate_limit: int
) -> str:
    truncated = content.strip()[:_MAX_CONTENT_CHARS]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": truncated},
    ]
    try:
        raw = await llm.chat_without_reasoning(messages, max_tokens=128)
    except Exception as exc:
        logger.warning("worker_content_summarize llm failed: %s", exc)
        return _truncate_fallback(content, truncate_limit)
    summary = raw.strip()
    if not summary or len(summary) < 5:
        return _truncate_fallback(content, truncate_limit)
    return summary[:truncate_limit]


async def summarize_worker_assistant_content(
    worker: list[dict[str, Any]],
    *,
    llm: LLMClient,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Replace verbose assistant planning content (with tool_calls) before persist."""
    truncate_limit = (
        settings.worker_content_summarize_max_chars
        if settings is not None
        else _DEFAULT_TRUNCATE_LIMIT
    )
    out = copy.deepcopy(worker)
    targets: list[tuple[int, str]] = []
    for index, message in enumerate(out):
        if _should_summarize_assistant_content(message):
            targets.append((index, str(message["content"]).strip()))

    if not targets:
        return out

    summaries = await asyncio.gather(
        *[_summarize_single(text, llm=llm, truncate_limit=truncate_limit) for _, text in targets]
    )

    for (index, _original), summary in zip(targets, summaries, strict=True):
        if summary:
            out[index]["content"] = summary
        else:
            out[index].pop("content", None)

    logger.info("worker_content_summarize applied count=%s", len(targets))
    return out
