from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

from openai import APIConnectionError, AsyncOpenAI
from openai.types.chat import ChatCompletion

from config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

RetryCallback = Callable[[int, float], Awaitable[None] | None]


class LLMRequestTimeoutError(TimeoutError):
    """Raised when the model API did not respond within the configured deadlines."""


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
        )

    @property
    def request_timeouts(self) -> tuple[float, ...]:
        return self._settings.llm_request_timeouts

    def _completion_kwargs(self, **extra: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._settings.openai_model,
            **extra,
        }
        if self._settings.reasoning_effort:
            kwargs["reasoning_effort"] = self._settings.reasoning_effort
        return kwargs

    async def _call_with_timeout_retry(
        self,
        operation: str,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        on_retry: RetryCallback | None = None,
    ) -> T:
        timeouts = self.request_timeouts
        last_error: BaseException | None = None
        retriable = (asyncio.TimeoutError, APIConnectionError)

        for attempt, timeout in enumerate(timeouts, start=1):
            try:
                return await asyncio.wait_for(coro_factory(), timeout=timeout)
            except retriable as exc:
                last_error = exc
                if attempt >= len(timeouts):
                    break
                next_timeout = timeouts[attempt]
                logger.warning(
                    "LLM %s failed after %.0fs (attempt %s/%s): %s — retrying with %.0fs",
                    operation,
                    timeout,
                    attempt,
                    len(timeouts),
                    exc,
                    next_timeout,
                )
                if on_retry is not None:
                    maybe = on_retry(attempt, next_timeout)
                    if asyncio.iscoroutine(maybe):
                        await maybe

        timeout_label = ", ".join(f"{value:.0f}s" for value in timeouts)
        raise LLMRequestTimeoutError(
            f"LLM {operation} failed after {len(timeouts)} attempt(s) "
            f"(timeouts: {timeout_label})"
        ) from last_error

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        on_retry: RetryCallback | None = None,
    ) -> str:
        chunks: list[str] = []
        async for token in self.chat_stream(messages, on_retry=on_retry):
            chunks.append(token)
        content = "".join(chunks).strip()
        if not content:
            raise RuntimeError("Empty response from model")
        return content

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        on_retry: RetryCallback | None = None,
    ) -> ChatCompletion:
        return await self._call_with_timeout_retry(
            "chat_with_tools",
            lambda: self._client.chat.completions.create(
                **self._completion_kwargs(
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                ),
            ),
            on_retry=on_retry,
        )

    async def count_prompt_tokens(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        on_retry: RetryCallback | None = None,
    ) -> int:
        """Count input tokens via the model API (prompt_tokens on a max_tokens=1 call)."""
        kwargs = self._completion_kwargs(messages=messages, max_tokens=1)
        if tools is not None:
            kwargs["tools"] = tools

        response = await self._call_with_timeout_retry(
            "count_prompt_tokens",
            lambda: self._client.chat.completions.create(**kwargs),
            on_retry=on_retry,
        )
        usage = response.usage
        if usage is None or usage.prompt_tokens is None:
            raise RuntimeError("Model API returned no prompt token usage")
        return usage.prompt_tokens

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        on_retry: RetryCallback | None = None,
    ) -> AsyncIterator[str]:
        async def _collect() -> list[str]:
            stream = await self._client.chat.completions.create(
                **self._completion_kwargs(
                    messages=messages,
                    stream=True,
                ),
            )
            parts: list[str] = []
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    parts.append(delta)
            return parts

        parts = await self._call_with_timeout_retry(
            "chat_stream",
            _collect,
            on_retry=on_retry,
        )
        for token in parts:
            yield token

    async def chat_without_reasoning(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        on_retry: RetryCallback | None = None,
    ) -> str:
        """Fast utility completion without reasoning_effort (summaries, classifiers)."""

        async def _call() -> str:
            response = await self._client.chat.completions.create(
                model=self._settings.openai_model,
                messages=messages,
                max_tokens=max_tokens,
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("Empty response from model")
            return content

        return await self._call_with_timeout_retry(
            "chat_without_reasoning",
            _call,
            on_retry=on_retry,
        )
