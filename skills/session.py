from __future__ import annotations

import logging
from dataclasses import dataclass

from skills.collapse import SkillContextCollapser

logger = logging.getLogger(__name__)


@dataclass
class SkillSessionState:
    expanded_skill_id: str | None = None


@dataclass(frozen=True)
class SkillRunSnapshot:
    expanded_skill_id: str | None
    skills_with_tools: frozenset[str]


class SkillSessionStore:
    _by_user: dict[int, SkillSessionState] = {}

    @classmethod
    def get(cls, user_id: int) -> SkillSessionState:
        if user_id not in cls._by_user:
            cls._by_user[user_id] = SkillSessionState()
        return cls._by_user[user_id]

    @classmethod
    def reset(cls, user_id: int) -> None:
        if user_id in cls._by_user:
            del cls._by_user[user_id]
            logger.info("skill_session_reset user_id=%s", user_id)


def build_skill_run_snapshot(collapser: SkillContextCollapser) -> SkillRunSnapshot:
    from skills.usage_tracker import skills_with_tools_this_run

    return SkillRunSnapshot(
        expanded_skill_id=collapser.primary_expanded_skill_id(),
        skills_with_tools=frozenset(skills_with_tools_this_run()),
    )


def inject_session_skill_for_run(user_id: int | None) -> str | None:
    """Deprecated: expanded skills persist in chat history between runs."""
    return None


def apply_skill_run_snapshot(user_id: int | None, snapshot: SkillRunSnapshot) -> None:
    """Track active skill for /reset metadata; playbook stays in chat history."""
    if user_id is None:
        return

    state = SkillSessionStore.get(user_id)
    state.expanded_skill_id = snapshot.expanded_skill_id
    logger.info(
        "skill_session_update user_id=%s expanded=%s tools=%s",
        user_id,
        state.expanded_skill_id,
        sorted(snapshot.skills_with_tools),
    )
