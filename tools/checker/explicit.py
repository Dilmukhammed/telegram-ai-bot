from __future__ import annotations

from tools.builtins.google.calendar_checker import CALENDAR_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.google.drive_checker import DRIVE_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.google.gmail_checker import GMAIL_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.google.maps_checker import MAPS_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.google.sheets_checker import SHEETS_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.google.tasks_checker import TASKS_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.pdf.pdf_checker import PDF_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.workspace.workspace_checker import WORKSPACE_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.yandex.music_checker import MUSIC_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.chat_checker import CHAT_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.exa_checker import EXA_CHECKER_QUESTIONS_BY_TOOL
from tools.builtins.telegram_checker import TELEGRAM_CHECKER_QUESTIONS_BY_TOOL
from tools.verification import VerificationQuestion

EXPLICIT_CHECKER_QUESTIONS: dict[str, tuple[VerificationQuestion, ...]] = {
    **CALENDAR_CHECKER_QUESTIONS_BY_TOOL,
    **GMAIL_CHECKER_QUESTIONS_BY_TOOL,
    **SHEETS_CHECKER_QUESTIONS_BY_TOOL,
    **DRIVE_CHECKER_QUESTIONS_BY_TOOL,
    **TASKS_CHECKER_QUESTIONS_BY_TOOL,
    **MAPS_CHECKER_QUESTIONS_BY_TOOL,
    **WORKSPACE_CHECKER_QUESTIONS_BY_TOOL,
    **PDF_CHECKER_QUESTIONS_BY_TOOL,
    **MUSIC_CHECKER_QUESTIONS_BY_TOOL,
    **EXA_CHECKER_QUESTIONS_BY_TOOL,
    **TELEGRAM_CHECKER_QUESTIONS_BY_TOOL,
    **CHAT_CHECKER_QUESTIONS_BY_TOOL,
}
