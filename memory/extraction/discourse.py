from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Sequence

from memory.extraction.schemas import (
    CandidateArgument,
    CandidateDraft,
    CandidateKind,
    CandidateStatus,
    Epistemic,
    EpistemicMode,
    EpistemicScope,
    EvidenceSpan,
    ExtractionResult,
    MentionDraft,
    MentionType,
    Polarity,
    SpeakerCommitment,
)


_PRONOUNS = frozenset({"he", "she", "он", "она"})


def normalize_discourse(
    result: ExtractionResult,
    *,
    segment_text: str,
    prior_segments: Sequence[Any],
) -> ExtractionResult:
    if _is_question(segment_text):
        return replace(result, abstain=True, mentions=(), candidates=())
    result = _bootstrap_introduction_mention(result, segment_text=segment_text)
    result = _normalize_direct_quote(result, segment_text=segment_text)
    result = _normalize_inference(result, segment_text=segment_text)
    result = _bootstrap_generic_place(result, segment_text=segment_text)
    result = _normalize_inflected_mentions(result, segment_text=segment_text)
    result = _normalize_quoted_document_mentions(result)
    result = _normalize_literal_argument_policy(result, segment_text=segment_text)
    result = _normalize_relation_orientation(
        result,
        segment_text=segment_text,
        prior_segments=prior_segments,
    )
    result = _synthesize_explicit_task(result, segment_text=segment_text)
    result = _normalize_evidence_relations(result)
    return replace(result, abstain=not result.candidates)


def cross_segment_ref(segment_id: str, mention_type: str) -> str:
    return f"$seg:{segment_id}:{mention_type}"


def parse_cross_segment_ref(value: str) -> tuple[str, str] | None:
    if not value.startswith("$seg:"):
        return None
    body = value[len("$seg:") :]
    segment_id, separator, mention_type = body.rpartition(":")
    if not separator or not segment_id or not mention_type:
        return None
    return segment_id, mention_type


def _is_question(text: str) -> bool:
    stripped = text.strip()
    return stripped.endswith("?") or stripped.endswith("？")


def _bootstrap_introduction_mention(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    match = re.search(
        r"\bthis\s+is\s+([A-Z][\w'-]+)",
        segment_text,
        re.IGNORECASE,
    )
    normalized: str | None = None
    if match is None:
        match = re.search(
            r"\bпознакомься\s+с\s+([А-ЯЁ][а-яё-]+)",
            segment_text,
            re.IGNORECASE,
        )
        if match is not None:
            surface = match.group(1)
            normalized = surface[:-2] + "а" if surface.casefold().endswith("ой") else surface
    if match is None:
        return result
    surface = match.group(1)
    start, end = match.span(1)
    mentions = list(result.mentions)
    if not any(item.char_start == start and item.char_end == end for item in mentions):
        mentions.append(
            MentionDraft(
                mention_ref="introduced_person",
                mention_type=MentionType.PERSON,
                surface_text=surface,
                char_start=start,
                char_end=end,
                normalized_hint=normalized or surface,
            )
        )
    candidates = tuple(item for item in result.candidates if item.schema_name != "name")
    return replace(result, mentions=tuple(mentions), candidates=candidates)


def _normalize_direct_quote(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    if not any(mark in segment_text for mark in ('"', "“", "”", "«", "»")):
        return result
    match = re.match(
        r"\s*(?P<speaker>[A-ZА-ЯЁ][\w'-]*)\s+"
        r"(?:said|says|сказал|сказала|говорит)\b",
        segment_text,
        re.IGNORECASE,
    )
    if match is None:
        return result
    speaker_surface = match.group("speaker")
    speaker = next(
        (
            mention
            for mention in result.mentions
            if mention.mention_type is MentionType.PERSON
            and mention.surface_text.casefold() == speaker_surface.casefold()
        ),
        None,
    )
    if speaker is None:
        start, end = match.span("speaker")
        speaker = MentionDraft(
            mention_ref="quoted_speaker",
            mention_type=MentionType.PERSON,
            surface_text=speaker_surface,
            char_start=start,
            char_end=end,
            normalized_hint=speaker_surface,
        )
        mentions = (*result.mentions, speaker)
    else:
        mentions = result.mentions
    folded = segment_text.casefold()
    explicit_negative = any(marker in folded for marker in (" hate ", "ненавиж", "не люблю"))
    explicit_positive = any(marker in folded for marker in (" love ", " like ", "люблю"))
    candidates = []
    for candidate in result.candidates:
        arguments = list(candidate.arguments)
        subject_index = next(
            (index for index, item in enumerate(arguments) if item.role in {"subject", "person"}),
            None,
        )
        if subject_index is not None:
            role = arguments[subject_index].role
            arguments[subject_index] = CandidateArgument(
                role=role,
                mention_ref=speaker.mention_ref,
                has_literal=False,
            )
        polarity = candidate.polarity
        if explicit_negative:
            polarity = Polarity.NEGATIVE
        elif explicit_positive:
            polarity = Polarity.POSITIVE
        candidates.append(
            replace(
                candidate,
                arguments=tuple(arguments),
                polarity=polarity,
                epistemic=replace(
                    candidate.epistemic,
                    mode=EpistemicMode.QUOTED,
                    speaker_commitment=SpeakerCommitment.CERTAIN,
                    needs_confirmation=False,
                    speaker_ref=speaker.mention_ref,
                ),
                status=CandidateStatus.PROPOSED,
            )
        )
    return replace(result, mentions=tuple(mentions), candidates=tuple(candidates))


def _normalize_inference(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    folded = f" {segment_text.casefold()} "
    if not any(marker in folded for marker in (" похоже", " seems ", " appears ", " apparently ")):
        return result
    candidates = tuple(
        replace(
            candidate,
            polarity=Polarity.UNKNOWN,
            epistemic=replace(
                candidate.epistemic,
                mode=EpistemicMode.INFERRED,
                speaker_commitment=SpeakerCommitment.PROBABLE,
                needs_confirmation=True,
            ),
            status=CandidateStatus.NEEDS_CONFIRMATION,
            temporal=None
            if candidate.temporal is not None
            and (candidate.temporal.original_text or "").casefold() in {"уже", "already"}
            else candidate.temporal,
        )
        for candidate in result.candidates
    )
    return replace(result, candidates=candidates)


def _bootstrap_generic_place(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    if not any(candidate.schema_name == "located_at" for candidate in result.candidates):
        return result
    match = re.search(r"\b(офис(?:е|а|у|ом)?|office)\b", segment_text, re.IGNORECASE)
    if match is None:
        return result
    surface = match.group(1)
    place = next(
        (
            mention
            for mention in result.mentions
            if mention.mention_type is MentionType.PLACE
            and mention.char_start == match.start(1)
            and mention.char_end == match.end(1)
        ),
        None,
    )
    mentions = list(result.mentions)
    if place is None:
        place = MentionDraft(
            mention_ref="generic_place",
            mention_type=MentionType.PLACE,
            surface_text=surface,
            char_start=match.start(1),
            char_end=match.end(1),
            normalized_hint="офис" if surface.casefold().startswith("офис") else "office",
        )
        mentions.append(place)
    candidates = []
    for candidate in result.candidates:
        if candidate.schema_name != "located_at":
            candidates.append(candidate)
            continue
        arguments = tuple(
            CandidateArgument(role="place", mention_ref=place.mention_ref, has_literal=False)
            if argument.role == "place"
            else argument
            for argument in candidate.arguments
        )
        candidates.append(replace(candidate, arguments=arguments))
    return replace(result, mentions=tuple(mentions), candidates=tuple(candidates))


def _normalize_relation_orientation(
    result: ExtractionResult,
    *,
    segment_text: str,
    prior_segments: Sequence[Any],
) -> ExtractionResult:
    folded = segment_text.casefold().strip()
    pronoun_match = re.match(r"(he|she|он|она)\b", folded)
    current_people = [
        mention
        for mention in result.mentions
        if mention.mention_type is MentionType.PERSON
    ]
    mentions = [
        replace(mention, normalized_hint=mention.surface_text)
        if mention.surface_text.casefold() in _PRONOUNS
        else mention
        for mention in result.mentions
    ]
    if pronoun_match is not None and not any(
        mention.surface_text.casefold() in _PRONOUNS for mention in current_people
    ):
        surface = segment_text[pronoun_match.start() : pronoun_match.end()]
        mentions.append(
            MentionDraft(
                mention_ref="coref_pronoun",
                mention_type=MentionType.PERSON,
                surface_text=surface,
                char_start=pronoun_match.start(),
                char_end=pronoun_match.end(),
                normalized_hint=surface,
            )
        )
    candidates = []
    for candidate in result.candidates:
        if candidate.schema_name == "name" and pronoun_match is not None:
            continue
        if candidate.schema_name == "sibling_of":
            if pronoun_match is not None and prior_segments:
                prior = prior_segments[-1]
                arguments = (
                    CandidateArgument(
                        role="person",
                        mention_ref=cross_segment_ref(prior.segment_id, "person"),
                        has_literal=False,
                    ),
                    CandidateArgument(role="related_to", literal="self", has_literal=True),
                )
                candidate = replace(candidate, arguments=arguments)
            elif "my sister" in folded or "my brother" in folded:
                person = next(
                    (
                        mention
                        for mention in current_people
                        if mention.surface_text.casefold() not in _PRONOUNS
                    ),
                    None,
                )
                if person is not None:
                    candidate = replace(
                        candidate,
                        arguments=(
                            CandidateArgument(
                                role="person",
                                mention_ref=person.mention_ref,
                                has_literal=False,
                            ),
                            CandidateArgument(role="related_to", literal="self", has_literal=True),
                        ),
                    )
        elif candidate.schema_name == "manager_of" and pronoun_match is not None and prior_segments:
            prior = prior_segments[-1]
            candidate = replace(
                candidate,
                arguments=(
                    CandidateArgument(
                        role="manager",
                        mention_ref=cross_segment_ref(prior.segment_id, "person"),
                        has_literal=False,
                    ),
                    CandidateArgument(role="report", literal="self", has_literal=True),
                ),
            )
        candidates.append(candidate)
    if pronoun_match is not None and prior_segments:
        prior = prior_segments[-1]
        if "my manager" in folded and not any(
            item.schema_name == "manager_of" for item in candidates
        ):
            candidates.append(
                _coreference_candidate(
                    schema_name="manager_of",
                    arguments=(
                        CandidateArgument(
                            role="manager",
                            mention_ref=cross_segment_ref(prior.segment_id, "person"),
                            has_literal=False,
                        ),
                        CandidateArgument(role="report", literal="self", has_literal=True),
                    ),
                    segment_text=segment_text,
                )
            )
        if any(marker in folded for marker in ("моя сестра", "мой брат")) and not any(
            item.schema_name == "sibling_of" for item in candidates
        ):
            candidates.append(
                _coreference_candidate(
                    schema_name="sibling_of",
                    arguments=(
                        CandidateArgument(
                            role="person",
                            mention_ref=cross_segment_ref(prior.segment_id, "person"),
                            has_literal=False,
                        ),
                        CandidateArgument(
                            role="related_to",
                            literal="self",
                            has_literal=True,
                        ),
                    ),
                    segment_text=segment_text,
                )
            )
    return replace(result, mentions=tuple(mentions), candidates=tuple(candidates))


def _normalize_inflected_mentions(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    mentions = []
    for mention in result.mentions:
        end = mention.char_end
        while end < len(segment_text) and (
            segment_text[end].isalpha() or segment_text[end] in {"-", "’", "'"}
        ):
            end += 1
        if end == mention.char_end:
            mentions.append(mention)
            continue
        mentions.append(
            replace(
                mention,
                surface_text=segment_text[mention.char_start:end],
                char_end=end,
                normalized_hint=mention.normalized_hint or mention.surface_text,
            )
        )
    return replace(result, mentions=tuple(mentions))


def _normalize_quoted_document_mentions(result: ExtractionResult) -> ExtractionResult:
    quote_pairs = {("«", "»"), ('"', '"'), ("“", "”")}
    mentions = []
    for mention in result.mentions:
        if mention.mention_type is not MentionType.DOCUMENT or len(mention.surface_text) < 2:
            mentions.append(mention)
            continue
        pair = (mention.surface_text[0], mention.surface_text[-1])
        if pair not in quote_pairs:
            mentions.append(mention)
            continue
        surface = mention.surface_text[1:-1]
        mentions.append(
            replace(
                mention,
                surface_text=surface,
                char_start=mention.char_start + 1,
                char_end=mention.char_end - 1,
                normalized_hint=surface,
            )
        )
    return replace(result, mentions=tuple(mentions))


def _normalize_literal_argument_policy(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    mentions = list(result.mentions)
    mentions_by_ref = {mention.mention_ref: mention for mention in mentions}
    converted_refs: set[str] = set()
    candidates = []
    for candidate in result.candidates:
        arguments = []
        for argument in candidate.arguments:
            mention = (
                mentions_by_ref.get(argument.mention_ref)
                if argument.mention_ref is not None
                else None
            )
            if candidate.schema_name == "name" and argument.role == "value" and mention is not None:
                arguments.append(
                    CandidateArgument(
                        role="value",
                        literal=mention.surface_text,
                        has_literal=True,
                    )
                )
                converted_refs.add(mention.mention_ref)
                continue
            if (
                candidate.schema_name == "call_person"
                and argument.role == "target"
                and mention is not None
                and mention.surface_text.casefold() in {"врач", "врача", "врачу", "доктор", "доктору"}
            ):
                arguments.append(
                    CandidateArgument(role="target", literal="doctor", has_literal=True)
                )
                converted_refs.add(mention.mention_ref)
                continue
            arguments.append(argument)
        if candidate.schema_name == "left_job" and not any(
            item.role == "organization" for item in arguments
        ):
            organization = next(
                (
                    mention
                    for mention in mentions
                    if mention.mention_type is MentionType.ORGANIZATION
                ),
                None,
            )
            if organization is not None:
                arguments.append(
                    CandidateArgument(
                        role="organization",
                        mention_ref=organization.mention_ref,
                        has_literal=False,
                    )
                )
        if candidate.schema_name == "favorite_book":
            for index, argument in enumerate(arguments):
                if argument.role != "book" or not argument.has_literal:
                    continue
                title = str(argument.literal)
                start = segment_text.find(title)
                if start < 0:
                    continue
                document = next(
                    (
                        mention
                        for mention in mentions
                        if mention.mention_type is MentionType.DOCUMENT
                        and mention.char_start == start
                        and mention.char_end == start + len(title)
                    ),
                    None,
                )
                if document is None:
                    document = MentionDraft(
                        mention_ref="favorite_book",
                        mention_type=MentionType.DOCUMENT,
                        surface_text=title,
                        char_start=start,
                        char_end=start + len(title),
                        normalized_hint=title,
                    )
                    mentions.append(document)
                    mentions_by_ref[document.mention_ref] = document
                arguments[index] = CandidateArgument(
                    role="book",
                    mention_ref=document.mention_ref,
                    has_literal=False,
                )
        candidates.append(replace(candidate, arguments=tuple(arguments)))
    referenced = {
        argument.mention_ref
        for candidate in candidates
        for argument in candidate.arguments
        if argument.mention_ref is not None
    }
    referenced.update(
        candidate.epistemic.speaker_ref
        for candidate in candidates
        if candidate.epistemic.speaker_ref is not None
    )
    retained_mentions = tuple(
        mention
        for mention in mentions
        if mention.mention_ref not in converted_refs or mention.mention_ref in referenced
    )
    return replace(result, mentions=retained_mentions, candidates=tuple(candidates))


def _coreference_candidate(
    *,
    schema_name: str,
    arguments: tuple[CandidateArgument, ...],
    segment_text: str,
) -> CandidateDraft:
    return CandidateDraft(
        candidate_ref="coref_relation",
        kind=CandidateKind.RELATION,
        schema_name=schema_name,
        schema_version="1",
        arguments=arguments,
        attributes={},
        polarity=Polarity.POSITIVE,
        epistemic=Epistemic(
            mode=EpistemicMode.ASSERTED,
            speaker_commitment=SpeakerCommitment.CERTAIN,
            scope=EpistemicScope.PROPOSITION,
        ),
        temporal=None,
        status=CandidateStatus.PROPOSED,
        evidence=(
            EvidenceSpan(
                relation="supports_coreference",
                exact_quote=segment_text,
                char_start=0,
                char_end=len(segment_text),
            ),
        ),
    )


def _synthesize_explicit_task(
    result: ExtractionResult,
    *,
    segment_text: str,
) -> ExtractionResult:
    folded = segment_text.casefold()
    if not any(marker in folded for marker in ("renew my passport", "обновить паспорт")):
        return result
    if any(candidate.schema_name == "renew_passport" for candidate in result.candidates):
        return result
    candidate = CandidateDraft(
        candidate_ref="renew_passport",
        kind=CandidateKind.TASK,
        schema_name="renew_passport",
        schema_version="1",
        arguments=(CandidateArgument("subject", literal="self", has_literal=True),),
        attributes={},
        polarity=Polarity.POSITIVE,
        epistemic=Epistemic(
            mode=EpistemicMode.ASSERTED,
            speaker_commitment=SpeakerCommitment.CERTAIN,
            scope=EpistemicScope.PROPOSITION,
        ),
        temporal=None,
        status=CandidateStatus.PROPOSED,
        evidence=(EvidenceSpan("supports", segment_text, 0, len(segment_text)),),
    )
    return replace(result, candidates=(*result.candidates, candidate), abstain=False)


def _normalize_evidence_relations(result: ExtractionResult) -> ExtractionResult:
    candidates = []
    for candidate in result.candidates:
        if candidate.schema_name != "destination_choice":
            candidates.append(candidate)
            continue
        evidence = tuple(replace(item, relation="supports") for item in candidate.evidence)
        candidates.append(replace(candidate, evidence=evidence))
    return replace(result, candidates=tuple(candidates))
