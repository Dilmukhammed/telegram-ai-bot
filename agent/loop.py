import asyncio
import copy
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from agent.coach_dialog import (
    bind_coach_reply_dispatch,
    clear_coach_reply_dispatch,
    is_billable_meta_tool_call,
    is_coach_reply_tool,
    reset_coach_dialog,
)
from agent.context_collapse import SearchContextCollapser, collapse_duplicate_use_tool_calls
from agent.context_stats import format_context_stats
from agent.prompts import AGENT_SYSTEM_PROMPT
from agent.run_result import AgentRunResult
from agent.run_trace import RunTraceCollector, ToolStep
from agent.supervisor import (
    AgentSupervisor,
    fallback_stop_decision,
    format_supervisor_coaching,
    format_supervisor_retry,
    format_supervisor_stop,
)
from agent.supervisor_triggers import detect_soft_trigger
from agent.checker_telemetry import CheckerTelemetry
from agent.supervisor_telemetry import SupervisorTelemetry
from agent.coach_progress import format_coach_coaching_with_trace
from agent.trajectory_coach import (
    TrajectoryCoach,
    format_coach_status,
    should_run_coach_review,
)
from agent.tool_checker import ToolChecker, checker_skip_reason
from agent.trace_store import TraceStore
from agent.runtime_context import build_runtime_context_prompt
from agent.calendar_links import CalendarLinkCollector, finalize_calendar_text
from agent.drive_links import DriveLinkCollector, finalize_drive_text
from agent.gmail_links import GmailLinkCollector, finalize_gmail_text
from agent.maps_links import MapsLinkCollector, finalize_maps_text
from agent.tasks_links import TasksLinkCollector, finalize_tasks_text
from agent.tool_links_appendix import append_tool_links_appendix
from agent.tool_search_hints import maybe_append_tool_hints
from bot.vision import build_user_message_content
from skills.auto_load import (
    append_pending_skills_to_messages,
    apply_pending_skill_unloads,
    auto_load_status_message,
    maybe_auto_load_after_tool,
    maybe_auto_load_for_skill,
    prepare_skills_for_run,
    reset_auto_load_run_state,
)
from skills.collapse import SkillContextCollapser, sanitize_expanded_skills_for_context
from skills.pending import reset_skill_run_state
from skills.session import build_skill_run_snapshot
from skills.usage_tracker import record_tagged_search, record_tool_use
from tools.workspace.vision_pending import take_pending_vision
from agent.sources import SourceCollector, append_sources
from agent.transit_guard import skipped_web_search_result, transit_route_satisfied
from agent.history_persist import extract_worker_history_for_persist, strip_reasoning_content_inplace
from agent.worker_content_summarize import summarize_worker_assistant_content
from config import Settings
from llm import LLMClient
from tools.coerce import normalize_use_tool_call
from tools.context import RunContext
from tools.meta_tools import META_TOOL_DEFINITIONS
from tools.outbound_files import (
    OutboundQueue,
    get_outbound_queue,
    reset_outbound_queue,
    set_outbound_queue,
)
from tools.run_files import RunFileStore, reset_run_file_store, set_run_file_store
from tools.runtime import ToolRuntime
from tools.tool_results.collapser import ToolResultCollapser, args_json_for_use_tool

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], Awaitable[None]]


def _looks_like_serialized_tool_call(content: str) -> bool:
    lowered = content.casefold()
    return (
        "<tool_call>" in lowered
        or ("<arg_key>" in lowered and "</arg_value>" in lowered)
    )


def _finalize_reply(
    content: str,
    sources: SourceCollector,
    maps_links: MapsLinkCollector,
    gmail_links: GmailLinkCollector,
    drive_links: DriveLinkCollector,
    calendar_links: CalendarLinkCollector,
    tasks_links: TasksLinkCollector,
) -> tuple[str, tuple[tuple[str, str], ...], tuple[tuple[str, str], ...], tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    maps_links.ingest_from_text(content)
    gmail_links.ingest_from_text(content)
    drive_links.ingest_from_text(content)
    calendar_links.ingest_from_text(content)
    tasks_links.ingest_from_text(content)

    reply = append_sources(content, sources)
    reply = finalize_maps_text(reply, maps_links)
    reply = finalize_gmail_text(reply, gmail_links)
    reply = finalize_drive_text(reply, drive_links)
    reply = finalize_calendar_text(reply, calendar_links)
    reply = finalize_tasks_text(reply, tasks_links)
    reply = append_tool_links_appendix(
        reply,
        maps_links=maps_links,
        gmail_links=gmail_links,
        drive_links=drive_links,
        calendar_links=calendar_links,
        tasks_links=tasks_links,
    )
    return (
        reply,
        gmail_links.buttons(),
        drive_links.buttons(),
        calendar_links.buttons(),
        tasks_links.buttons(),
    )


def _complete_run(
    messages: list[dict[str, Any]],
    *,
    history_len: int,
    content: str,
    sources: SourceCollector,
    maps_links: MapsLinkCollector,
    gmail_links: GmailLinkCollector,
    drive_links: DriveLinkCollector,
    calendar_links: CalendarLinkCollector,
    tasks_links: TasksLinkCollector,
    skill_collapser: SkillContextCollapser,
) -> AgentRunResult:
    reply, gmail_buttons, drive_buttons, calendar_buttons, tasks_buttons = _finalize_reply(
        content, sources, maps_links, gmail_links, drive_links, calendar_links, tasks_links
    )
    worker_history = extract_worker_history_for_persist(
        messages,
        worker_start_index=1 + history_len + 1,
        display_reply=reply,
    )
    outbound = get_outbound_queue()
    outbound_files = outbound.snapshot() if outbound is not None else ()
    return AgentRunResult(
        reply=reply,
        worker_history=worker_history,
        skill_snapshot=build_skill_run_snapshot(skill_collapser),
        maps_buttons=maps_links.buttons(),
        gmail_buttons=gmail_buttons,
        drive_buttons=drive_buttons,
        calendar_buttons=calendar_buttons,
        tasks_buttons=tasks_buttons,
        outbound_files=outbound_files,
    )


async def _finish_run(
    messages: list[dict[str, Any]],
    *,
    result_collapser: ToolResultCollapser | None,
    history_len: int,
    content: str,
    sources: SourceCollector,
    maps_links: MapsLinkCollector,
    gmail_links: GmailLinkCollector,
    drive_links: DriveLinkCollector,
    calendar_links: CalendarLinkCollector,
    tasks_links: TasksLinkCollector,
    skill_collapser: SkillContextCollapser,
    summarize_llm: LLMClient,
    settings: Settings,
) -> AgentRunResult:
    if result_collapser is not None:
        collapsed = await result_collapser.collapse_all(messages)
        if collapsed:
            logger.info("tool_result_archive run_end collapsed=%s", collapsed)
    result = _complete_run(
        messages,
        history_len=history_len,
        content=content,
        sources=sources,
        maps_links=maps_links,
        gmail_links=gmail_links,
        drive_links=drive_links,
        calendar_links=calendar_links,
        tasks_links=tasks_links,
        skill_collapser=skill_collapser,
    )
    try:
        worker_history = await summarize_worker_assistant_content(
            result.worker_history,
            llm=summarize_llm,
            settings=settings,
        )
        return replace(result, worker_history=worker_history)
    except Exception:
        logger.warning("worker_content_summarize failed; keeping original content", exc_info=True)
        return result


def _parse_tool_arguments(raw_args: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _checker_args_fingerprint(arguments_normalized: dict[str, Any]) -> str:
    try:
        return json.dumps(arguments_normalized, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(sorted(arguments_normalized.items())) if arguments_normalized else ""


def _count_billable_tool_calls(tool_calls: list[Any]) -> int:
    count = 0
    for tool_call in tool_calls:
        meta_tool = tool_call.function.name
        target_tool: str | None = None
        if meta_tool == "use_tool":
            args = _parse_tool_arguments(tool_call.function.arguments)
            target_tool, _ = normalize_use_tool_call(args)
        if is_billable_meta_tool_call(meta_tool, target_tool):
            count += 1
    return count


def _status_for_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name == "search_tools":
        query = str(arguments.get("query", "")).strip()
        if query:
            return f"Ищу инструмент: {query}"
        return "Ищу подходящий инструмент…"
    if tool_name != "use_tool":
        return "Выполняю инструмент…"

    target, tool_args = normalize_use_tool_call(arguments)
    if target == "exa.web_search":
        query = str(tool_args.get("query", "")).strip()
        if query:
            return f"Ищу в интернете: {query}"
        return "Ищу в интернете…"
    if target == "exa.web_fetch":
        urls = tool_args.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        if urls:
            return f"Читаю страницу: {urls[0]}"
        return "Читаю страницу…"
    if target == "echo.test":
        return "Тестирую инструмент echo…"
    if target.startswith("google.calendar."):
        return "Работаю с Google Calendar…"
    if target.startswith("google.gmail."):
        return "Работаю с Gmail…"
    if target.startswith("google.drive."):
        return "Работаю с Google Drive…"
    if target.startswith("google.sheets."):
        return "Работаю с Google Sheets…"
    if target.startswith("google.tasks."):
        return "Работаю с Google Tasks…"
    if target.startswith("google.maps."):
        return "Работаю с Google Maps…"
    if target.startswith("google.auth."):
        return "Проверяю Google OAuth…"
    if target == "skills.load":
        skill_id = str(tool_args.get("skill_id", "")).strip()
        if skill_id:
            return f"Загружаю skill: {skill_id}…"
        return "Загружаю skill…"
    if target == "skills.unload":
        skill_id = str(tool_args.get("skill_id", "")).strip()
        if skill_id:
            return f"Сворачиваю skill: {skill_id}…"
        return "Сворачиваю skill…"
    if target == "skills.list":
        return "Список skills…"
    if target == "tool_results.get":
        return "Загружаю полный результат инструмента…"
    if target == "coach.reply":
        return "Уточняю статус для коуча…"
    return f"Запускаю {target}…"


class Agent:
    def __init__(self, settings: Settings, runtime: ToolRuntime) -> None:
        self._settings = settings
        self._llm = LLMClient(settings)
        self._summarize_llm = LLMClient(settings, profile="summarize")
        self._coach_llm = LLMClient(settings, profile="coach")
        self._checker_llm = LLMClient(settings, profile="checker")
        self._runtime = runtime
        self._max_tool_turns = settings.agent_max_tool_turns
        self._supervisor = (
            AgentSupervisor(self._llm, settings) if settings.agent_supervisor_enabled else None
        )
        self._trajectory_coach = (
            TrajectoryCoach(self._coach_llm, settings) if settings.agent_coach_enabled else None
        )
        self._tool_checker = (
            ToolChecker(self._checker_llm, settings) if settings.agent_checker_enabled else None
        )
        if settings.agent_checker_enabled:
            allowlist = settings.checker_tools_allowlist.strip() or "*"
            logger.info("Tool checker enabled allowlist=%s", allowlist)
        self._trace_store = TraceStore(settings)
        self._supervisor_telemetry = SupervisorTelemetry()
        self._checker_telemetry = CheckerTelemetry()

    def stats_report(self, runtime: ToolRuntime) -> str:
        return (
            runtime.stats_report()
            + "\n\n"
            + self._supervisor_telemetry.format_report()
            + "\n\n"
            + self._checker_telemetry.format_report()
        )

    async def context_stats_report(
        self,
        history: list[dict[str, Any]] | None,
        *,
        user_id: int | None = None,
    ) -> str:
        from local_tokenizer import count_prompt_tokens_local
        from tools.meta_tools import META_TOOL_DEFINITIONS

        messages = self._build_messages("", history)
        prompt_tokens = count_prompt_tokens_local(
            messages,
            tools=META_TOOL_DEFINITIONS,
        )
        return format_context_stats(
            self._settings,
            prompt_tokens,
            user_id=user_id,
            history=history,
        ) + (
            "\n\n" + self._checker_telemetry.format_report()
            if self._settings.agent_checker_enabled
            else ""
        )

    def trace_last_report(self, user_id: int) -> str:
        return self._trace_store.format_for_telegram(user_id)

    def coach_last_report(self, user_id: int) -> str:
        return self._trace_store.format_coach_last_for_telegram(user_id)

    def checker_last_report(self, user_id: int) -> str:
        return self._trace_store.format_checker_last_for_telegram(user_id)

    def last_trace(self, user_id: int):
        return self._trace_store.get(user_id)

    def _build_messages(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        *,
        image_data_urls: list[str] | None = None,
    ) -> list[dict]:
        system = AGENT_SYSTEM_PROMPT
        if self._settings.system_prompt.strip() not in system:
            system = f"{system}\n\n{self._settings.system_prompt}"
        system = f"{system}\n\n{build_runtime_context_prompt()}"

        messages: list[dict] = [{"role": "system", "content": system}]
        if history:
            history_for_run = copy.deepcopy(sanitize_expanded_skills_for_context(history))
            strip_reasoning_content_inplace(history_for_run)
            collapse_duplicate_use_tool_calls(history_for_run)
            messages.extend(history_for_run)
        messages.append(
            {
                "role": "user",
                "content": build_user_message_content(
                    user_message,
                    image_data_urls or [],
                ),
            }
        )
        return messages

    async def _maybe_run_tool_checker(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        trace: RunTraceCollector,
        current_step: ToolStep | None,
        user_message: str,
        user_id: int | None,
        checker_tasks: list[asyncio.Task[None]],
    ) -> None:
        if self._tool_checker is None or tool_name != "use_tool":
            return
        target, _inner = normalize_use_tool_call(arguments)
        if not target or is_coach_reply_tool(target):
            return
        spec = self._runtime.get_tool_spec(target)
        if spec is None:
            return
        if current_step is None:
            return
        skip_reason = checker_skip_reason(spec=spec, step=current_step, settings=self._settings)
        if skip_reason is not None:
            if skip_reason not in {"disabled", "not_use_tool", "no_questions", "tool_disabled"}:
                self._checker_telemetry.record_skip(tool_name=target, reason=skip_reason)
            return
        # Skip identical (tool, args) calls already checked this run — retries and
        # duplicates produce the same verdict, so one review is enough.
        dedup_key = f"{target}|{_checker_args_fingerprint(current_step.arguments_normalized)}"
        if not trace.register_checker_dedup(dedup_key):
            self._checker_telemetry.record_skip(tool_name=target, reason="duplicate")
            return
        prior_steps = trace.steps_before(current_step)
        snapshot_steps = (*prior_steps, current_step)
        snapshot_checker_reviews = trace.checker_reviews_snapshot()

        async def _run() -> None:
            try:
                review = await self._tool_checker.review_step(
                    spec=spec,
                    current_step=current_step,
                    prior_steps=prior_steps,
                    user_message=user_message,
                    user_id=user_id,
                    runtime=self._runtime,
                    all_steps=snapshot_steps,
                    prior_checker_reviews=snapshot_checker_reviews,
                    worker_turns_used=trace.worker_turns_used,
                    worker_turns_budget=trace.worker_turns_budget,
                )
                trace.record_checker_review(review)
                self._checker_telemetry.record_review(
                    user_id=user_id,
                    tool_name=review.tool_name,
                    overall=review.overall,
                    rule_based_only=review.rule_based_only,
                )
            except Exception:
                logger.exception("tool_checker background review failed tool=%s", target)
                self._checker_telemetry.record_error(tool_name=target)

        checker_tasks.append(asyncio.create_task(_run(), name=f"tool_checker:{target}"))
        logger.info("tool_checker spawned tool=%s turn=%s", target, current_step.turn)

    async def _dispatch_tool_call(
        self,
        tool_call: Any,
        turn: int,
        user_id: int | None,
        on_status: StatusCallback | None,
        trace: RunTraceCollector,
        messages: list[dict[str, Any]],
        *,
        billable_tool_calls_before: int = 0,
        user_message: str = "",
        checker_tasks: list[asyncio.Task[None]] | None = None,
    ) -> tuple[str, str]:
        checker_tasks = checker_tasks if checker_tasks is not None else []
        tool_name = tool_call.function.name
        arguments = _parse_tool_arguments(tool_call.function.arguments)

        if on_status:
            await on_status(_status_for_tool(tool_name, arguments))

        trace.on_tool_dispatch(
            turn=turn,
            meta_tool=tool_name,
            arguments_raw=arguments,
            call_id=tool_call.id,
        )

        bind_coach_reply_dispatch(
            tool_calls_at=billable_tool_calls_before,
            tool_step_index=len(trace.steps),
        )

        logger.info("Tool call turn=%s name=%s args=%s", turn + 1, tool_name, arguments)

        try:
            if tool_name == "use_tool":
                target, tool_args = normalize_use_tool_call(arguments)
                if target == "exa.web_search" and transit_route_satisfied(messages):
                    query = str(tool_args.get("query") or "").strip()
                    logger.info(
                        "Skipping exa.web_search after transit route satisfied query=%s",
                        query,
                    )
                    result = skipped_web_search_result(query=query)
                    trace.on_tool_result(
                        turn=turn,
                        call_id=tool_call.id,
                        result_json=result,
                        duration_ms=0,
                    )
                    return tool_call.id, result

            ctx = RunContext(user_id=user_id, turn=turn + 1, meta_tool=tool_name)
            started = time.perf_counter()
            result = await self._runtime.dispatch_meta_tool(tool_name, arguments, ctx=ctx)
            current_step = trace.on_tool_result(
                turn=turn,
                call_id=tool_call.id,
                result_json=result,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            await self._maybe_run_tool_checker(
                tool_name=tool_name,
                arguments=arguments,
                trace=trace,
                current_step=current_step,
                user_message=user_message,
                user_id=user_id,
                checker_tasks=checker_tasks,
            )
            return tool_call.id, result
        finally:
            clear_coach_reply_dispatch()

    async def _execute_tool_turn(
        self,
        *,
        turn: int,
        messages: list[dict],
        tool_calls: list[Any],
        user_id: int | None,
        on_status: StatusCallback | None,
        trace: RunTraceCollector,
        collapser: SearchContextCollapser,
        skill_collapser: SkillContextCollapser,
        result_collapser: ToolResultCollapser | None,
        sources: SourceCollector,
        maps_links: MapsLinkCollector,
        gmail_links: GmailLinkCollector,
        drive_links: DriveLinkCollector,
        calendar_links: CalendarLinkCollector,
        tasks_links: TasksLinkCollector,
        hinted_tool_groups: set[str],
        hinted_skill_groups: set[str],
        billable_tool_calls_before: int = 0,
        user_message: str = "",
        checker_tasks: list[asyncio.Task[None]] | None = None,
    ) -> None:
        checker_tasks = checker_tasks if checker_tasks is not None else []
        parallel_safe = all(
            self._runtime.is_meta_tool_parallel_safe(
                tool_call.function.name,
                _parse_tool_arguments(tool_call.function.arguments),
            )
            for tool_call in tool_calls
        )

        if parallel_safe and len(tool_calls) > 1:
            pairs = await asyncio.gather(
                *[
                    self._dispatch_tool_call(
                        tool_call, turn, user_id, on_status, trace, messages,
                        billable_tool_calls_before=billable_tool_calls_before,
                        user_message=user_message,
                        checker_tasks=checker_tasks,
                    )
                    for tool_call in tool_calls
                ]
            )
        else:
            pairs = []
            for tool_call in tool_calls:
                pairs.append(
                    await self._dispatch_tool_call(
                        tool_call, turn, user_id, on_status, trace, messages,
                        billable_tool_calls_before=billable_tool_calls_before,
                        user_message=user_message,
                        checker_tasks=checker_tasks,
                    )
                )

        tool_results: list[str] = []
        for tool_call, (tool_call_id, result) in zip(tool_calls, pairs, strict=True):
            try:
                payload = json.loads(result)
            except json.JSONDecodeError:
                payload = {}
            if payload.get("ok"):
                auto_loaded_skill: str | None = None
                if tool_call.function.name == "search_tools":
                    raw_args = _parse_tool_arguments(tool_call.function.arguments)
                    tags = raw_args.get("tags")
                    if isinstance(tags, list) and tags:
                        skill_id = record_tagged_search(tags)
                        auto_loaded_skill = maybe_auto_load_for_skill(skill_id)
                else:
                    tool_name = str(payload.get("tool_name") or "")
                    if tool_name and not is_coach_reply_tool(tool_name):
                        record_tool_use(tool_name)
                        auto_loaded_skill = maybe_auto_load_after_tool(tool_name)
                if auto_loaded_skill and on_status:
                    await on_status(auto_load_status_message(auto_loaded_skill))
            result = maybe_append_tool_hints(
                result,
                hinted_search_groups=hinted_tool_groups,
                hinted_skill_groups=hinted_skill_groups,
            )
            sources.ingest_tool_result_json(result)
            maps_links.ingest_tool_result_json(result)
            gmail_links.ingest_tool_result_json(result)
            drive_links.ingest_tool_result_json(result)
            calendar_links.ingest_tool_result_json(result)
            tasks_links.ingest_tool_result_json(result)
            tool_results.append(result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result,
                }
            )
            if (
                result_collapser is not None
                and tool_call.function.name == "use_tool"
            ):
                raw_args = _parse_tool_arguments(tool_call.function.arguments)
                target, _inner = normalize_use_tool_call(raw_args)
                if not is_coach_reply_tool(target):
                    result_collapser.register_tool_message(
                        tool_call_id=tool_call_id,
                        turn=turn,
                        content=result,
                        tool_name=target,
                        args_json=args_json_for_use_tool(raw_args),
                    )
            for image_path, data_url in take_pending_vision():
                messages.append(
                    {
                        "role": "user",
                        "content": build_user_message_content(
                            f"[workspace image: {image_path}]",
                            [data_url],
                        ),
                    }
                )

        apply_pending_skill_unloads(messages, skill_collapser)
        append_pending_skills_to_messages(
            messages,
            skill_collapser,
            turn_index=turn,
        )
        skill_collapser.record_tool_uses_from_results(tool_results, turn)

        collapser.on_tool_turn(messages, tool_calls, tool_results)
        collapse_duplicate_use_tool_calls(messages)
        if result_collapser is not None:
            stale = await result_collapser.collapse_stale(messages, turn + 1)
            if stale:
                logger.info("tool_result_archive stale collapsed=%s turn=%s", stale, turn + 1)

    async def _finalize_with_instruction(self, messages: list[dict], instruction: str) -> str:
        return await self._llm.chat([*messages, {"role": "user", "content": instruction}])

    async def _invoke_supervisor(
        self,
        *,
        trigger: str,
        trigger_detail: str,
        messages: list[dict],
        trace: RunTraceCollector,
        sources: SourceCollector,
        maps_links: MapsLinkCollector,
        gmail_links: GmailLinkCollector,
        drive_links: DriveLinkCollector,
        calendar_links: CalendarLinkCollector,
        tasks_links: TasksLinkCollector,
        on_status: StatusCallback | None,
        supervisor_cycles_left: int,
        retries_left: int,
        history_len: int,
        skill_collapser: SkillContextCollapser,
        result_collapser: ToolResultCollapser | None,
        checker_tasks: list[asyncio.Task[None]] | None = None,
    ) -> tuple[AgentRunResult | None, int, int, int]:
        """Returns run result (if done), cycles_left, retries_left, bonus_turns to add."""
        if self._supervisor is None or supervisor_cycles_left <= 0:
            if on_status:
                await on_status("Формирую ответ…")
            trace.finish("supervisor_stop")
            content = await self._finalize_with_instruction(
                messages,
                format_supervisor_stop(
                    fallback_stop_decision(reason="supervisor disabled or cycles exhausted")
                ),
            )
            return (
                await _finish_run(
                    messages,
                    result_collapser=result_collapser,
                    history_len=history_len,
                    content=content,
                    sources=sources,
                    maps_links=maps_links,
                    gmail_links=gmail_links,
                    drive_links=drive_links,
                    calendar_links=calendar_links,
                    tasks_links=tasks_links,
                    skill_collapser=skill_collapser,
                    summarize_llm=self._summarize_llm,
                    settings=self._settings,
                ),
                supervisor_cycles_left,
                retries_left,
                0,
            )

        if on_status:
            await on_status("Проверяю шаги агента…")

        # Flush pending checker reviews so the supervisor sees fresh verdicts in its cycle log.
        if checker_tasks:
            await asyncio.gather(*checker_tasks, return_exceptions=True)
            checker_tasks.clear()

        decision = await self._supervisor.review(
            trace.build(),
            trigger=trigger,
            trigger_detail=trigger_detail,
        )
        supervisor_cycles_left -= 1
        self._supervisor_telemetry.record(
            user_id=trace.user_id,
            trigger=trigger,
            decision=decision.decision,
            bonus_turns=decision.bonus_turns,
        )

        if decision.decision == "CONTINUE":
            bonus_turns = decision.bonus_turns or self._settings.agent_supervisor_bonus_turns
            if on_status:
                await on_status("Продолжаю выполнение…")
            messages.append(
                {"role": "user", "content": format_supervisor_coaching(decision, bonus_turns)}
            )
            trace.extend_turn_budget(bonus_turns)
            logger.info(
                "supervisor_continue trigger=%s bonus_turns=%s cycles_left=%s",
                trigger,
                bonus_turns,
                supervisor_cycles_left,
            )
            return None, supervisor_cycles_left, retries_left, bonus_turns

        if decision.decision == "STOP_RETRY" and retries_left > 0:
            bonus_turns = decision.bonus_turns or self._settings.agent_supervisor_bonus_turns
            retries_left -= 1
            if on_status:
                await on_status("Продолжаю с новым планом…")
            messages.append(
                {"role": "user", "content": format_supervisor_retry(decision, bonus_turns)}
            )
            trace.extend_turn_budget(bonus_turns)
            logger.info(
                "supervisor_retry trigger=%s bonus_turns=%s retries_left=%s",
                trigger,
                bonus_turns,
                retries_left,
            )
            return None, supervisor_cycles_left, retries_left, bonus_turns

        if on_status:
            await on_status("Формирую ответ…")
        trace.finish("supervisor_stop")
        content = await self._finalize_with_instruction(
            messages,
            format_supervisor_stop(decision),
        )
        return (
            await _finish_run(
                messages,
                result_collapser=result_collapser,
                history_len=history_len,
                content=content,
                sources=sources,
                maps_links=maps_links,
                gmail_links=gmail_links,
                drive_links=drive_links,
                calendar_links=calendar_links,
                tasks_links=tasks_links,
                skill_collapser=skill_collapser,
                summarize_llm=self._summarize_llm,
                settings=self._settings,
            ),
            supervisor_cycles_left,
            retries_left,
            0,
        )

    async def run(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
        on_status: StatusCallback | None = None,
        user_id: int | None = None,
        *,
        image_data_urls: list[str] | None = None,
    ) -> AgentRunResult:
        history_len = len(history or [])
        messages = self._build_messages(
            user_message,
            history,
            image_data_urls=image_data_urls,
        )

        sources = SourceCollector()
        maps_links = MapsLinkCollector()
        gmail_links = GmailLinkCollector()
        drive_links = DriveLinkCollector()
        calendar_links = CalendarLinkCollector()
        tasks_links = TasksLinkCollector()
        hinted_tool_groups: set[str] = set()
        hinted_skill_groups: set[str] = set()
        reset_skill_run_state()
        reset_auto_load_run_state()
        reset_coach_dialog()
        prepare_skills_for_run(history)
        skill_collapser = SkillContextCollapser()
        skill_collapser.sync_from_messages(messages)
        append_pending_skills_to_messages(messages, skill_collapser, turn_index=0)
        trace = RunTraceCollector(
            user_id=user_id,
            user_message=user_message,
            worker_turns_budget=self._max_tool_turns,
            debug_trace=self._settings.agent_supervisor_debug_trace,
        )
        collapser = SearchContextCollapser(on_search_collapsed=trace.mark_last_search_collapsed)

        turn_limit = self._max_tool_turns
        turn_index = 0
        supervisor_cycles_left = (
            self._settings.agent_supervisor_max_cycles if self._supervisor is not None else 0
        )
        retries_left = (
            self._settings.agent_supervisor_max_retries if self._supervisor is not None else 0
        )
        serialized_tool_call_retries = 0
        last_soft_trigger_turn = -1
        tool_calls_completed = 0
        last_meta_review_at_tool_count = 0

        run_id = uuid.uuid4().hex[:12]
        result_collapser = ToolResultCollapser(
            settings=self._settings,
            llm=self._summarize_llm,
            user_id=user_id,
            run_id=run_id,
        )
        file_store = RunFileStore(run_id=run_id, user_id=user_id)
        outbound_queue = OutboundQueue()
        file_store_token = set_run_file_store(file_store)
        outbound_token = set_outbound_queue(outbound_queue)
        checker_tasks: list[asyncio.Task[None]] = []

        try:
            while True:
                while turn_index < turn_limit:
                    trace.begin_worker_turn(turn_index)

                    response = await self._llm.chat_with_tools(
                        messages=messages,
                        tools=META_TOOL_DEFINITIONS,
                    )
                    message = response.choices[0].message
                    tool_calls = message.tool_calls or []

                    if not tool_calls:
                        collapser.collapse_if_pending(messages)
                        content = (message.content or "").strip()
                        if (
                            content
                            and _looks_like_serialized_tool_call(content)
                            and serialized_tool_call_retries < 1
                        ):
                            serialized_tool_call_retries += 1
                            logger.warning(
                                "Model serialized a tool call as text at turn=%s; retrying",
                                turn_index,
                            )
                            messages.append({"role": "assistant", "content": content})
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "Your previous response emitted tool-call markup as plain text. "
                                        "Do not print tool markup. Call the required tool now using the "
                                        "native use_tool function, or answer in plain language if no tool "
                                        "is needed."
                                    ),
                                }
                            )
                            turn_index += 1
                            continue
                        if not content:
                            logger.warning(
                                "Model returned empty final response at turn=%s; requesting summary",
                                turn_index,
                            )
                            if on_status:
                                await on_status("Формирую ответ…")
                            content = (
                                await self._finalize_with_instruction(
                                    messages,
                                    "Reply to the user now in plain language using the tool results above.",
                                )
                            ).strip()
                        if not content:
                            trace.finish("error")
                            raise RuntimeError("Model returned empty response")
                        trace.finish("completed")
                        return await _finish_run(
                            messages,
                            result_collapser=result_collapser,
                            history_len=history_len,
                            content=content,
                            sources=sources,
                            maps_links=maps_links,
                            gmail_links=gmail_links,
                            drive_links=drive_links,
                            calendar_links=calendar_links,
                            tasks_links=tasks_links,
                            skill_collapser=skill_collapser,
                            summarize_llm=self._summarize_llm,
                            settings=self._settings,
                        )

                    assistant_message = message.model_dump(exclude_none=True)
                    assistant_message.pop("reasoning_content", None)
                    messages.append(assistant_message)
                    if result_collapser is not None:
                        result_collapser.register_assistant_tool_calls(
                            assistant_message,
                            turn=turn_index,
                        )
                    await self._execute_tool_turn(
                        turn=turn_index,
                        messages=messages,
                        tool_calls=tool_calls,
                        user_id=user_id,
                        on_status=on_status,
                        trace=trace,
                        collapser=collapser,
                        skill_collapser=skill_collapser,
                        result_collapser=result_collapser,
                        sources=sources,
                        maps_links=maps_links,
                        gmail_links=gmail_links,
                        drive_links=drive_links,
                        calendar_links=calendar_links,
                        tasks_links=tasks_links,
                        hinted_tool_groups=hinted_tool_groups,
                        hinted_skill_groups=hinted_skill_groups,
                        billable_tool_calls_before=tool_calls_completed,
                        user_message=user_message,
                        checker_tasks=checker_tasks,
                    )
                    tool_calls_completed += _count_billable_tool_calls(tool_calls)
                    turn_index += 1

                    run_periodic_meta_review = should_run_coach_review(
                        tool_calls_completed=tool_calls_completed,
                        last_coach_at_tool_count=last_meta_review_at_tool_count,
                        every_n=self._settings.coach_every_n_tool_calls,
                    )
                    if run_periodic_meta_review and self._trajectory_coach is not None:
                        # Flush pending per-call checker reviews so the coach — the single
                        # trajectory reviewer — sees the latest verification verdicts.
                        if checker_tasks:
                            await asyncio.gather(*checker_tasks, return_exceptions=True)
                            checker_tasks.clear()

                        built_trace = trace.build()

                        if on_status:
                            await on_status("Проверяю траекторию…")
                        coach_decision, coach_trace_input = await self._trajectory_coach.review(
                            built_trace
                        )
                        trace.record_coach_review(
                            turn=turn_index,
                            tool_calls=tool_calls_completed,
                            trace_input=coach_trace_input,
                            decision=coach_decision,
                        )
                        if on_status:
                            await on_status(format_coach_status(coach_decision))

                        last_meta_review_at_tool_count = tool_calls_completed

                        if (
                            self._settings.coach_inject_hints
                            and coach_decision.should_inject_hint()
                        ):
                            for coach_message in format_coach_coaching_with_trace(
                                coach_decision,
                                built_trace,
                            ):
                                messages.append(coach_message)

                    if (
                        self._settings.agent_supervisor_soft_triggers
                        and self._supervisor is not None
                        and supervisor_cycles_left > 0
                        and turn_index != last_soft_trigger_turn
                    ):
                        soft = detect_soft_trigger(
                            trace.steps,
                            completed_turns=turn_index,
                            soft_triggers_enabled=True,
                            periodic_every=self._settings.agent_supervisor_periodic_every,
                        )
                        if soft is not None:
                            last_soft_trigger_turn = turn_index
                            logger.warning(
                                "Supervisor soft trigger at turn %s: %s (%s)",
                                turn_index,
                                soft.reason,
                                soft.detail,
                            )
                            run_result, supervisor_cycles_left, retries_left, bonus = await self._invoke_supervisor(
                                trigger=soft.reason,
                                trigger_detail=soft.detail,
                                messages=messages,
                                trace=trace,
                                sources=sources,
                                maps_links=maps_links,
                                gmail_links=gmail_links,
                                drive_links=drive_links,
                                calendar_links=calendar_links,
                                tasks_links=tasks_links,
                                on_status=on_status,
                                supervisor_cycles_left=supervisor_cycles_left,
                                retries_left=retries_left,
                                history_len=history_len,
                                skill_collapser=skill_collapser,
                                result_collapser=result_collapser,
                                checker_tasks=checker_tasks,
                            )
                            if run_result is not None:
                                return run_result
                            if bonus > 0:
                                turn_limit += bonus

                collapser.collapse_if_pending(messages)
                logger.warning(
                    "Exceeded worker tool turns (%s/%s), invoking supervisor",
                    turn_index,
                    turn_limit,
                )

                run_result, supervisor_cycles_left, retries_left, bonus = await self._invoke_supervisor(
                    trigger="cap_hit",
                    trigger_detail=f"{turn_index}/{turn_limit} turns used",
                    messages=messages,
                    trace=trace,
                    sources=sources,
                    maps_links=maps_links,
                    gmail_links=gmail_links,
                    drive_links=drive_links,
                    calendar_links=calendar_links,
                    tasks_links=tasks_links,
                    on_status=on_status,
                    supervisor_cycles_left=supervisor_cycles_left,
                    retries_left=retries_left,
                    history_len=history_len,
                    skill_collapser=skill_collapser,
                    result_collapser=result_collapser,
                    checker_tasks=checker_tasks,
                )
                if run_result is not None:
                    return run_result

                turn_limit += bonus
        finally:
            if checker_tasks:
                await asyncio.gather(*checker_tasks, return_exceptions=True)
            reset_outbound_queue(outbound_token)
            reset_run_file_store(file_store_token)
            file_store.cleanup()
            if user_id is not None:
                self._trace_store.put(user_id, trace.build())
