"""Shared scaffolding for meta-review LLM passes (trajectory coach, supervisor).

All meta-reviewers follow the same skeleton: build messages → call the model →
parse a JSON decision → fall back to a safe default on failure, with optional
one-shot repair when the JSON came back truncated. This base centralises that
Template Method so each reviewer only supplies its prompt, parser, and fallback.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Generic, TypeVar

from config import Settings
from llm import LLMClient

logger = logging.getLogger(__name__)

D = TypeVar("D")

Messages = list[dict[str, str]]


class MetaReviewer(Generic[D]):
    name = "meta_reviewer"

    def __init__(self, llm: LLMClient, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    async def _complete(
        self,
        messages: Messages,
        *,
        reasoning: bool,
        max_tokens: int | None,
        json_object: bool,
    ) -> str:
        if reasoning:
            return await self._llm.chat(messages)
        kwargs: dict[str, object] = {}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if json_object:
            kwargs["response_format"] = {"type": "json_object"}
        return await self._llm.chat_without_reasoning(messages, **kwargs)  # type: ignore[arg-type]

    async def _review(
        self,
        messages: Messages,
        *,
        parse: Callable[[str], D],
        fallback: Callable[[Exception, str], D],
        reasoning: bool = False,
        max_tokens: int | None = None,
        json_object: bool = True,
        repair: Callable[[Messages], Messages] | None = None,
    ) -> D:
        """Run one review pass with a single optional repair retry on bad JSON."""
        raw = ""
        try:
            raw = await self._complete(
                messages, reasoning=reasoning, max_tokens=max_tokens, json_object=json_object
            )
            return parse(raw)
        except json.JSONDecodeError as exc:
            if repair is not None:
                logger.warning(
                    "%s JSON truncated (%s), retrying compact (raw_len=%s)", self.name, exc, len(raw)
                )
                try:
                    raw = await self._complete(
                        repair(messages),
                        reasoning=reasoning,
                        max_tokens=max_tokens,
                        json_object=json_object,
                    )
                    return parse(raw)
                except Exception as exc2:  # noqa: BLE001 - fall back on any repair failure
                    logger.warning("%s repair failed: %s (raw=%r)", self.name, exc2, raw[:240])
                    return fallback(exc2, raw)
            logger.warning("%s JSON error: %s (raw=%r)", self.name, exc, raw[:240])
            return fallback(exc, raw)
        except Exception as exc:  # noqa: BLE001 - reviewers must never crash the run
            logger.warning("%s failed: %s (raw=%r)", self.name, exc, raw[:240])
            return fallback(exc, raw)
