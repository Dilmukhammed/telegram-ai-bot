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

# LLMClient profile names for thorough system (see config THOROUGH_* env vars).
THOROUGH_LLM_PROFILES = frozenset(
    {
        "thorough_planner_unit",
        "thorough_planner_surface",
        "thorough_planner_hot",
        "thorough_merger",
    }
)

_THOROUGH_PROFILE_ATTRS: dict[str, tuple[str, str, str]] = {
    "thorough_planner_unit": (
        "thorough_planner_unit_model",
        "thorough_planner_unit_base_url",
        "thorough_planner_unit_api_key",
    ),
    "thorough_planner_surface": (
        "thorough_planner_surface_model",
        "thorough_planner_surface_base_url",
        "thorough_planner_surface_api_key",
    ),
    "thorough_planner_hot": (
        "thorough_planner_hot_model",
        "thorough_planner_hot_base_url",
        "thorough_planner_hot_api_key",
    ),
    "thorough_merger": (
        "thorough_merger_model",
        "thorough_merger_base_url",
        "thorough_merger_api_key",
    ),
}

RetryCallback = Callable[[int, float], Awaitable[None] | None]


class LLMRequestTimeoutError(TimeoutError):
    """Raised when the model API did not respond within the configured deadlines."""


class LLMClient:
    def __init__(self, settings: Settings, *, profile: str = "agent") -> None:
        self._settings = settings
        if profile in {"summarize", "coach", "extraction"}:
            self._model = settings.summarize_model
            base_url = settings.summarize_base_url
            api_key = settings.summarize_api_key
            self._reasoning_effort: str | None = (
                settings.reasoning_effort if profile == "extraction" else None
            )
        elif profile == "checker":
            self._model = settings.checker_model
            base_url = settings.checker_base_url
            api_key = settings.checker_api_key
            self._reasoning_effort = None
        elif profile in _THOROUGH_PROFILE_ATTRS:
            model_attr, base_attr, key_attr = _THOROUGH_PROFILE_ATTRS[profile]
            self._model = getattr(settings, model_attr)
            base_url = getattr(settings, base_attr)
            api_key = getattr(settings, key_attr)
            self._reasoning_effort = None
        elif profile == "agent":
            self._model = settings.openai_model
            base_url = settings.openai_base_url
            api_key = settings.openai_api_key
            self._reasoning_effort = settings.reasoning_effort
        else:
            raise ValueError(f"Unknown LLM profile: {profile!r}")
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )

    @property
    def request_timeouts(self) -> tuple[float, ...]:
        return self._settings.llm_request_timeouts

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def reasoning_effort(self) -> str | None:
        return self._reasoning_effort

    def _completion_kwargs(self, **extra: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            **extra,
        }
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort
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
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        on_retry: RetryCallback | None = None,
    ) -> str:
        """Fast utility completion without reasoning_effort (summaries, classifiers)."""

        async def _call() -> str:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if response_format is not None:
                kwargs["response_format"] = response_format
            if temperature is not None:
                kwargs["temperature"] = temperature
            response = await self._client.chat.completions.create(**kwargs)
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("Empty response from model")
            return content

        return await self._call_with_timeout_retry(
            "chat_without_reasoning",
            _call,
            on_retry=on_retry,
        )

    async def chat_structured(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        on_retry: RetryCallback | None = None,
    ) -> str:
        """Structured completion that preserves this profile's reasoning settings."""

        async def _call() -> str:
            kwargs = self._completion_kwargs(
                messages=messages,
                max_tokens=max_tokens,
            )
            if response_format is not None:
                kwargs["response_format"] = response_format
            # Most reasoning endpoints reject sampling controls. Determinism comes
            # from the structured schema and semantic validator for these calls.
            if temperature is not None and self._reasoning_effort is None:
                kwargs["temperature"] = temperature
            response = await self._client.chat.completions.create(**kwargs)
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("Empty response from model")
            return content

        return await self._call_with_timeout_retry(
            "chat_structured",
            _call,
            on_retry=on_retry,
        )
