from __future__ import annotations

import logging
from dataclasses import dataclass

from skills.auto_load import queue_skill_load
from skills.collapse import SkillContextCollapser, skills_collapse_idle_turns

logger = logging.getLogger(__name__)


@dataclass
class SkillSessionState:
    expanded_skill_id: str | None = None
    idle_runs: int = 0


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
    """Re-inject the session's expanded skill at the start of an agent run."""
    if user_id is None:
        return None
    skill_id = SkillSessionStore.get(user_id).expanded_skill_id
    if not skill_id:
        return None
    if queue_skill_load(skill_id):
        logger.info("skill_session_inject user_id=%s skill_id=%s", user_id, skill_id)
        return skill_id
    return None


def apply_skill_run_snapshot(user_id: int | None, snapshot: SkillRunSnapshot) -> None:
    """Update per-chat session skill state after a completed agent run."""
    if user_id is None:
        return

    state = SkillSessionStore.get(user_id)
    threshold = skills_collapse_idle_turns()

    if snapshot.expanded_skill_id:
        if snapshot.expanded_skill_id in snapshot.skills_with_tools:
            state.expanded_skill_id = snapshot.expanded_skill_id
            state.idle_runs = 0
        else:
            state.expanded_skill_id = snapshot.expanded_skill_id
            state.idle_runs += 1
            if state.idle_runs >= threshold:
                logger.info(
                    "skill_session_idle_clear user_id=%s skill_id=%s idle_runs=%s",
                    user_id,
                    snapshot.expanded_skill_id,
                    state.idle_runs,
                )
                state.expanded_skill_id = None
                state.idle_runs = 0
        logger.info(
            "skill_session_update user_id=%s expanded=%s idle_runs=%s tools=%s",
            user_id,
            state.expanded_skill_id,
            state.idle_runs,
            sorted(snapshot.skills_with_tools),
        )
        return

    state.expanded_skill_id = None
    state.idle_runs = 0
    logger.info(
        "skill_session_update user_id=%s expanded=None (collapsed this run)",
        user_id,
    )
