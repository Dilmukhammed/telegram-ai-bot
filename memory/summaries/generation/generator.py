from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from memory.ids import canonical_json
from memory.summaries.eligibility import eligible_for_summary_type
from memory.summaries.generation.json_schema import summary_output_schema
from memory.summaries.generation.parser import SummaryParseError, parse_summary_output
from memory.summaries.generation.prompts import build_generation_messages
from memory.summaries.schemas import (
    GENERATOR_NAME,
    GENERATOR_VERSION,
    SUMMARY_PROMPT_VERSION,
    BeliefSnapshot,
    SummaryDraft,
)
from memory.structured_output import StructuredOutputModel


@runtime_checkable
class SummaryGeneratorModel(Protocol):
    model_profile: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "summary_generation",
    ) -> str: ...


class LLMSummaryGeneratorModel:
    def __init__(self, client: object, *, model_profile: str, max_tokens: int) -> None:
        self._transport = StructuredOutputModel(
            client,
            model_profile=model_profile,
            max_tokens=max_tokens,
        )
        self.model_profile = model_profile

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "summary_generation",
    ) -> str:
        generated = await self._transport.generate(
            messages,
            schema_name=structured_schema,
            schema=summary_output_schema() if structured_schema else None,
        )
        return generated.text


class DeterministicSummaryGenerator:
    """Belief-only generator for tests; never reads prior summary text."""

    model_profile = "deterministic"

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "summary_generation",
    ) -> str:
        del structured_schema
        beliefs = _beliefs_from_messages(messages)
        sentences = [
            {
                "text": belief.statement,
                "belief_ids": [belief.belief_id],
            }
            for belief in beliefs
        ]
        if not sentences:
            sentences = [{"text": "No eligible beliefs.", "belief_ids": ["none"]}]
        import json

        return json.dumps({"sentences": sentences})


def summary_input_hash(
    *,
    user_id: int,
    summary_type: str,
    target_id: str,
    beliefs: tuple[BeliefSnapshot, ...],
    prompt_version: str = SUMMARY_PROMPT_VERSION,
) -> str:
    payload = {
        "user_id": user_id,
        "summary_type": summary_type,
        "target_id": target_id,
        "generator_name": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "prompt_version": prompt_version,
        "belief_ids": sorted(b.belief_id for b in beliefs),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


async def generate_summary_draft(
    *,
    user_id: int,
    summary_type: str,
    target_id: str,
    beliefs: tuple[BeliefSnapshot, ...],
    model: SummaryGeneratorModel,
    member_belief_ids: frozenset[str] | None = None,
) -> SummaryDraft:
    eligible = eligible_for_summary_type(
        beliefs,
        summary_type=summary_type,
        target_id=target_id,
        member_belief_ids=member_belief_ids,
    )
    messages = build_generation_messages(
        summary_type=summary_type,
        target_id=target_id,
        beliefs=eligible,
    )
    raw = await model.generate(messages, structured_schema="summary_generation")
    try:
        return parse_summary_output(raw)
    except SummaryParseError:
        if eligible:
            return SummaryDraft(
                sentences=(
                    SummarySentence(text=eligible[0].statement, belief_ids=(eligible[0].belief_id,)),
                ),
                content=eligible[0].statement,
                belief_ids=(eligible[0].belief_id,),
                sentence_support={"0": (eligible[0].belief_id,)},
            )
        raise


def _beliefs_from_messages(messages: list[dict[str, str]]) -> list[BeliefSnapshot]:
    out: list[BeliefSnapshot] = []
    for message in messages:
        for line in message.get("content", "").splitlines():
            if not line.startswith("- id="):
                continue
            parts = line.split(" schema=", 1)
            head = parts[0]
            schema = parts[1].split(":", 1)[0] if len(parts) > 1 else ""
            statement = parts[1].split(":", 1)[1].strip() if len(parts) > 1 else ""
            belief_id = head.split(" id=", 1)[1].split(" ", 1)[0]
            status = _extract_token(head, "status=")
            utility = _extract_token(head, "utility=")
            polarity = _extract_token(head, "polarity=")
            out.append(
                BeliefSnapshot(
                    belief_id=belief_id,
                    schema_name=schema,
                    statement=statement,
                    belief_status=status,
                    utility_class=utility,
                    polarity=polarity,
                    entity_ids=(),
                    temporal=None,
                )
            )
    return out


def _extract_token(text: str, prefix: str) -> str:
    if prefix not in text:
        return ""
    rest = text.split(prefix, 1)[1]
    return rest.split(" ", 1)[0]
