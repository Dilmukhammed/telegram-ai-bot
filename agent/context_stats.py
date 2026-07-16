from __future__ import annotations

from config import Settings
from local_tokenizer import DEFAULT_LOCAL_TOKENIZER_MODEL


def format_context_fill_percent(prompt_tokens: int, window_tokens: int) -> str:
    if window_tokens <= 0:
        return "—"
    percent = prompt_tokens / window_tokens * 100
    if prompt_tokens > 0 and percent < 0.01:
        return "<0.01%"
    if percent < 10:
        return f"{percent:.2f}%"
    return f"{percent:.1f}%"


def format_context_stats(
    settings: Settings,
    prompt_tokens: int,
    *,
    user_id: int | None = None,
    history: list[dict] | None = None,
) -> str:
    from bot.model_runtime import active_agent_model

    window = settings.llm_context_window_tokens
    model = active_agent_model(settings.openai_model)
    reasoning = settings.reasoning_effort or "none"
    fill = format_context_fill_percent(prompt_tokens, window)
    parts = [
        "**Context stats**",
        "",
        f"- Model: `{model}`",
        f"- Reasoning: `{reasoning}`",
        f"- Tokenizer: local `{DEFAULT_LOCAL_TOKENIZER_MODEL}` (google-genai)",
        f"- Context: **{prompt_tokens:,}** / {window:,} tokens (**{fill}**)",
    ]
    if user_id is not None and settings.tool_result_archive_enabled:
        from tools.tool_results.stats import format_archive_stats_section

        parts.extend(
            [
                "",
                format_archive_stats_section(
                    user_id=user_id,
                    history=history,
                ),
            ]
        )
    return "\n".join(parts)
