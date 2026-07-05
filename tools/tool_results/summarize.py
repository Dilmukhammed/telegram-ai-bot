from __future__ import annotations

import json
import logging

from config import Settings
from llm import LLMClient
from tools.tool_results.families import summarize_system_prompt, tool_family
from tools.tool_results.store import ToolResultStore

logger = logging.getLogger(__name__)

SUMMARY_UNAVAILABLE = "Summary unavailable."
SUMMARIZE_STATUS_OK = "ok"
SUMMARIZE_STATUS_UNAVAILABLE = "unavailable"
SUMMARIZE_STATUS_FAILED = "failed"
SUMMARIZE_STATUS_PENDING = "pending"


def summary_ready_for_collapse(status: str, summary: str | None) -> bool:
    if not summary:
        return False
    return status in {SUMMARIZE_STATUS_OK, SUMMARIZE_STATUS_UNAVAILABLE}


def summary_ok_for_reuse(status: str, summary: str | None) -> bool:
    return status == SUMMARIZE_STATUS_OK and bool(summary and summary.strip())


def apply_summary_unavailable(
    store: ToolResultStore,
    ref: str,
    *,
    summarize_attempts: int,
) -> None:
    store.update_summary(
        ref,
        summary=SUMMARY_UNAVAILABLE,
        summarize_status=SUMMARIZE_STATUS_UNAVAILABLE,
        summarize_attempts=summarize_attempts,
    )


def _truncate_for_summarize(payload: str, limit: int) -> str:
    if len(payload) <= limit:
        return payload
    return payload[: limit - 1] + "…"


def _summary_acceptable(summary: str, *, min_chars: int) -> bool:
    text = summary.strip()
    if len(text) < min_chars:
        return False
    if text.endswith("…"):
        return False
    return True


async def summarize_tool_result(
    llm: LLMClient,
    settings: Settings,
    store: ToolResultStore,
    *,
    ref: str,
    tool_name: str,
    args_json: str | None,
    payload_json: str,
) -> None:
    family = tool_family(tool_name)
    system = summarize_system_prompt(family)
    user_parts = [f"Tool: {tool_name}"]
    if args_json:
        user_parts.append(f"Arguments: {args_json}")
    user_parts.append(
        "Result JSON:\n"
        + _truncate_for_summarize(payload_json, settings.tool_result_summarize_max_input_chars)
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    max_retries = settings.tool_result_summarize_max_retries
    last_error: str | None = None
    for attempt in range(1, max_retries + 1):
        try:
            summary = await llm.chat_without_reasoning(messages)
            cleaned = summary.strip()
            if _summary_acceptable(
                cleaned,
                min_chars=settings.tool_result_summarize_min_chars,
            ):
                store.update_summary(
                    ref,
                    summary=cleaned,
                    summarize_status=SUMMARIZE_STATUS_OK,
                    summarize_attempts=attempt,
                )
                logger.info(
                    "tool_result_summarize ok ref=%s tool=%s attempt=%s chars=%s",
                    ref,
                    tool_name,
                    attempt,
                    len(cleaned),
                )
                return
            last_error = (
                "empty summary"
                if not cleaned
                else f"summary too short ({len(cleaned)}<{settings.tool_result_summarize_min_chars})"
            )
            logger.warning(
                "tool_result_summarize rejected ref=%s tool=%s attempt=%s reason=%s",
                ref,
                tool_name,
                attempt,
                last_error,
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "tool_result_summarize failed ref=%s tool=%s attempt=%s error=%s",
                ref,
                tool_name,
                attempt,
                last_error,
            )

    apply_summary_unavailable(store, ref, summarize_attempts=max_retries)
    logger.warning(
        "tool_result_summarize fallback unavailable ref=%s tool=%s error=%s",
        ref,
        tool_name,
        last_error,
    )
