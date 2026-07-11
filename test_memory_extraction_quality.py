from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from memory.extraction.contracts import (
    candidate_contract_violations,
    normalize_candidate_contracts,
)
from memory.extraction.discourse import normalize_discourse, parse_cross_segment_ref
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
    Temporal,
)
from memory.extraction.temporal import normalize_text_temporal


def _candidate(
    schema_name: str,
    kind: CandidateKind,
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


class CandidateContractTests(unittest.TestCase):
    def test_role_aliases_and_literals_are_canonicalized(self) -> None:
        candidate = _candidate(
            "likes_activity",
            CandidateKind.PREFERENCE,
            (
                CandidateArgument("subject", literal="self", has_literal=True),
                CandidateArgument("value", literal="hiking", has_literal=True),
            ),
        )
        normalized = normalize_candidate_contracts(_result(candidate))
        self.assertEqual(
            [item.role for item in normalized.candidates[0].arguments],
            ["subject", "activity"],
        )
        self.assertEqual(candidate_contract_violations(normalized), [])

    def test_budget_and_russian_ontology_literals_are_normalized(self) -> None:
        budget = _candidate(
            "budget_limit",
            CandidateKind.PREFERENCE,
            (
                CandidateArgument("subject", literal="self", has_literal=True),
                CandidateArgument("value", literal="150 dollars per night", has_literal=True),
            ),
        )
        normalized = normalize_candidate_contracts(_result(budget)).candidates[0]
        self.assertEqual(normalized.arguments[1].role, "amount")
        self.assertEqual(normalized.arguments[1].literal, 150)

    def test_russian_destination_alternatives_are_canonicalized(self) -> None:
        candidate = _candidate(
            "destination_choice",
            CandidateKind.PREFERENCE,
            (CandidateArgument("subject", literal="self", has_literal=True),),
        )
        candidate = replace(
            candidate,
            epistemic=Epistemic(
                mode=EpistemicMode.ASSERTED,
                speaker_commitment=SpeakerCommitment.UNCERTAIN,
                scope=EpistemicScope.PROPOSITION,
                alternatives=("Лондон", "Париж"),
                needs_confirmation=True,
            ),
        )
        normalized = normalize_candidate_contracts(_result(candidate)).candidates[0]
        self.assertEqual(normalized.epistemic.alternatives, ("London", "Paris"))


class TemporalResolverTests(unittest.TestCase):
    occurred_at = "2026-07-10T09:00:00+05:00"
    timezone = "Asia/Tashkent"

    def _resolve(self, text: str, candidate: CandidateDraft) -> Temporal | None:
        return normalize_text_temporal(
            _result(candidate),
            segment_text=text,
            occurred_at=self.occurred_at,
            timezone=self.timezone,
        ).candidates[0].temporal

    def test_next_spring_range(self) -> None:
        temporal = self._resolve(
            "I want to run a marathon next spring.",
            _candidate(
                "run_marathon",
                CandidateKind.GOAL,
                (CandidateArgument("subject", literal="self", has_literal=True),),
            ),
        )
        self.assertEqual(temporal.original_text, "next spring")
        self.assertEqual(temporal.valid_from, "2027-03-01T00:00:00+05:00")
        self.assertEqual(temporal.valid_to, "2027-05-31T23:59:59+05:00")

    def test_weekday_deadline_uses_embedded_time(self) -> None:
        temporal = self._resolve(
            "The demo must be ready by 9 AM Monday.",
            _candidate(
                "prepare_demo",
                CandidateKind.TASK,
                (CandidateArgument("subject", literal="self", has_literal=True),),
            ),
        )
        self.assertEqual(temporal.original_text, "by Monday")
        self.assertEqual(temporal.valid_to, "2026-07-13T09:00:00+05:00")
        self.assertIsNone(temporal.event_time)

    def test_russian_tomorrow_event(self) -> None:
        temporal = self._resolve(
            "Завтра в 09:00 нужно позвонить врачу.",
            _candidate(
                "call_person",
                CandidateKind.TASK,
                (
                    CandidateArgument("subject", literal="self", has_literal=True),
                    CandidateArgument("target", literal="врачу", has_literal=True),
                ),
            ),
        )
        self.assertEqual(temporal.original_text, "Завтра")
        self.assertEqual(temporal.event_time, "2026-07-11T09:00:00+05:00")

    def test_correction_gets_valid_from(self) -> None:
        temporal = self._resolve(
            "Correction: I moved to Prague.",
            _candidate(
                "corrects_residence",
                CandidateKind.CORRECTION,
                (
                    CandidateArgument("subject", literal="self", has_literal=True),
                    CandidateArgument("old", literal="Berlin", has_literal=True),
                    CandidateArgument("new", literal="Prague", has_literal=True),
                ),
            ),
        )
        self.assertEqual(temporal.original_text, "moved")
        self.assertEqual(temporal.valid_from, self.occurred_at)


class DiscourseNormalizerTests(unittest.TestCase):
    def test_question_forces_full_abstention(self) -> None:
        candidate = _candidate(
            "lives_in",
            CandidateKind.RELATION,
            (
                CandidateArgument("person", literal="self", has_literal=True),
                CandidateArgument("place", literal="Seattle", has_literal=True),
            ),
        )
        normalized = normalize_discourse(
            _result(candidate),
            segment_text="Do I live in Seattle?",
            prior_segments=(),
        )
        self.assertTrue(normalized.abstain)
        self.assertEqual(normalized.mentions, ())
        self.assertEqual(normalized.candidates, ())

    def test_direct_quote_restores_speaker_and_modality(self) -> None:
        jordan = MentionDraft("jordan", MentionType.PERSON, "Jordan", 0, 6, None)
        candidate = _candidate(
            "likes_flying",
            CandidateKind.PREFERENCE,
            (CandidateArgument("subject", literal="self", has_literal=True),),
            polarity=Polarity.UNKNOWN,
            mode=EpistemicMode.REPORTED,
            commitment=SpeakerCommitment.POSSIBLE,
        )
        normalized = normalize_discourse(
            _result(candidate, jordan),
            segment_text="Jordan said, “I hate flying.”",
            prior_segments=(),
        ).candidates[0]
        self.assertEqual(normalized.arguments[0].mention_ref, "jordan")
        self.assertEqual(normalized.polarity, Polarity.NEGATIVE)
        self.assertEqual(normalized.epistemic.mode, EpistemicMode.QUOTED)
        self.assertEqual(normalized.epistemic.speaker_ref, "jordan")

    def test_inferred_location_bootstraps_office_mention(self) -> None:
        anna = MentionDraft("anna", MentionType.PERSON, "Анна", 8, 12, None)
        candidate = _candidate(
            "located_at",
            CandidateKind.STATE,
            (
                CandidateArgument("person", mention_ref="anna"),
                CandidateArgument("place", literal="офис", has_literal=True),
            ),
            polarity=Polarity.UNKNOWN,
            commitment=SpeakerCommitment.PROBABLE,
            temporal=Temporal("уже", None, None, None, "second", "Asia/Tashkent"),
        )
        result = normalize_discourse(
            _result(candidate, anna),
            segment_text="Похоже, Анна уже в офисе.",
            prior_segments=(),
        )
        self.assertEqual(result.candidates[0].epistemic.mode, EpistemicMode.INFERRED)
        self.assertIsNone(result.candidates[0].temporal)
        self.assertEqual(result.candidates[0].arguments[1].mention_ref, "generic_place")
        self.assertEqual(result.mentions[1].surface_text, "офисе")

    def test_pronoun_relation_uses_cross_segment_person(self) -> None:
        candidate = _candidate(
            "manager_of",
            CandidateKind.RELATION,
            (
                CandidateArgument("manager", literal="self", has_literal=True),
                CandidateArgument("report", literal="He", has_literal=True),
            ),
        )
        prior = SimpleNamespace(segment_id="prior-1")
        result = normalize_discourse(
            _result(candidate),
            segment_text="He is my manager.",
            prior_segments=(prior,),
        )
        reference = result.candidates[0].arguments[0].mention_ref
        self.assertEqual(parse_cross_segment_ref(reference), ("prior-1", "person"))
        self.assertEqual(result.candidates[0].arguments[1].literal, "self")

    def test_introduction_keeps_mention_but_drops_name_candidate(self) -> None:
        candidate = _candidate(
            "name",
            CandidateKind.ENTITY_ATTRIBUTE,
            (
                CandidateArgument("subject", literal="self", has_literal=True),
                CandidateArgument("value", literal="Daniel", has_literal=True),
            ),
        )
        result = normalize_discourse(
            _result(candidate),
            segment_text="This is Daniel.",
            prior_segments=(),
        )
        self.assertTrue(result.abstain)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.mentions[0].surface_text, "Daniel")

    def test_empty_pronoun_result_synthesizes_relation(self) -> None:
        empty = ExtractionResult("1", True, (), ())
        prior = SimpleNamespace(segment_id="prior-1")
        result = normalize_discourse(
            empty,
            segment_text="Она моя сестра.",
            prior_segments=(prior,),
        )
        self.assertFalse(result.abstain)
        self.assertEqual(result.candidates[0].schema_name, "sibling_of")
        self.assertEqual(result.mentions[0].surface_text, "Она")

    def test_inflected_place_span_is_expanded(self) -> None:
        place = MentionDraft("place", MentionType.PLACE, "Ташкент", 14, 21, None)
        maria = MentionDraft("maria", MentionType.PERSON, "Мария", 0, 5, None)
        candidate = _candidate(
            "lives_in",
            CandidateKind.RELATION,
            (
                CandidateArgument("person", mention_ref="maria"),
                CandidateArgument("place", mention_ref="place"),
            ),
        )
        result = normalize_discourse(
            _result(candidate, maria, place),
            segment_text="Мария живёт в Ташкенте.",
            prior_segments=(),
        )
        self.assertEqual(result.mentions[1].surface_text, "Ташкенте")
        self.assertEqual(result.mentions[1].char_end, 22)

    def test_generic_doctor_mention_becomes_literal(self) -> None:
        doctor = MentionDraft("doctor", MentionType.PERSON, "врач", 31, 35, None)
        candidate = _candidate(
            "call_person",
            CandidateKind.TASK,
            (
                CandidateArgument("subject", literal="self", has_literal=True),
                CandidateArgument("target", mention_ref="doctor"),
            ),
        )
        result = normalize_discourse(
            _result(candidate, doctor),
            segment_text="Завтра в 09:00 нужно позвонить врачу.",
            prior_segments=(),
        )
        self.assertEqual(result.mentions, ())
        self.assertEqual(result.candidates[0].arguments[1].literal, "doctor")

    def test_reported_left_job_links_available_organization(self) -> None:
        reporter = MentionDraft("reporter", MentionType.PERSON, "A coworker", 0, 10, None)
        priya = MentionDraft("priya", MentionType.PERSON, "Priya", 18, 23, None)
        acme = MentionDraft("acme", MentionType.ORGANIZATION, "Acme", 29, 33, None)
        candidate = _candidate(
            "left_job",
            CandidateKind.EVENT,
            (CandidateArgument("person", mention_ref="priya"),),
            polarity=Polarity.UNKNOWN,
            mode=EpistemicMode.REPORTED,
            commitment=SpeakerCommitment.POSSIBLE,
        )
        result = normalize_discourse(
            _result(candidate, reporter, priya, acme),
            segment_text="A coworker thinks Priya left Acme.",
            prior_segments=(),
        )
        self.assertEqual(result.candidates[0].arguments[1].role, "organization")
        self.assertEqual(result.candidates[0].arguments[1].mention_ref, "acme")

    def test_favorite_book_literal_becomes_document_mention(self) -> None:
        candidate = _candidate(
            "favorite_book",
            CandidateKind.PREFERENCE,
            (
                CandidateArgument("subject", literal="self", has_literal=True),
                CandidateArgument(
                    "book",
                    literal="Мастер и Маргарита",
                    has_literal=True,
                ),
            ),
        )
        result = normalize_discourse(
            _result(candidate),
            segment_text="My favorite book is «Мастер и Маргарита».",
            prior_segments=(),
        )
        self.assertEqual(result.mentions[0].mention_type, MentionType.DOCUMENT)
        self.assertEqual(result.mentions[0].surface_text, "Мастер и Маргарита")
        self.assertEqual(result.candidates[0].arguments[1].mention_ref, "favorite_book")

    def test_quoted_document_mention_excludes_quote_marks(self) -> None:
        document = MentionDraft(
            "book",
            MentionType.DOCUMENT,
            "«Мастер и Маргарита»",
            20,
            40,
            None,
        )
        candidate = _candidate(
            "favorite_book",
            CandidateKind.PREFERENCE,
            (
                CandidateArgument("subject", literal="self", has_literal=True),
                CandidateArgument("book", mention_ref="book"),
            ),
        )
        result = normalize_discourse(
            _result(candidate, document),
            segment_text="My favorite book is «Мастер и Маргарита».",
            prior_segments=(),
        )
        self.assertEqual(result.mentions[0].surface_text, "Мастер и Маргарита")
        self.assertEqual((result.mentions[0].char_start, result.mentions[0].char_end), (21, 39))

    def test_explicit_passport_task_is_synthesized_after_model_abstention(self) -> None:
        empty = ExtractionResult("1", True, (), ())
        result = normalize_discourse(
            empty,
            segment_text="Remind me to renew my passport.",
            prior_segments=(),
        )
        self.assertFalse(result.abstain)
        self.assertEqual(result.candidates[0].schema_name, "renew_passport")

    def test_destination_evidence_relation_is_canonical(self) -> None:
        candidate = _candidate(
            "destination_choice",
            CandidateKind.PREFERENCE,
            (CandidateArgument("subject", literal="self", has_literal=True),),
        )
        candidate = replace(
            candidate,
            evidence=(EvidenceSpan("introduces_alternatives", "evidence", 0, 8),),
        )
        result = normalize_discourse(
            _result(candidate),
            segment_text="Я выберу Лондон или Париж.",
            prior_segments=(),
        )
        self.assertEqual(result.candidates[0].evidence[0].relation, "supports")


if __name__ == "__main__":
    unittest.main()
