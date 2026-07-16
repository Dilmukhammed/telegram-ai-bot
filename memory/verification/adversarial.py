from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def looks_like_correction(candidate: Mapping[str, Any]) -> bool:
    """Structural correction detection — independent of free kind/schema labels."""
    kind = str(
        candidate.get("candidate_kind") or candidate.get("kind") or ""
    ).casefold()
    schema = str(candidate.get("schema_name") or "").casefold()
    # Soft fallback: correction / corrects_* / *_correction, etc.
    if "correct" in kind or "correct" in schema:
        return True
    roles = {
        str(item.get("role") or "").casefold()
        for item in candidate.get("arguments") or ()
        if isinstance(item, Mapping)
    }
    if "old" in roles and "new" in roles:
        return True
    for item in candidate.get("evidence") or ():
        if isinstance(item, Mapping) and str(item.get("relation") or "") == "corrects":
            return True
    return False


def requires_adversarial_verification(candidate: Mapping[str, Any]) -> bool:
    epistemic = candidate.get("epistemic")
    if not isinstance(epistemic, Mapping):
        return True
    if str(candidate.get("polarity")) in {"negative", "unknown"}:
        return True
    if str(epistemic.get("mode")) in {"reported", "quoted", "inferred"}:
        return True
    if looks_like_correction(candidate):
        return True
    if bool(candidate.get("temporal")):
        return True
    if epistemic.get("needs_confirmation") is True:
        return True
    return False


def argument_roles(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    roles: list[str] = []
    arguments = candidate.get("arguments")
    if not isinstance(arguments, Sequence):
        return ()
    for item in arguments:
        if isinstance(item, Mapping):
            role = str(item.get("role") or "").strip()
            if role:
                roles.append(role)
    return tuple(roles)
