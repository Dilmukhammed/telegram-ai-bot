from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def requires_adversarial_verification(candidate: Mapping[str, Any]) -> bool:
    epistemic = candidate.get("epistemic")
    if not isinstance(epistemic, Mapping):
        return True
    if str(candidate.get("polarity")) in {"negative", "unknown"}:
        return True
    if str(epistemic.get("mode")) in {"reported", "quoted", "inferred"}:
        return True
    if str(candidate.get("candidate_kind")) == "correction":
        return True
    if bool(candidate.get("temporal")):
        return True
    if epistemic.get("needs_confirmation") is True:
        return True
    return False
