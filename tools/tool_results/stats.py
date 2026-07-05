from __future__ import annotations

import json
from dataclasses import dataclass

from config import format_byte_size
from local_tokenizer import count_text
from tools.tool_results.archive import archived_content_json
from tools.tool_results.store import get_tool_result_store


@dataclass(frozen=True)
class ArchiveCompressionStats:
    sample_count: int
    stub_tokens: int
    full_tokens: int
    stub_chars: int
    full_chars: int

    @property
    def token_kept_percent(self) -> float:
        if self.full_tokens <= 0:
            return 0.0
        return self.stub_tokens / self.full_tokens * 100

    @property
    def token_saved_percent(self) -> float:
        return max(0.0, 100.0 - self.token_kept_percent)


@dataclass(frozen=True)
class HistoryArchiveCompressionStats:
    archived_in_history: int
    stub_tokens: int
    full_tokens: int

    @property
    def token_saved_percent(self) -> float:
        if self.full_tokens <= 0:
            return 0.0
        return max(0.0, (1 - self.stub_tokens / self.full_tokens) * 100)


def load_user_archive_compression(user_id: int) -> ArchiveCompressionStats | None:
    records = get_tool_result_store().list_summarized(user_id)
    if not records:
        return None
    stub_tokens = 0
    full_tokens = 0
    stub_chars = 0
    full_chars = 0
    for record in records:
        stub = archived_content_json(record)
        stub_tokens += count_text(stub)
        full_tokens += count_text(record.payload_json)
        stub_chars += len(stub)
        full_chars += len(record.payload_json)
    return ArchiveCompressionStats(
        sample_count=len(records),
        stub_tokens=stub_tokens,
        full_tokens=full_tokens,
        stub_chars=stub_chars,
        full_chars=full_chars,
    )


def load_history_archive_compression(
    history: list[dict],
    *,
    user_id: int,
) -> HistoryArchiveCompressionStats | None:
    store = get_tool_result_store()
    archived_in_history = 0
    stub_tokens = 0
    full_tokens = 0
    for message in history:
        if message.get("role") != "tool":
            continue
        content = str(message.get("content") or "")
        if not content:
            continue
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            stub_tokens += count_text(content)
            full_tokens += count_text(content)
            continue
        if not payload.get("archived"):
            stub_tokens += count_text(content)
            full_tokens += count_text(content)
            continue
        ref = payload.get("ref")
        if ref is None or ref == "":
            stub_tokens += count_text(content)
            full_tokens += count_text(content)
            continue
        archived_in_history += 1
        stub_tokens += count_text(content)
        record = store.get(ref, user_id=user_id)
        full_tokens += count_text(record.payload_json if record else content)
    if archived_in_history == 0:
        return None
    return HistoryArchiveCompressionStats(
        archived_in_history=archived_in_history,
        stub_tokens=stub_tokens,
        full_tokens=full_tokens,
    )


def format_compression_percent(saved_percent: float) -> str:
    if saved_percent <= 0:
        return "0%"
    if saved_percent < 10:
        return f"{saved_percent:.1f}%"
    return f"{saved_percent:.0f}%"


@dataclass(frozen=True)
class UserArchiveStats:
    row_count: int
    byte_count: int
    summarize_ok: int
    summarize_pending: int
    summarize_failed: int
    expired_pending: int
    top_tools: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class GlobalArchiveStats:
    row_count: int
    byte_count: int
    user_count: int
    summarize_ok: int
    summarize_pending: int
    summarize_failed: int


def load_user_archive_stats(user_id: int, *, top_tools: int = 5) -> UserArchiveStats:
    raw = get_tool_result_store().user_archive_stats_detailed(user_id, top_tools=top_tools)
    return UserArchiveStats(
        row_count=raw["row_count"],
        byte_count=raw["byte_count"],
        summarize_ok=raw["summarize_ok"],
        summarize_pending=raw["summarize_pending"],
        summarize_failed=raw["summarize_failed"],
        expired_pending=raw["expired_pending"],
        top_tools=tuple(raw["top_tools"]),
    )


def load_global_archive_stats() -> GlobalArchiveStats:
    raw = get_tool_result_store().global_archive_stats()
    return GlobalArchiveStats(
        row_count=raw["row_count"],
        byte_count=raw["byte_count"],
        user_count=raw["user_count"],
        summarize_ok=raw["summarize_ok"],
        summarize_pending=raw["summarize_pending"],
        summarize_failed=raw["summarize_failed"],
    )


def format_archive_stats_section(
    *,
    user_id: int,
    include_global: bool = True,
    history: list[dict] | None = None,
) -> str:
    from config import get_settings

    settings = get_settings()
    if not settings.tool_result_archive_enabled:
        return "**Tool result archive**\n\n- Disabled (`TOOL_RESULT_ARCHIVE_ENABLED=false`)"

    user = load_user_archive_stats(user_id)
    lines = [
        "**Tool result archive**",
        "",
        f"- Your stored refs: **{user.row_count:,}** ({format_byte_size(user.byte_count)})",
        f"- Summarize: ok **{user.summarize_ok}**, pending **{user.summarize_pending}**, "
        f"failed **{user.summarize_failed}**",
    ]
    if user.expired_pending:
        lines.append(f"- Expired (awaiting cleanup): **{user.expired_pending}**")
    if user.top_tools:
        tool_lines = ", ".join(f"`{name}`×{count}" for name, count in user.top_tools)
        lines.append(f"- Top tools: {tool_lines}")
    lines.append(f"- TTL: **{settings.tool_result_ttl_hours}h**")

    compression = load_user_archive_compression(user_id)
    if compression is not None:
        avg_stub = compression.stub_tokens / compression.sample_count
        avg_full = compression.full_tokens / compression.sample_count
        lines.extend(
            [
                "",
                "**Archive compression** (local tokenizer `gemini-2.5-flash`)",
                f"- Stored summarized refs: **{compression.sample_count}**",
                f"- Avg stub: **{avg_stub:,.0f}** tok vs full **{avg_full:,.0f}** tok",
                f"- Token reduction: **{format_compression_percent(compression.token_saved_percent)}** "
                f"(keep **{compression.token_kept_percent:.1f}%** of full)",
                f"- Chars: **{compression.stub_chars / compression.full_chars * 100:.1f}%** of full",
            ]
        )

    if history is not None:
        history_compression = load_history_archive_compression(history, user_id=user_id)
        if history_compression is not None:
            lines.extend(
                [
                    "",
                    "**History (archived tool results only)**",
                    f"- Archived stubs in chat: **{history_compression.archived_in_history}**",
                    f"- Current tool tokens: **{history_compression.stub_tokens:,}**",
                    f"- If kept full payloads: **{history_compression.full_tokens:,}**",
                    f"- Saved in history: **{format_compression_percent(history_compression.token_saved_percent)}**",
                ]
            )

    if include_global:
        global_stats = load_global_archive_stats()
        lines.extend(
            [
                "",
                "**Archive (all users)**",
                f"- Total refs: **{global_stats.row_count:,}** "
                f"({format_byte_size(global_stats.byte_count)})",
                f"- Users with data: **{global_stats.user_count}**",
                f"- Summarize: ok **{global_stats.summarize_ok}**, "
                f"pending **{global_stats.summarize_pending}**, "
                f"failed **{global_stats.summarize_failed}**",
            ]
        )
    return "\n".join(lines)
