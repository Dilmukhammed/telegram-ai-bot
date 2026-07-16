from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from memory.summaries.schemas import (
    BeliefSnapshot,
    SentenceVerdict,
    SummaryDraft,
    VerificationResult,
    VERIFY_PROMPT_VERSION,
)
from memory.summaries.verification.preflight import exact_support_match, run_preflight


@runtime_checkable
class SummaryVerifierModel(Protocol):
    model_profile: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = None,
    ) -> str: ...


class FailClosedVerifierModel:
    """Marks any non-exact sentence unsupported unless explicitly supported."""

    model_profile = "fail_closed"

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = None,
    ) -> str:
        del structured_schema
        user = next((m["content"] for m in messages if m["role"] == "user"), "")
        verdict = "unsupported"
        if "exact_match=yes" in user:
            verdict = "supported"
        return json.dumps({"verdict": verdict})


class AlwaysSupportVerifierModel:
    model_profile = "always_support"

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = None,
    ) -> str:
        del structured_schema
        return json.dumps({"verdict": "supported"})


class LLMSummaryVerifierModel:
    def __init__(self, client: object, *, model_profile: str, max_tokens: int) -> None:
        from memory.structured_output import StructuredOutputModel

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
        structured_schema: str | None = None,
    ) -> str:
        del structured_schema
        generated = await self._transport.generate(messages)
        return generated.text


async def verify_summary_draft(
    draft: SummaryDraft,
    *,
    input_beliefs: tuple[BeliefSnapshot, ...],
    model: SummaryVerifierModel | None,
    verify_enabled: bool,
) -> VerificationResult:
    ok, reason = run_preflight(draft, input_beliefs=input_beliefs)
    if not ok:
        return VerificationResult(
            accepted=False,
            sentence_verdicts=(),
            reject_reason=reason,
        )
    verdicts: list[SentenceVerdict] = []
    for index, sentence in enumerate(draft.sentences):
        cited = sentence.belief_ids
        if exact_support_match(sentence.text, input_beliefs, cited_ids=cited):
            verdicts.append(
                SentenceVerdict(
                    sentence_index=index,
                    verdict="supported",
                    belief_ids=cited,
                )
            )
            continue
        if not verify_enabled or model is None:
            verdicts.append(
                SentenceVerdict(
                    sentence_index=index,
                    verdict="supported",
                    belief_ids=cited,
                )
            )
            continue
        llm_verdict = await _llm_sentence_verdict(
            sentence.text,
            cited_ids=cited,
            beliefs=input_beliefs,
            model=model,
        )
        verdicts.append(
            SentenceVerdict(
                sentence_index=index,
                verdict=llm_verdict,
                belief_ids=cited,
            )
        )
        if llm_verdict == "unsupported":
            return VerificationResult(
                accepted=False,
                sentence_verdicts=tuple(verdicts),
                reject_reason=f"sentence_{index}_unsupported",
            )
    return VerificationResult(accepted=True, sentence_verdicts=tuple(verdicts))


async def _llm_sentence_verdict(
    sentence: str,
    *,
    cited_ids: tuple[str, ...],
    beliefs: tuple[BeliefSnapshot, ...],
    model: SummaryVerifierModel,
) -> str:
    cited = [b for b in beliefs if b.belief_id in cited_ids]
    exact = exact_support_match(sentence, beliefs, cited_ids=cited_ids)
    lines = [
        f"prompt_version={VERIFY_PROMPT_VERSION}",
        f"sentence={sentence}",
        f"exact_match={'yes' if exact else 'no'}",
        "cited_beliefs:",
    ]
    for belief in cited:
        lines.append(f"- {belief.belief_id}: {belief.statement}")
    messages = [
        {
            "role": "system",
            "content": "Return JSON {verdict: supported|unsupported|uncertain}. Fail closed.",
        },
        {"role": "user", "content": "\n".join(lines)},
    ]
    raw = await model.generate(messages)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "unsupported"
    verdict = str(payload.get("verdict") or "unsupported").casefold()
    if verdict not in {"supported", "unsupported", "uncertain"}:
        return "unsupported"
    if verdict in {"unsupported", "uncertain"}:
        return "unsupported"
    return "supported"
