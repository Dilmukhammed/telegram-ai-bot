from __future__ import annotations

from tools.checker.common import is_checker_excluded
from tools.checker.explicit import EXPLICIT_CHECKER_QUESTIONS
from tools.checker.templates import template_questions_for
from tools.schema import ToolSpec
from tools.verification import VerificationQuestion


def get_checker_questions(spec: ToolSpec) -> tuple[VerificationQuestion, ...]:
    if is_checker_excluded(spec):
        return ()
    if spec.name in EXPLICIT_CHECKER_QUESTIONS:
        return EXPLICIT_CHECKER_QUESTIONS[spec.name]
    if spec.verification_questions:
        return spec.verification_questions
    return template_questions_for(spec)


def checker_has_questions(spec: ToolSpec) -> bool:
    return bool(get_checker_questions(spec))
