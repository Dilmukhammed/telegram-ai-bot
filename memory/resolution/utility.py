from __future__ import annotations

from typing import Any, Mapping


_SOFT_COMMITMENTS = frozenset({"possible", "probable", "uncertain", "unknown"})
_SOFT_MODES = frozenset({"reported", "quoted", "inferred"})


def classify_utility(
    *,
    polarity: str,
    epistemic: Mapping[str, Any],
    has_provisional_identity: bool,
    is_correction: bool,
) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    # Meta correction assertions stay non-graph. Domain winners call with is_correction=False.
    if is_correction:
        reasons.append("correction_deferred")
        reasons.append("correction_lineage")
        return "deferred", tuple(reasons)
    if has_provisional_identity:
        reasons.append("provisional_identity")
        return "deferred", tuple(reasons)
    if polarity == "unknown":
        reasons.append("uncertain_claim")
        return "deferred", tuple(reasons)
    commitment = str(epistemic.get("speaker_commitment") or "")
    mode = str(epistemic.get("mode") or "")
    if commitment in _SOFT_COMMITMENTS or mode in _SOFT_MODES:
        reasons.append("uncertain_claim")
        return "deferred", tuple(reasons)
    if epistemic.get("needs_confirmation") is True:
        reasons.append("uncertain_claim")
        return "deferred", tuple(reasons)
    reasons.append("durable_fact")
    return "durable", tuple(reasons)
