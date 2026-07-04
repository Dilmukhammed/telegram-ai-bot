from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from skills.session import SkillRunSnapshot
from tools.outbound_files import OutboundDelivery


@dataclass(frozen=True)
class AgentRunResult:
    reply: str
    worker_history: list[dict[str, Any]]
    skill_snapshot: SkillRunSnapshot
    maps_buttons: tuple[tuple[str, str], ...] = ()
    gmail_buttons: tuple[tuple[str, str], ...] = ()
    drive_buttons: tuple[tuple[str, str], ...] = ()
    calendar_buttons: tuple[tuple[str, str], ...] = ()
    tasks_buttons: tuple[tuple[str, str], ...] = ()
    outbound_files: tuple[OutboundDelivery, ...] = ()
