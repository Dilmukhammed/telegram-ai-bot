from __future__ import annotations

import re

from agent.tool_checker import ToolCheckerReview
from tools.verification import SEVERITY_CRITICAL, VERDICT_FAIL

_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")


def user_prefers_russian(user_message: str) -> bool:
    return bool(_CYRILLIC_RE.search(user_message))


def critical_failures(review: ToolCheckerReview) -> list[tuple[str, str]]:
    return [
        (item.question_id, item.reason)
        for item in review.verdicts
        if item.verdict == VERDICT_FAIL and item.severity == SEVERITY_CRITICAL and item.reason
    ]


def should_inject_checker_hint(review: ToolCheckerReview) -> bool:
    return bool(critical_failures(review))


def format_checker_hint_message(
    review: ToolCheckerReview,
    *,
    user_message: str,
) -> dict[str, str]:
    return {
        "role": "user",
        "content": format_checker_hint(review, user_message=user_message),
    }


def format_checker_hint(review: ToolCheckerReview, *, user_message: str) -> str:
    failures = critical_failures(review)
    if not failures:
        return ""

    russian = user_prefers_russian(user_message)
    if russian:
        header = (
            "[Internal — tool checker]\n"
            f"Проверка вызова {review.tool_name} (turn {review.turn}): critical fail.\n"
        )
        intro = "Исправь следующий шаг с учётом замечаний. Не сообщай пользователю о проверке."
        bullet_prefix = "- "
    else:
        header = (
            "[Internal — tool checker]\n"
            f"Review of {review.tool_name} (turn {review.turn}): critical fail.\n"
        )
        intro = "Fix your next step based on these issues. Do not mention this review to the user."
        bullet_prefix = "- "

    lines = [header, ""]
    for question_id, reason in failures:
        lines.append(f"{bullet_prefix}{question_id}: {reason}")
    lines.extend(["", intro])
    return "\n".join(lines)
