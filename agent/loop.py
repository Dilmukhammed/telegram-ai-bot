import asyncio
import copy
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from agent.context_collapse import SearchContextCollapser
from agent.prompts import AGENT_SYSTEM_PROMPT
from agent.run_result import AgentRunResult
from agent.run_trace import RunTraceCollector
from agent.supervisor import (
    AgentSupervisor,
    fallback_stop_decision,
    format_supervisor_coaching,
    format_supervisor_retry,
    format_supervisor_stop,
)
from agent.supervisor_triggers import detect_soft_trigger
from agent.supervisor_telemetry import SupervisorTelemetry
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
    auto_load_skills_for_run,
    maybe_auto_load_after_tool,
    reset_auto_load_run_state,
)
from skills.collapse import SkillContextCollapser, sanitize_expanded_skills_for_context
from skills.pending import reset_skill_run_state
from skills.session import build_skill_run_snapshot, inject_session_skill_for_run
from skills.usage_tracker import record_tool_use
from tools.workspace.vision_pending import take_pending_vision
from agent.sources import SourceCollector, append_sources
from agent.transit_guard import skipped_web_search_result, transit_route_satisfied
from agent.history_persist import extract_worker_history_for_persist
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

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], Awaitable[None]]


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


def _parse_tool_arguments(raw_args: str) -> dict[str, Any]:
    try:
        return json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {}


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
    return f"Запускаю {target}…"


class Agent:
    def __init__(self, settings: Settings, runtime: ToolRuntime) -> None:
        self._settings = settings
        self._llm = LLMClient(settings)
        self._runtime = runtime
        self._max_tool_turns = settings.agent_max_tool_turns
        self._supervisor = (
            AgentSupervisor(self._llm, settings) if settings.agent_supervisor_enabled else None
        )
        self._trace_store = TraceStore()
        self._supervisor_telemetry = SupervisorTelemetry()

    def stats_report(self, runtime: ToolRuntime) -> str:
        return (
            runtime.stats_report()
            + "\n\n"
            + self._supervisor_telemetry.format_report()
        )

    def trace_last_report(self, user_id: int) -> str:
        return self._trace_store.format_for_telegram(user_id)

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
            messages.extend(sanitize_expanded_skills_for_context(history))
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

    async def _dispatch_tool_call(
        self,
        tool_call: Any,
        turn: int,
        user_id: int | None,
        on_status: StatusCallback | None,
        trace: RunTraceCollector,
        messages: list[dict[str, Any]],
    ) -> tuple[str, str]:
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

        logger.info("Tool call turn=%s name=%s args=%s", turn + 1, tool_name, arguments)

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
        trace.on_tool_result(
            turn=turn,
            call_id=tool_call.id,
            result_json=result,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return tool_call.id, result

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
        sources: SourceCollector,
        maps_links: MapsLinkCollector,
        gmail_links: GmailLinkCollector,
        drive_links: DriveLinkCollector,
        calendar_links: CalendarLinkCollector,
        tasks_links: TasksLinkCollector,
        hinted_tool_groups: set[str],
        hinted_skill_groups: set[str],
        chat_history: list[dict[str, Any]] | None = None,
    ) -> None:
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
                        tool_call, turn, user_id, on_status, trace, messages
                    )
                    for tool_call in tool_calls
                ]
            )
        else:
            pairs = []
            for tool_call in tool_calls:
                pairs.append(
                    await self._dispatch_tool_call(
                        tool_call, turn, user_id, on_status, trace, messages
                    )
                )

        tool_results: list[str] = []
        for tool_call_id, result in pairs:
            try:
                payload = json.loads(result)
            except json.JSONDecodeError:
                payload = {}
            if payload.get("ok"):
                tool_name = str(payload.get("tool_name") or "")
                if tool_name:
                    record_tool_use(tool_name)
                    maybe_auto_load_after_tool(tool_name, history=chat_history)
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
        skill_collapser.collapse_idle_if_needed(messages, turn)

        collapser.on_tool_turn(messages, tool_calls, tool_results)

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
                _complete_run(
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
                ),
                supervisor_cycles_left,
                retries_left,
                0,
            )

        if on_status:
            await on_status("Проверяю шаги агента…")

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
            _complete_run(
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
        skill_collapser = SkillContextCollapser()
        skill_collapser.sync_from_messages(messages)
        session_injected = inject_session_skill_for_run(user_id)
        if session_injected:
            logger.info("session_skill_injected skill_id=%s user_id=%s", session_injected, user_id)
        auto_loaded = auto_load_skills_for_run(user_message, history)
        if auto_loaded:
            logger.info("auto_loaded_skills skill_ids=%s", auto_loaded)
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
        last_soft_trigger_turn = -1

        run_id = uuid.uuid4().hex[:12]
        file_store = RunFileStore(run_id=run_id, user_id=user_id)
        outbound_queue = OutboundQueue()
        file_store_token = set_run_file_store(file_store)
        outbound_token = set_outbound_queue(outbound_queue)

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
                        skill_collapser.collapse_idle_if_needed(messages, turn_index)
                        content = (message.content or "").strip()
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
                        return _complete_run(
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

                    messages.append(message.model_dump(exclude_none=True))
                    await self._execute_tool_turn(
                        turn=turn_index,
                        messages=messages,
                        tool_calls=tool_calls,
                        user_id=user_id,
                        on_status=on_status,
                        trace=trace,
                        collapser=collapser,
                        skill_collapser=skill_collapser,
                        sources=sources,
                        maps_links=maps_links,
                        gmail_links=gmail_links,
                        drive_links=drive_links,
                        calendar_links=calendar_links,
                        tasks_links=tasks_links,
                        hinted_tool_groups=hinted_tool_groups,
                        hinted_skill_groups=hinted_skill_groups,
                        chat_history=history,
                    )
                    turn_index += 1

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
                )
                if run_result is not None:
                    return run_result

                turn_limit += bonus
        finally:
            reset_outbound_queue(outbound_token)
            reset_run_file_store(file_store_token)
            file_store.cleanup()
            if user_id is not None:
                self._trace_store.put(user_id, trace.build())
