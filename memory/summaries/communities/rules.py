from __future__ import annotations

from typing import Any, Mapping

FAMILY_EDGE_HINTS = frozenset(
    {
        "relation:family",
        "relation:parent",
        "relation:child",
        "relation:sibling",
        "relation:spouse",
        "has_relation:family",
    }
)
WORK_EDGE_HINTS = frozenset(
    {
        "entity_attribute:works_at",
        "entity_attribute:employer",
        "relation:colleague",
        "relation:organization",
    }
)
PROJECT_EDGE_HINTS = frozenset(
    {
        "claim:project",
        "state:project",
        "entity_attribute:project",
    }
)
TRIP_EDGE_HINTS = frozenset(
    {
        "event:travel",
        "event:trip",
        "entity_attribute:place",
        "state:travel",
    }
)
TASK_EDGE_HINTS = frozenset(
    {
        "claim:task",
        "state:task",
        "entity_attribute:document",
    }
)
INTEREST_EDGE_HINTS = frozenset(
    {
        "preference:likes",
        "preference:prefers",
        "preference:interest",
    }
)

COMMUNITY_EDGE_RULES: dict[str, frozenset[str]] = {
    "family": FAMILY_EDGE_HINTS,
    "work": WORK_EDGE_HINTS,
    "project": PROJECT_EDGE_HINTS,
    "trip_place": TRIP_EDGE_HINTS,
    "documents_tasks": TASK_EDGE_HINTS,
    "interests": INTEREST_EDGE_HINTS,
}


def edge_matches_community(edge_type: str, community_type: str) -> bool:
    allowed = COMMUNITY_EDGE_RULES.get(community_type, frozenset())
    edge = edge_type.casefold()
    if edge in allowed:
        return True
    return any(hint in edge for hint in allowed)


def node_label(node: Mapping[str, Any]) -> str:
    return str(node.get("label") or node.get("source_record_id") or "")


def seed_score(node: Mapping[str, Any], community_type: str) -> int:
    label = node_label(node).casefold()
    node_type = str(node.get("node_type") or "").casefold()
    props = node.get("properties") or {}
    entity_type = str(props.get("entity_type") or "").casefold()
    score = 0
    if community_type == "family" and entity_type == "person":
        score += 3
    if community_type == "work" and entity_type in {"organization", "person"}:
        score += 2
    if community_type == "project" and "project" in label:
        score += 3
    if community_type == "trip_place" and entity_type in {"place", "location"}:
        score += 3
    if community_type == "documents_tasks" and any(
        token in label for token in ("task", "doc", "file")
    ):
        score += 2
    if community_type == "interests" and entity_type == "concept":
        score += 1
    return score
