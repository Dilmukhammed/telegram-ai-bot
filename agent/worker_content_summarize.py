from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

from config import Settings
from llm import LLMClient

logger = logging.getLogger(__name__)

_MIN_CONTENT_CHARS = 24
_MAX_LINE_INPUT_CHARS = 1500
_MAX_BATCH_INPUT_CHARS = 8000
_COLLAPSE_STUB_PREFIX = "[Collapsed duplicate tool call"

_SYSTEM_PROMPT = """\
You compress internal agent planning notes written before tool calls.
Input: numbered lines (often English) describing what the agent decided to do next.
Output: ONLY a JSON array of strings — same length and order as the input lines.

Rules for each summary string:
- Brief Russian note, past tense, ≤120 characters
- Keep tool names when useful (e.g. yandex.music.users_likes_tracks)
- Use "" for pure noise / empty planning with no useful intent
- No markdown, no extra keys, no commentary outside the JSON array
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


def _truncate_line(text: str, limit: int = _MAX_LINE_INPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _build_batch_user_content(lines: list[str]) -> str:
    parts: list[str] = []
    total = 0
    for index, line in enumerate(lines, start=1):
        clipped = _truncate_line(line)
        block = f"{index}. {clipped}"
        if total + len(block) > _MAX_BATCH_INPUT_CHARS:
            block = block[: max(0, _MAX_BATCH_INPUT_CHARS - total)]
        parts.append(block)
        total += len(block)
        if total >= _MAX_BATCH_INPUT_CHARS:
            break
    return "\n".join(parts)


def _parse_summary_array(text: str, *, expected_len: int) -> list[str] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or len(data) != expected_len:
        return None
    return ["" if item is None else str(item).strip() for item in data]


async def _batch_summarize(lines: list[str], *, llm: LLMClient) -> list[str] | None:
    if not lines:
        return []
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_batch_user_content(lines)},
    ]
    try:
        raw = await llm.chat_without_reasoning(messages, max_tokens=1024)
    except Exception as exc:
        logger.warning("worker_content_summarize llm failed: %s", exc)
        return None
    return _parse_summary_array(raw, expected_len=len(lines))


async def summarize_worker_assistant_content(
    worker: list[dict[str, Any]],
    *,
    llm: LLMClient,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Replace verbose assistant planning content (with tool_calls) before persist."""
    del settings  # reserved for future toggles/limits
    out = copy.deepcopy(worker)
    targets: list[tuple[int, str]] = []
    for index, message in enumerate(out):
        if _should_summarize_assistant_content(message):
            targets.append((index, str(message["content"]).strip()))

    if not targets:
        return out

    summaries = await _batch_summarize([text for _, text in targets], llm=llm)
    if summaries is None:
        logger.warning(
            "worker_content_summarize skipped: bad batch response for %s lines",
            len(targets),
        )
        return out

    for (index, _original), summary in zip(targets, summaries, strict=True):
        if summary:
            out[index]["content"] = summary
        else:
            out[index].pop("content", None)

    logger.info("worker_content_summarize applied count=%s", len(targets))
    return out
