from __future__ import annotations

import json
import warnings
from functools import lru_cache
from typing import Any

DEFAULT_LOCAL_TOKENIZER_MODEL = "gemini-2.5-flash"


@lru_cache(maxsize=1)
def get_local_tokenizer():
    from google.genai.local_tokenizer import LocalTokenizer

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=Warning)
        return LocalTokenizer(model_name=DEFAULT_LOCAL_TOKENIZER_MODEL)


def count_text(text: str) -> int:
    if not text:
        return 0
    return get_local_tokenizer().count_tokens(text).total_tokens


def _message_to_text(message: dict[str, Any]) -> str:
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str) and content:
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if text:
                    parts.append(str(text))
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        parts.append(json.dumps(tool_calls, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(parts)


def count_openai_messages(messages: list[dict[str, Any]]) -> int:
    return sum(count_text(_message_to_text(message)) for message in messages)


def count_openai_tools(tools: list[dict[str, Any]] | None) -> int:
    if not tools:
        return 0
    return count_text(json.dumps(tools, ensure_ascii=False, separators=(",", ":")))


def count_prompt_tokens_local(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> int:
    return count_openai_messages(messages) + count_openai_tools(tools)
