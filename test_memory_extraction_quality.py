from __future__ import annotations

import unittest

from memory.extraction.prompts import PROMPT_VERSION, build_extraction_messages
from memory.extraction.contracts import (
    candidate_contract_violations,
    normalize_candidate_contracts,
)
from memory.extraction.discourse import normalize_discourse, parse_cross_segment_ref
from memory.extraction.schemas import (
    CandidateArgument,
    CandidateDraft,
    CandidateStatus,
    Epistemic,
    EpistemicMode,
    EpistemicScope,
    EvidenceSpan,
    ExtractionResult,
    MentionDraft,
    Polarity,
    SpeakerCommitment,
    Temporal,
)
from memory.extraction.temporal import normalize_text_temporal


def _candidate(
    schema_name: str,
    kind: str,
    arguments: tuple[CandidateArgument, ...],
    *,
    polarity: Polarity = Polarity.POSITIVE,
    mode: EpistemicMode = EpistemicMode.ASSERTED,
    commitment: SpeakerCommitment = SpeakerCommitment.CERTAIN,
    temporal: Temporal | None = None,
) -> CandidateDraft:
    return CandidateDraft(
        candidate_ref="c1",
        kind=kind,
        schema_name=schema_name,
        schema_version="1",
        arguments=arguments,
        attributes={},
        polarity=polarity,
        epistemic=Epistemic(
            mode=mode,
            speaker_commitment=commitment,
            scope=EpistemicScope.PROPOSITION,
        ),
        temporal=temporal,
        status=CandidateStatus.PROPOSED,
        evidence=(EvidenceSpan("supports", "evidence", 0, 8),),
    )


def _result(candidate: CandidateDraft, *mentions: MentionDraft) -> ExtractionResult:
    return ExtractionResult("1", False, tuple(mentions), (candidate,))


class FreeFieldContractTests(unittest.TestCase):
    def test_extraction_prompt_canonicalizes_only_obvious_literal_typos(self) -> None:
        messages = build_extraction_messages(
            segment_text="я люблю пицы",
            source_type="chat_message",
            authority_class="user_direct_statement",
            occurred_at=None,
            timezone="Asia/Tashkent",
        )
        system_prompt = messages[0]["content"]
        self.assertEqual(PROMPT_VERSION, "text_candidates_v8")
        self.assertIn('literal "пицца"', system_prompt)
        self.assertIn("evidence quote", system_prompt)
        self.assertIn("Never guess", system_prompt)

    def test_contracts_are_pass_through(self) -> None:
        candidate = _candidate(
            "quest_completed",
            "game_progress",
            (
                CandidateArgument("player", literal="self", has_literal=True),
                CandidateArgument("quest", literal="intro", has_literal=True),
            ),
        )
        normalized = normalize_candidate_contracts(_result(candidate))
        self.assertEqual(normalized.candidates[0].schema_name, "quest_completed")
        self.assertEqual(
            [item.role for item in normalized.candidates[0].arguments],
            ["player", "quest"],
        )
        self.assertEqual(candidate_contract_violations(normalized), [])

    def test_discourse_is_pass_through(self) -> None:
        candidate = _candidate(
            "prefers",
            "preference",
            (
                CandidateArgument("subject", literal="self", has_literal=True),
                CandidateArgument("value", literal="tea", has_literal=True),
            ),
        )
        result = _result(candidate)
        normalized = normalize_discourse(
            result,
            segment_text="Do I like tea?",
            prior_segments=(),
        )
        self.assertEqual(normalized, result)

    def test_cross_segment_ref_helpers(self) -> None:
        ref = "seg_1"
        value = f"$seg:{ref}:person"
        self.assertEqual(parse_cross_segment_ref(value), (ref, "person"))
        self.assertIsNone(parse_cross_segment_ref("not-a-ref"))


class TemporalNormalizerTests(unittest.TestCase):
    def test_weekend_preference_clears_temporal(self) -> None:
        candidate = _candidate(
            "likes_activity",
            "preference",
            (
                CandidateArgument("subject", literal="self", has_literal=True),
                CandidateArgument("activity", literal="hiking", has_literal=True),
            ),
            temporal=Temporal("on weekends", None, None, None, "day", "UTC"),
        )
        result = normalize_text_temporal(
            _result(candidate),
            segment_text="I hike on weekends",
            occurred_at="2026-01-01T12:00:00+00:00",
            timezone="UTC",
        )
        self.assertIsNone(result.candidates[0].temporal)


if __name__ == "__main__":
    unittest.main()
