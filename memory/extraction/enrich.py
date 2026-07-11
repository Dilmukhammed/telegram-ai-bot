from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from memory.extraction.schemas import EXTRACTION_SCHEMA_VERSION


_UNCERTAIN_COMMITMENTS = frozenset({"uncertain", "possible", "probable", "unknown"})


def is_slim_extraction_payload(payload: Mapping[str, Any]) -> bool:
    if payload.get("schema_version") != EXTRACTION_SCHEMA_VERSION:
        return True
    for mention in payload.get("mentions") or []:
        if isinstance(mention, Mapping) and "char_start" not in mention:
            return True
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        if "candidate_ref" not in candidate:
            return True
        for item in candidate.get("evidence") or []:
            if isinstance(item, Mapping) and "quote" in item and "exact_quote" not in item:
                return True
    return False


def enrich_extraction_payload(
    payload: Mapping[str, Any],
    *,
    segment_text: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    if not is_slim_extraction_payload(payload):
        return dict(payload)
    data = dict(payload)
    mentions_in = list(data.get("mentions") or [])
    candidates_in = list(data.get("candidates") or [])

    mentions_out: list[dict[str, Any]] = []
    surface_to_ref: dict[str, str] = {}
    for index, mention in enumerate(mentions_in):
        if not isinstance(mention, Mapping):
            raise ValueError(f"$.mentions[{index}]: must be an object")
        if "char_start" in mention and "char_end" in mention:
            mention_ref = str(mention.get("mention_ref") or f"m{index + 1}")
            surface = str(mention["surface_text"])
            hint = mention.get("normalized_hint")
            if hint is not None:
                hint = str(hint)
            mentions_out.append(
                {
                    "mention_ref": mention_ref,
                    "mention_type": mention["mention_type"],
                    "surface_text": surface,
                    "char_start": int(mention["char_start"]),
                    "char_end": int(mention["char_end"]),
                    "normalized_hint": hint,
                }
            )
            surface_to_ref[surface.casefold()] = mention_ref
            continue
        mention_ref = mention.get("mention_ref")
        if mention_ref is None:
            mention_ref = f"m{index + 1}"
        mention_ref = str(mention_ref)
        surface = str(mention["surface_text"])
        start, end = _find_span(segment_text, surface, f"$.mentions[{index}].surface_text")
        hint = mention.get("normalized_hint")
        if hint is not None:
            hint = str(hint)
        mentions_out.append(
            {
                "mention_ref": mention_ref,
                "mention_type": mention["mention_type"],
                "surface_text": surface,
                "char_start": start,
                "char_end": end,
                "normalized_hint": hint,
            }
        )
        surface_to_ref[surface.casefold()] = mention_ref

    mention_refs = {item["mention_ref"] for item in mentions_out}
    candidates_out: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates_in):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"$.candidates[{index}]: must be an object")
        candidate_ref = candidate.get("candidate_ref") or f"c{index + 1}"
        arguments = [
            _enrich_argument(item, arg_index, candidate_path=f"$.candidates[{index}]", surface_to_ref=surface_to_ref, mention_refs=mention_refs)
            for arg_index, item in enumerate(candidate.get("arguments") or [])
        ]
        epistemic = _enrich_epistemic(
            candidate.get("epistemic") or {},
            path=f"$.candidates[{index}].epistemic",
            surface_to_ref=surface_to_ref,
            mention_refs=mention_refs,
        )
        polarity = str(candidate["polarity"])
        status, needs_confirmation = _derive_status_and_confirmation(
            polarity=polarity,
            epistemic=epistemic,
        )
        epistemic["needs_confirmation"] = needs_confirmation
        if polarity != "unknown" and needs_confirmation:
            polarity = "unknown"
        temporal = _enrich_temporal(
            candidate,
            segment_text=segment_text,
            path=f"$.candidates[{index}]",
            timezone=timezone,
        )
        evidence = [
            _enrich_evidence(item, ev_index, segment_text=segment_text, path=f"$.candidates[{index}].evidence[{ev_index}]")
            for ev_index, item in enumerate(candidate.get("evidence") or [])
        ]
        candidates_out.append(
            {
                "candidate_ref": str(candidate_ref),
                "kind": candidate["kind"],
                "schema_name": candidate["schema_name"],
                "schema_version": EXTRACTION_SCHEMA_VERSION,
                "arguments": arguments,
                "attributes": {},
                "polarity": polarity,
                "epistemic": epistemic,
                "temporal": temporal,
                "status": status,
                "evidence": evidence,
                "canonical_hint": _build_canonical_hint(
                    str(candidate["schema_name"]),
                    arguments,
                ),
            }
        )

    abstain = bool(data.get("abstain", False))
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "abstain": abstain,
        "mentions": mentions_out,
        "candidates": candidates_out,
    }


def _enrich_argument(
    value: Any,
    index: int,
    *,
    candidate_path: str,
    surface_to_ref: dict[str, str],
    mention_refs: set[str],
) -> dict[str, Any]:
    path = f"{candidate_path}.arguments[{index}]"
    if not isinstance(value, Mapping):
        raise ValueError(f"{path}: must be an object")
    role = value["role"]
    if "literal" in value:
        return {"role": role, "literal": value["literal"]}
    if "mention_ref" in value:
        mention_ref = str(value["mention_ref"])
        if mention_ref not in mention_refs:
            raise ValueError(f"{path}.mention_ref: references an undeclared mention")
        return {"role": role, "mention_ref": mention_ref}
    if "mention_surface" in value:
        surface = str(value["mention_surface"])
        mention_ref = surface_to_ref.get(surface.casefold())
        if mention_ref is None:
            raise ValueError(f"{path}.mention_surface: references an undeclared mention")
        return {"role": role, "mention_ref": mention_ref}
    raise ValueError(f"{path}: exactly one of literal, mention_ref, or mention_surface is required")


def _enrich_epistemic(
    value: Mapping[str, Any],
    *,
    path: str,
    surface_to_ref: dict[str, str],
    mention_refs: set[str],
) -> dict[str, Any]:
    alternatives = list(value.get("alternatives") or [])
    speaker_raw = value.get("speaker_ref")
    speaker_ref: str | None
    if speaker_raw is None:
        speaker_ref = None
    else:
        speaker = str(speaker_raw)
        if speaker == "self":
            speaker_ref = "self"
        elif speaker in mention_refs:
            speaker_ref = speaker
        else:
            speaker_ref = surface_to_ref.get(speaker.casefold())
            if speaker_ref is None:
                raise ValueError(f"{path}.speaker_ref: references an undeclared mention")
    # Alternatives describe competing proposition values; they do not narrow
    # uncertainty to one already-selected argument.
    scope = "proposition"
    return {
        "mode": value["mode"],
        "speaker_commitment": value["speaker_commitment"],
        "scope": scope,
        "alternatives": alternatives,
        "speaker_ref": speaker_ref,
    }


def _derive_status_and_confirmation(
    *,
    polarity: str,
    epistemic: Mapping[str, Any],
) -> tuple[str, bool]:
    mode = str(epistemic["mode"])
    commitment = str(epistemic["speaker_commitment"])
    needs_confirmation = (
        polarity == "unknown"
        or commitment in _UNCERTAIN_COMMITMENTS
        or mode == "reported"
    )
    status = "needs_confirmation" if needs_confirmation else "proposed"
    return status, needs_confirmation


def _enrich_temporal(
    candidate: Mapping[str, Any],
    *,
    segment_text: str,
    path: str,
    timezone: str | None,
) -> dict[str, Any] | None:
    if "temporal" in candidate:
        return candidate["temporal"]  # full-format passthrough inside slim root
    cue = candidate.get("temporal_cue")
    if cue is None:
        return None
    cue_text = str(cue)
    _find_span(segment_text, cue_text, f"{path}.temporal_cue")
    return {
        "original_text": cue_text,
        "valid_from": None,
        "valid_to": None,
        "event_time": None,
        "precision": "second",
        "timezone": timezone,
    }


def _enrich_evidence(
    value: Any,
    index: int,
    *,
    segment_text: str,
    path: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path}: must be an object")
    quote = value.get("exact_quote")
    if quote is None:
        quote = value.get("quote")
    if quote is None:
        raise ValueError(f"{path}: quote or exact_quote is required")
    quote_text = str(quote)
    start, end = _find_span(segment_text, quote_text, path)
    return {
        "relation": value["relation"],
        "exact_quote": quote_text,
        "char_start": start,
        "char_end": end,
    }


def _build_canonical_hint(schema_name: str, arguments: list[dict[str, Any]]) -> str | None:
    parts = [schema_name]
    for argument in sorted(arguments, key=lambda item: str(item["role"])):
        if "literal" in argument:
            parts.append(str(argument["literal"]))
        elif "mention_ref" in argument:
            parts.append(str(argument["mention_ref"]))
    return ":".join(parts) if len(parts) > 1 else None


def _find_span(text: str, substring: str, path: str) -> tuple[int, int]:
    if not substring:
        raise ValueError(f"{path}: must be non-empty")
    if substring == text:
        return 0, len(text)
    start = 0
    positions: list[int] = []
    while True:
        index = text.find(substring, start)
        if index < 0:
            break
        positions.append(index)
        start = index + 1
    if not positions:
        raise ValueError(f"{path}: text not found in segment_text")
    if len(positions) > 1:
        raise ValueError(f"{path}: ambiguous span ({len(positions)} matches in segment_text)")
    index = positions[0]
    return index, index + len(substring)
