from __future__ import annotations

from memory.summaries.schemas import BeliefSnapshot, SummaryDraft


def run_preflight(
    draft: SummaryDraft,
    *,
    input_beliefs: tuple[BeliefSnapshot, ...],
) -> tuple[bool, str | None]:
    allowed = {b.belief_id for b in input_beliefs}
    status_by_id = {b.belief_id: b.belief_status for b in input_beliefs}
    if not draft.sentences:
        return False, "empty_sentences"
    for index, sentence in enumerate(draft.sentences):
        if not sentence.belief_ids:
            return False, f"sentence_{index}_missing_belief_ids"
        for belief_id in sentence.belief_ids:
            if belief_id not in allowed:
                return False, f"sentence_{index}_unknown_belief:{belief_id}"
        support = draft.sentence_support.get(str(index), sentence.belief_ids)
        if not support:
            return False, f"sentence_{index}_missing_support"
        if _claims_current_fact(sentence.text):
            for belief_id in sentence.belief_ids:
                status = status_by_id.get(belief_id, "")
                if status in {"historical", "expired"}:
                    return False, f"sentence_{index}_stale_as_current"
    return True, None


def exact_support_match(
    sentence_text: str,
    beliefs: tuple[BeliefSnapshot, ...],
    *,
    cited_ids: tuple[str, ...],
) -> bool:
    normalized = sentence_text.strip().casefold()
    for belief in beliefs:
        if belief.belief_id not in cited_ids:
            continue
        if normalized == belief.statement.casefold():
            return True
        if belief.statement.casefold() in normalized:
            return True
    return False


def _claims_current_fact(text: str) -> bool:
    lowered = text.casefold()
    if "uncertain" in lowered or "maybe" in lowered or "?" in text:
        return False
    if any(token in lowered for token in ("was ", "used to", "formerly", "historical")):
        return False
    return True
