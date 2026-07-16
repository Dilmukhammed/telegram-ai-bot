from __future__ import annotations

import hashlib
from typing import Any, Mapping, Protocol, runtime_checkable

from memory.ids import canonical_json, make_resolution_verdict_id
from memory.resolution.json_schema import resolution_link_output_schema
from memory.resolution.link_view import build_proposed_link_view
from memory.resolution.parser import ResolutionParseError, parse_link_verdict
from memory.resolution.prompts import build_adversarial_messages, build_support_messages
from memory.resolution.schemas import (
    ALIAS_CRITIC_RISK,
    CRITIC_NAME,
    CRITIC_VERSION,
    RESOLUTION_PROMPT_VERSION,
    ProposedExactAlias,
    ResolutionVerdictRecord,
)
from memory.structured_output import StructuredOutputModel


@runtime_checkable
class LinkCriticModel(Protocol):
    model_profile: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = "resolution_link",
    ) -> str: ...


class LLMLinkCriticModel:
    def __init__(self, client: Any, *, model_profile: str, max_tokens: int = 1536) -> None:
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
        structured_schema: str | None = "resolution_link",
    ) -> str:
        if structured_schema not in (None, "resolution_link"):
            raise ValueError(f"unsupported resolution schema: {structured_schema!r}")
        generated = await self._transport.generate(
            messages,
            schema_name=structured_schema,
            schema=resolution_link_output_schema() if structured_schema else None,
        )
        return generated.text


def link_view_input_hash(link_view: Mapping[str, Any], *, role: str) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "prompt_version": RESOLUTION_PROMPT_VERSION,
                "critic_name": CRITIC_NAME,
                "critic_version": CRITIC_VERSION,
                "role": role,
                "link_view": dict(link_view),
            }
        ).encode("utf-8")
    ).hexdigest()


async def critique_proposed_alias(
    proposal: ProposedExactAlias,
    *,
    support_model: LinkCriticModel | None,
    adversarial_model: LinkCriticModel | None,
    neighboring_arguments: list[Mapping[str, Any]] | None = None,
    source_authority: str | None = None,
    source_occurred_at: str | None = None,
    require_adversarial: bool = True,
) -> tuple[bool, list[ResolutionVerdictRecord], str]:
    """Return (accepted, verdicts, decision_reason). Fail-closed to provisional."""
    link_view = build_proposed_link_view(
        proposal,
        neighboring_arguments=neighboring_arguments or (),
        source_authority=source_authority,
        source_occurred_at=source_occurred_at,
    )
    verdicts: list[ResolutionVerdictRecord] = []

    if support_model is None:
        return False, verdicts, "critic_unavailable"

    support = await _run_critic(
        support_model,
        role="support",
        proposal=proposal,
        link_view=link_view,
        messages=build_support_messages(link_view),
    )
    verdicts.append(support)
    if support.verdict != "supported":
        return False, verdicts, f"support_{support.verdict}"

    if require_adversarial or ALIAS_CRITIC_RISK == "support_and_adversarial":
        if adversarial_model is None:
            return False, verdicts, "adversarial_unavailable"
        adversarial = await _run_critic(
            adversarial_model,
            role="adversarial",
            proposal=proposal,
            link_view=link_view,
            messages=build_adversarial_messages(link_view),
        )
        verdicts.append(adversarial)
        if adversarial.verdict != "supported":
            return False, verdicts, f"adversarial_{adversarial.verdict}"

    return True, verdicts, "exact_alias_verified"


async def _run_critic(
    model: LinkCriticModel,
    *,
    role: str,
    proposal: ProposedExactAlias,
    link_view: Mapping[str, Any],
    messages: list[dict[str, str]],
) -> ResolutionVerdictRecord:
    input_hash = link_view_input_hash(link_view, role=role)
    output: dict[str, Any]
    try:
        raw = await model.generate(messages, structured_schema="resolution_link")
        parsed = parse_link_verdict(raw)
        output = {
            "schema_version": parsed.schema_version,
            "verdict": parsed.verdict,
            "scope_errors": list(parsed.scope_errors),
            "ambiguities": list(parsed.ambiguities),
            "missing_context": list(parsed.missing_context),
            "corrected_resolution": None,
        }
        verdict = parsed.verdict
        scope_errors = parsed.scope_errors
        ambiguities = parsed.ambiguities
        missing_context = parsed.missing_context
    except (ResolutionParseError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
        verdict = "malformed"
        scope_errors = ("critic_failure",)
        ambiguities = ()
        missing_context = ()
        output = {
            "schema_version": "1",
            "verdict": "malformed",
            "scope_errors": ["critic_failure"],
            "ambiguities": [],
            "missing_context": [],
            "corrected_resolution": None,
            "error": str(exc)[:500],
        }
    return ResolutionVerdictRecord(
        resolution_verdict_id=make_resolution_verdict_id(
            mention_id=proposal.mention_id,
            proposed_entity_id=proposal.proposed_entity.entity_id,
            role=role,
            critic_name=CRITIC_NAME,
            critic_version=CRITIC_VERSION,
            prompt_version=RESOLUTION_PROMPT_VERSION,
            input_hash=input_hash,
        ),
        mention_id=proposal.mention_id,
        proposed_entity_id=proposal.proposed_entity.entity_id,
        role=role,
        verdict=verdict,
        scope_errors=scope_errors,
        ambiguities=ambiguities,
        missing_context=missing_context,
        critic_name=CRITIC_NAME,
        critic_version=CRITIC_VERSION,
        prompt_version=RESOLUTION_PROMPT_VERSION,
        model_profile=getattr(model, "model_profile", None),
        model_name=None,
        reasoning_effort="medium",
        input_hash=input_hash,
        output_json=output,
    )
