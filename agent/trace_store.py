from __future__ import annotations

from agent.run_cycle_log import CycleLogOptions, build_run_cycle_log
from agent.run_trace import RunTrace
from config import Settings, get_settings


class TraceStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
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
            f"- Failed: {', '.join(f'`{name}`' for name in trace.failed_tools) or '—'}\n"
        )
        if trace.coach_reviews:
            last = trace.coach_reviews[-1]
            header += (
                f"- Coach (T{last.get('turn', '?')}, "
                f"tools={last.get('tool_calls', '?')}): "
                f"on_track={last.get('on_track')} "
                f"risk={last.get('collapse_risk', 'low')}\n"
            )
            if last.get("focus_now"):
                header += f"- Coach focus: `{last['focus_now']}`\n"
        if trace.checker_reviews:
            last_checker = trace.checker_reviews[-1]
            header += (
                f"- Checker (T{last_checker.get('turn', '?')}, "
                f"`{last_checker.get('tool_name', '?')}`): "
                f"overall=`{last_checker.get('overall', 'unknown')}`\n"
            )
        header += "\n"
        settings = self._settings or get_settings()
        options = CycleLogOptions(
            step_limit=160,
            max_chars=max(500, max_chars - len(header) - 20),
            include_collapse_tags=False,
            include_checker_reviews=True,
        )
        body = build_run_cycle_log(trace, settings=settings, options=options)
        text = header + "```\n" + body + "\n```"
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 20].rstrip() + "\n… [truncated]"

    def format_coach_last_for_telegram(self, user_id: int, *, max_chars: int = 12000) -> str:
        trace = self.get(user_id)
        if trace is None or not trace.coach_reviews:
            return (
                "Нет coach review для этого user_id. "
                "Нужен run с AGENT_COACH_ENABLED и хотя бы один coach trigger."
            )

        last = trace.coach_reviews[-1]
        header = (
            f"**Last coach input** (user `{user_id}`)\n\n"
            f"- Turn: **{last.get('turn', '?')}** · tool_calls: **{last.get('tool_calls', '?')}**\n"
            f"- intervene: `{last.get('intervene', False)}` · on_track: `{last.get('on_track')}` · risk: `{last.get('collapse_risk', 'low')}`\n"
        )
        if last.get("focus_now"):
            header += f"- focus_now: `{last['focus_now']}`\n"
        if last.get("assessment"):
            header += f"- assessment: {last['assessment']}\n"
        header += "\n**Trace sent to coach (user message):**\n```\n"

        trace_input = str(last.get("trace_input") or "")
        if not trace_input:
            header += "(trace_input not stored — run again after update)\n```"
            return header

        budget = max(500, max_chars - len(header) - 10)
        body = trace_input if len(trace_input) <= budget else trace_input[: budget - 20].rstrip() + "\n… [truncated]"
        text = header + body + "\n```"
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 20].rstrip() + "\n… [truncated]"

    def format_checker_last_for_telegram(self, user_id: int, *, max_chars: int = 12000) -> str:
        trace = self.get(user_id)
        if trace is None or not trace.checker_reviews:
            return (
                "Нет checker review для этого user_id. "
                "Нужен run с AGENT_CHECKER_ENABLED=1 и tool с verification questions."
            )

        last = trace.checker_reviews[-1]
        header = (
            f"**Last tool checker** (user `{user_id}`)\n\n"
            f"- Turn: **{last.get('turn', '?')}** · tool: `{last.get('tool_name', '?')}`\n"
            f"- Overall: `{last.get('overall', 'unknown')}` · rule_based_only: `{last.get('rule_based_only')}`\n"
        )
        verdict_lines: list[str] = []
        for item in last.get("verdicts") or []:
            verdict_lines.append(
                f"- `{item.get('question_id')}` [{item.get('severity')}]: "
                f"**{item.get('verdict')}** — {item.get('reason') or '—'}"
            )
        if verdict_lines:
            header += "\n**Verdicts:**\n" + "\n".join(verdict_lines) + "\n"

        checker_input = str(last.get("checker_input") or "")
        header += "\n**Checker input (LLM user message):**\n```\n"
        if not checker_input:
            header += "(rule-based only — no LLM input)\n```"
            return header

        budget = max(500, max_chars - len(header) - 10)
        body = (
            checker_input
            if len(checker_input) <= budget
            else checker_input[: budget - 20].rstrip() + "\n… [truncated]"
        )
        text = header + body + "\n```"
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 20].rstrip() + "\n… [truncated]"
