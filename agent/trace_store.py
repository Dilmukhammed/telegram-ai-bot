from __future__ import annotations

from agent.run_trace import RunTrace


class TraceStore:
    def __init__(self) -> None:
        self._last_by_user: dict[int, RunTrace] = {}

    def put(self, user_id: int | None, trace: RunTrace) -> None:
        if user_id is None:
            return
        self._last_by_user[user_id] = trace

    def get(self, user_id: int) -> RunTrace | None:
        return self._last_by_user.get(user_id)

    def format_for_telegram(self, user_id: int, *, max_chars: int = 3500) -> str:
        trace = self.get(user_id)
        if trace is None:
            return "Нет сохранённого trace для этого user_id. Сначала отправь боту запрос с tools."

        header = (
            f"**Last RunTrace** (user `{user_id}`)\n\n"
            f"- Outcome: `{trace.final_outcome or 'unknown'}`\n"
            f"- Steps: **{len(trace.steps)}**\n"
            f"- Turns: **{trace.worker_turns_used}/{trace.worker_turns_budget}**\n"
            f"- Successful: {', '.join(f'`{name}`' for name in trace.successful_tools) or '—'}\n"
            f"- Failed: {', '.join(f'`{name}`' for name in trace.failed_tools) or '—'}\n\n"
        )
        body = trace.to_supervisor_text(max_chars=max(500, max_chars - len(header) - 20))
        text = header + "```\n" + body + "\n```"
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 20].rstrip() + "\n… [truncated]"
