from __future__ import annotations

import json
from typing import Any, Mapping

from memory.summaries.schemas import SummaryDraft, SummarySentence


class SummaryParseError(ValueError):
    pass


def parse_summary_output(raw: str) -> SummaryDraft:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SummaryParseError(f"invalid summary json: {exc}") from exc
    if not isinstance(payload, dict):
        raise SummaryParseError("summary output must be an object")
    sentences_raw = payload.get("sentences")
    if not isinstance(sentences_raw, list) or not sentences_raw:
        raise SummaryParseError("summary output requires non-empty sentences")
    sentences: list[SummarySentence] = []
    support: dict[str, tuple[str, ...]] = {}
    belief_ids: set[str] = set()
    for index, item in enumerate(sentences_raw):
        if not isinstance(item, dict):
            raise SummaryParseError(f"sentence {index} must be an object")
        text = str(item.get("text") or "").strip()
        if not text:
            raise SummaryParseError(f"sentence {index} text is empty")
        ids_raw = item.get("belief_ids")
        if not isinstance(ids_raw, list) or not ids_raw:
            raise SummaryParseError(f"sentence {index} requires belief_ids")
        ids = tuple(str(x) for x in ids_raw if str(x).strip())
        if not ids:
            raise SummaryParseError(f"sentence {index} requires belief_ids")
        sentences.append(SummarySentence(text=text, belief_ids=ids))
        support[str(index)] = ids
        belief_ids.update(ids)
    content = " ".join(s.text for s in sentences)
    return SummaryDraft(
        sentences=tuple(sentences),
        content=content,
        belief_ids=tuple(sorted(belief_ids)),
        sentence_support=support,
    )


def draft_from_mapping(payload: Mapping[str, Any]) -> SummaryDraft:
    raw = json.dumps(payload)
    return parse_summary_output(raw)
