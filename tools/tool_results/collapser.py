from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Literal

from agent.coach_dialog import is_coach_reply_tool
from config import Settings
from llm import LLMClient
from tools.coerce import normalize_use_tool_call
from tools.tool_results.archive import (
    RECALL_TOOL_NAME,
    archived_content_json,
    archived_tool_call_arguments_json,
    is_archived_tool_call_arguments,
    is_archived_tool_content,
    parse_tool_results_get_display_ref,
    should_archive_tool_call_arguments,
    should_archive_tool_content,
    should_collapse_tool_results_get,
)
from tools.tool_results.store import StoredToolResult, ToolResultStore, get_tool_result_store
from tools.tool_results.summarize import (
    apply_summary_unavailable,
    summary_ok_for_reuse,
    summary_ready_for_collapse,
)
from tools.tool_results.summarize_queue import get_summarize_queue

logger = logging.getLogger(__name__)


@dataclass
class ArchivedToolEntry:
    ref: str
    tool_call_id: str
    turn: int
    kind: Literal["result", "arguments"] = "result"
    collapsed: bool = False
    summarize_task: asyncio.Task[None] | None = None
    recall_display_ref: int | None = None


@dataclass
class ToolResultCollapser:
    settings: Settings
    llm: LLMClient
    user_id: int | None
    run_id: str
    store: ToolResultStore = field(default_factory=get_tool_result_store)
    entries: list[ArchivedToolEntry] = field(default_factory=list)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _summarize_tasks_by_ref: dict[str, asyncio.Task[None]] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.settings.tool_result_archive_enabled and self.user_id is not None

    def register_tool_message(
        self,
        *,
        tool_call_id: str,
        turn: int,
        content: str,
        tool_name: str | None,
        args_json: str | None,
    ) -> None:
        if not self.enabled:
            return

        min_chars = self.settings.tool_result_archive_min_chars
        if should_collapse_tool_results_get(content, min_chars=min_chars, tool_name=tool_name):
            display_ref = parse_tool_results_get_display_ref(content, tool_name=tool_name)
            if display_ref is not None:
                self._register_recall_tool_message(
                    tool_call_id=tool_call_id,
                    turn=turn,
                    display_ref=display_ref,
                )
            return

        if tool_name == RECALL_TOOL_NAME:
            return

        if not should_archive_tool_content(content, min_chars=min_chars):
            return

        payload = content
        ok = True
        cached = False
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                ok = bool(parsed.get("ok", True))
                cached = bool(parsed.get("cached", False))
                tool_name = tool_name or parsed.get("tool_name")
        except (json.JSONDecodeError, TypeError):
            pass

        if not tool_name:
            return

        ref = self.store.insert(
            user_id=self.user_id,  # type: ignore[arg-type]
            run_id=self.run_id,
            tool_name=tool_name,
            turn=turn,
            args_json=args_json,
            payload_json=payload,
            ok=ok,
            cached=cached,
            payload_kind="result",
        )
        entry = ArchivedToolEntry(
            ref=ref,
            tool_call_id=tool_call_id,
            turn=turn,
        )
        self.entries.append(entry)
        entry.summarize_task = self._queue_summarize_for_record(
            self.store.get(ref, user_id=self.user_id),  # type: ignore[arg-type]
            args_json=args_json,
        )
        record = self.store.get(ref, user_id=self.user_id)  # type: ignore[arg-type]
        if record is not None:
            from bot.chat_store import get_chat_store
            from bot.chat_index.sync import enqueue_index_tool_result

            enqueue_index_tool_result(
                get_chat_store(),
                user_id=record.user_id,
                display_ref=record.display_ref,
                tool_name=record.tool_name,
                summary=record.summary,
                payload_json=record.payload_json,
                run_id=record.run_id,
            )
        logger.info(
            "tool_result_archive registered ref=%s tool=%s turn=%s call_id=%s chars=%s",
            ref,
            tool_name,
            turn,
            tool_call_id,
            len(payload),
        )

    def register_assistant_tool_calls(
        self,
        assistant_message: dict,
        *,
        turn: int,
    ) -> None:
        if not self.enabled:
            return
        if assistant_message.get("role") != "assistant":
            return

        min_chars = self.settings.tool_result_archive_min_chars
        for call in assistant_message.get("tool_calls") or []:
            function = call.get("function") or {}
            if function.get("name") != "use_tool":
                continue
            tool_call_id = call.get("id")
            if not tool_call_id:
                continue
            args_str = str(function.get("arguments") or "")
            if not should_archive_tool_call_arguments(args_str, min_chars=min_chars):
                continue

            try:
                raw_args = json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                raw_args = {}
            if not isinstance(raw_args, dict):
                continue

            target, _inner = normalize_use_tool_call(raw_args)
            if not target or is_coach_reply_tool(target):
                continue

            ref = self.store.insert(
                user_id=self.user_id,  # type: ignore[arg-type]
                run_id=self.run_id,
                tool_name=target,
                turn=turn,
                args_json=args_json_for_use_tool(raw_args),
                payload_json=args_str,
                ok=True,
                cached=False,
                payload_kind="arguments",
            )
            entry = ArchivedToolEntry(
                ref=ref,
                tool_call_id=tool_call_id,
                turn=turn,
                kind="arguments",
            )
            self.entries.append(entry)
            entry.summarize_task = self._queue_summarize_for_record(
                self.store.get(ref, user_id=self.user_id),  # type: ignore[arg-type]
                args_json=args_json_for_use_tool(raw_args),
                payload_kind="arguments",
            )
            logger.info(
                "tool_call_args_archive registered ref=%s tool=%s turn=%s call_id=%s chars=%s",
                ref,
                target,
                turn,
                tool_call_id,
                len(args_str),
            )

    def _register_recall_tool_message(
        self,
        *,
        tool_call_id: str,
        turn: int,
        display_ref: int,
    ) -> None:
        record = self.store.get(display_ref, user_id=self.user_id)  # type: ignore[arg-type]
        if record is None:
            logger.info(
                "tool_result_archive recall skip unknown ref=%s call_id=%s",
                display_ref,
                tool_call_id,
            )
            return

        entry = ArchivedToolEntry(
            ref=record.ref,
            tool_call_id=tool_call_id,
            turn=turn,
            recall_display_ref=display_ref,
        )
        if not summary_ok_for_reuse(record.summarize_status, record.summary):
            entry.summarize_task = self._queue_summarize_for_record(record)
        self.entries.append(entry)
        logger.info(
            "tool_result_archive recall registered display_ref=%s tool=%s turn=%s call_id=%s reuse_summary=%s",
            display_ref,
            record.tool_name,
            turn,
            tool_call_id,
            summary_ok_for_reuse(record.summarize_status, record.summary),
        )

    def _queue_summarize_for_record(
        self,
        record: StoredToolResult | None,
        *,
        args_json: str | None = None,
        payload_kind: str = "result",
    ) -> asyncio.Task[None] | None:
        if record is None:
            return None
        existing = self._summarize_tasks_by_ref.get(record.ref)
        if existing is not None and not existing.done():
            return existing
        queue = get_summarize_queue(self.settings)
        task = queue.submit(
            self.llm,
            self.settings,
            self.store,
            ref=record.ref,
            tool_name=record.tool_name,
            args_json=args_json if args_json is not None else record.args_json,
            payload_json=record.payload_json,
            payload_kind=payload_kind,
        )
        self._summarize_tasks_by_ref[record.ref] = task
        self._tasks.append(task)
        return task

    async def collapse_stale(self, messages: list[dict], current_turn: int) -> int:
        if not self.enabled:
            return 0
        threshold = self.settings.tool_result_collapse_stale_steps
        collapsed = 0
        for entry in self.entries:
            if entry.collapsed:
                continue
            if current_turn - entry.turn < threshold:
                continue
            if await self._collapse_entry(messages, entry):
                collapsed += 1
        return collapsed

    async def collapse_all(self, messages: list[dict]) -> int:
        if not self.enabled:
            return 0
        collapsed = 0
        for entry in self.entries:
            if entry.collapsed:
                continue
            if await self._collapse_entry(messages, entry):
                collapsed += 1
        return collapsed

    async def _collapse_entry(self, messages: list[dict], entry: ArchivedToolEntry) -> bool:
        if entry.collapsed:
            return False
        if entry.kind == "arguments":
            return await self._collapse_arguments_entry(messages, entry)
        tool_index = _find_tool_message_index(messages, entry.tool_call_id)
        if tool_index is None:
            entry.collapsed = True
            return False
        tool_message = messages[tool_index]
        if tool_message.get("role") != "tool":
            return False
        content = str(tool_message.get("content") or "")
        if is_archived_tool_content(content):
            entry.collapsed = True
            return False

        record = self._resolve_target_record(entry)
        if record is None:
            return False

        needs_summarize = (
            not summary_ok_for_reuse(record.summarize_status, record.summary)
            if entry.recall_display_ref is not None
            else not summary_ready_for_collapse(record.summarize_status, record.summary)
        )
        if needs_summarize:
            if entry.summarize_task is None or entry.summarize_task.done():
                entry.summarize_task = self._queue_summarize_for_record(record)
            await self._wait_for_task(entry.summarize_task)
            record = self._resolve_target_record(entry)
            if record is None:
                return False

        record = self._ensure_collapsible_record(record)
        if record is None or not summary_ready_for_collapse(
            record.summarize_status,
            record.summary,
        ):
            logger.info(
                "tool_result_archive skip collapse ref=%s status=%s recall=%s",
                entry.ref,
                record.summarize_status if record else "missing",
                entry.recall_display_ref,
            )
            return False

        tool_message["content"] = archived_content_json(record)
        entry.collapsed = True
        logger.info(
            "tool_result_archive collapsed ref=%s tool=%s call_id=%s recall=%s",
            record.ref,
            record.tool_name,
            entry.tool_call_id,
            entry.recall_display_ref,
        )
        return True

    async def _collapse_arguments_entry(
        self,
        messages: list[dict],
        entry: ArchivedToolEntry,
    ) -> bool:
        located = _find_assistant_tool_call(messages, entry.tool_call_id)
        if located is None:
            entry.collapsed = True
            return False
        message_index, call_index = located
        assistant_message = messages[message_index]
        tool_calls = assistant_message.get("tool_calls") or []
        function = tool_calls[call_index].get("function") or {}
        args_str = str(function.get("arguments") or "")
        if is_archived_tool_call_arguments(args_str):
            entry.collapsed = True
            return False

        record = self._resolve_target_record(entry)
        if record is None:
            return False

        if not summary_ready_for_collapse(record.summarize_status, record.summary):
            if entry.summarize_task is None or entry.summarize_task.done():
                entry.summarize_task = self._queue_summarize_for_record(
                    record,
                    payload_kind="arguments",
                )
            await self._wait_for_task(entry.summarize_task)
            record = self._resolve_target_record(entry)
            if record is None:
                return False

        record = self._ensure_collapsible_record(record)
        if record is None or not summary_ready_for_collapse(
            record.summarize_status,
            record.summary,
        ):
            logger.info(
                "tool_call_args_archive skip collapse ref=%s status=%s",
                entry.ref,
                record.summarize_status if record else "missing",
            )
            return False

        function["arguments"] = archived_tool_call_arguments_json(record)
        entry.collapsed = True
        logger.info(
            "tool_call_args_archive collapsed ref=%s tool=%s call_id=%s",
            record.ref,
            record.tool_name,
            entry.tool_call_id,
        )
        return True

    def _resolve_target_record(self, entry: ArchivedToolEntry) -> StoredToolResult | None:
        if entry.recall_display_ref is not None:
            return self.store.get(entry.recall_display_ref, user_id=self.user_id)  # type: ignore[arg-type]
        return self.store.get(entry.ref, user_id=self.user_id)  # type: ignore[arg-type]

    async def _wait_for_task(self, task: asyncio.Task[None] | None) -> None:
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(task, timeout=self.settings.tool_result_collapse_wait_seconds)
        except TimeoutError:
            logger.info("tool_result_archive summarize wait timeout")

    def _ensure_collapsible_record(self, record: StoredToolResult) -> StoredToolResult | None:
        if summary_ready_for_collapse(record.summarize_status, record.summary):
            return record
        apply_summary_unavailable(
            self.store,
            record.ref,
            summarize_attempts=record.summarize_attempts,
        )
        logger.info(
            "tool_result_archive fallback unavailable ref=%s prior_status=%s",
            record.ref,
            record.summarize_status,
        )
        return self.store.get(record.ref, user_id=self.user_id)  # type: ignore[arg-type]


def _find_tool_message_index(messages: list[dict], tool_call_id: str) -> int | None:
    for index, message in enumerate(messages):
        if message.get("role") == "tool" and message.get("tool_call_id") == tool_call_id:
            return index
    return None


def _find_assistant_tool_call(
    messages: list[dict],
    tool_call_id: str,
) -> tuple[int, int] | None:
    for message_index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        for call_index, call in enumerate(message.get("tool_calls") or []):
            if call.get("id") == tool_call_id:
                return message_index, call_index
    return None


def args_json_for_use_tool(raw_arguments: dict) -> str | None:
    tool_name, inner = normalize_use_tool_call(raw_arguments)
    if not tool_name:
        return None
    return json.dumps(
        {"tool_name": tool_name, "arguments": inner},
        ensure_ascii=False,
        sort_keys=True,
    )
