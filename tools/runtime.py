import json
import logging
from typing import Any

from tools.cache import ToolResultCache, cache_key
from tools.coerce import filter_known_arguments, normalize_use_tool_call
from tools.context import RunContext, reset_run_context, set_run_context
from tools.index import HybridToolIndex
from tools.phase4_config import (
    cache_max_ttl_seconds,
    cache_ttl_for_tool,
    max_tool_calls_per_user_hour,
    rate_limit_for_tool,
)
from tools.ratelimit import SlidingWindowRateLimiter
from tools.registry import ToolRegistry
from tools.schema import ToolSpec
from tools.search_enrichment import (
    SearchToolsValidationError,
    build_search_payload,
    normalize_search_mode,
)
from tools.telemetry import ToolCallRecord, ToolCallTimer, ToolTelemetry

logger = logging.getLogger(__name__)


class ToolValidationError(ValueError):
    pass


def _validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> None:
    schema = spec.parameters
    if schema.get("type") != "object":
        raise ToolValidationError("Tool parameters schema must be an object")

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for key in required:
        if key not in arguments:
            raise ToolValidationError(f"Missing required argument: {key}")

    extra = set(arguments) - set(properties)
    if extra:
        logger.debug("Ignoring unknown tool arguments for %s: %s", spec.name, sorted(extra))


class ToolRuntime:
    def __init__(
        self,
        registry: ToolRegistry,
        index: HybridToolIndex,
        *,
        cache: ToolResultCache | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        telemetry: ToolTelemetry | None = None,
    ) -> None:
        self._registry = registry
        self._index = index
        self._cache = cache or ToolResultCache(cache_max_ttl_seconds())
        self._rate_limiter = rate_limiter or SlidingWindowRateLimiter()
        self._telemetry = telemetry or ToolTelemetry()

    @property
    def telemetry(self) -> ToolTelemetry:
        return self._telemetry

    def stats_report(self, recent_limit: int = 5) -> str:
        return self._telemetry.format_report(
            cache_entries=self._cache.size(),
            recent_limit=recent_limit,
        )

    def get_tool_spec(self, name: str) -> ToolSpec | None:
        return self._registry.get(name)

    async def search_tools(
        self,
        query: str,
        top_k: int = 5,
        *,
        tags: list[str] | None = None,
        mode: str = "rank",
    ) -> dict[str, Any]:
        return await build_search_payload(
            index=self._index,
            all_tools=self._registry.all(),
            query=query,
            top_k=top_k,
            tags=tags,
            mode=normalize_search_mode(mode),
        )

    def is_meta_tool_parallel_safe(self, name: str, arguments: dict[str, Any]) -> bool:
        if name == "search_tools":
            return True
        if name != "use_tool":
            return True

        tool_name, _ = normalize_use_tool_call(arguments)
        spec = self._registry.get(tool_name)
        if spec is None:
            return True
        return spec.parallel_safe

    async def use_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        ctx: RunContext | None = None,
    ) -> dict[str, Any]:
        ctx = ctx or RunContext()
        timer = ToolCallTimer()

        spec = self._registry.get(tool_name)
        if spec is None:
            self._record_call(
                ctx=ctx,
                tool_name=tool_name,
                timer=timer,
                ok=False,
                cached=False,
                rate_limited=False,
                error=f"Unknown tool: {tool_name}",
            )
            raise ToolValidationError(
                f"Unknown tool: {tool_name}. "
                "Use search_tools to find the correct tool name."
            )

        rate_decision = self._check_rate_limits(ctx, tool_name, spec)
        if not rate_decision.allowed:
            payload = {
                "tool_name": tool_name,
                "ok": False,
                "error": "rate_limited",
                "retry_after_seconds": rate_decision.retry_after_seconds,
            }
            self._record_call(
                ctx=ctx,
                tool_name=tool_name,
                timer=timer,
                ok=False,
                cached=False,
                rate_limited=True,
                error="rate_limited",
            )
            return payload

        properties = spec.parameters.get("properties", {})
        _validate_arguments(spec, arguments)
        filtered = filter_known_arguments(properties, arguments)

        ttl = cache_ttl_for_tool(tool_name, spec.cache_ttl_seconds)
        key = cache_key(ctx.user_id, tool_name, filtered) if ttl else None
        if key is not None:
            cached = self._cache.get(key)
            if cached is not None:
                self._record_call(
                    ctx=ctx,
                    tool_name=tool_name,
                    timer=timer,
                    ok=True,
                    cached=True,
                    rate_limited=False,
                )
                return {
                    "tool_name": tool_name,
                    "ok": True,
                    "cached": True,
                    "result": cached,
                }

        try:
            token = set_run_context(ctx)
            try:
                result = await spec.handler(filtered)
            finally:
                reset_run_context(token)
        except Exception as exc:
            self._record_call(
                ctx=ctx,
                tool_name=tool_name,
                timer=timer,
                ok=False,
                cached=False,
                rate_limited=False,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        if key is not None and ttl:
            self._cache.set(key, result, ttl)

        self._record_call(
            ctx=ctx,
            tool_name=tool_name,
            timer=timer,
            ok=True,
            cached=False,
            rate_limited=False,
        )
        return {
            "tool_name": tool_name,
            "ok": True,
            "cached": False,
            "result": result,
        }

    async def dispatch_meta_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: RunContext | None = None,
    ) -> str:
        ctx = ctx or RunContext(meta_tool=name)
        timer = ToolCallTimer()
        try:
            if name == "search_tools":
                raw_tags = arguments.get("tags") or []
                tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else None
                try:
                    payload = await self.search_tools(
                        query=str(arguments.get("query", "")),
                        top_k=int(arguments.get("top_k", 5)),
                        tags=tags,
                        mode=str(arguments.get("mode", "rank")),
                    )
                except SearchToolsValidationError as exc:
                    payload = {"ok": False, "error": str(exc)}
            elif name == "use_tool":
                tool_name, tool_arguments = normalize_use_tool_call(arguments)
                payload = await self.use_tool(
                    tool_name=tool_name,
                    arguments=tool_arguments,
                    ctx=RunContext(
                        user_id=ctx.user_id,
                        turn=ctx.turn,
                        meta_tool=name,
                    ),
                )
            else:
                payload = {"ok": False, "error": f"Unknown meta-tool: {name}"}
        except ToolValidationError as exc:
            payload = {"ok": False, "error": str(exc)}
        except Exception as exc:
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        if name == "search_tools":
            self._record_call(
                ctx=ctx,
                tool_name="search_tools",
                timer=timer,
                ok=bool(payload.get("count", 0) >= 0),
                cached=False,
                rate_limited=False,
            )

        return json.dumps(payload, ensure_ascii=False)

    def _check_rate_limits(self, ctx: RunContext, tool_name: str, spec: ToolSpec):
        hourly = self._rate_limiter.check(
            ctx.user_id,
            "use_tool:hourly",
            max_tool_calls_per_user_hour(),
            3600,
        )
        if not hourly.allowed:
            return hourly

        limit = rate_limit_for_tool(tool_name, spec.rate_limit)
        if limit is None:
            return hourly

        max_calls, window_seconds = limit
        return self._rate_limiter.check(ctx.user_id, tool_name, max_calls, window_seconds)

    def _record_call(
        self,
        *,
        ctx: RunContext,
        tool_name: str,
        timer: ToolCallTimer,
        ok: bool,
        cached: bool,
        rate_limited: bool,
        error: str | None = None,
    ) -> None:
        self._telemetry.record(
            ToolCallRecord(
                tool_name=tool_name,
                meta_tool=ctx.meta_tool,
                user_id=ctx.user_id,
                turn=ctx.turn,
                duration_ms=timer.duration_ms,
                ok=ok,
                cached=cached,
                rate_limited=rate_limited,
                error=error,
            )
        )
