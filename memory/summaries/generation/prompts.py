from __future__ import annotations

from memory.summaries.schemas import BeliefSnapshot, SUMMARY_PROMPT_VERSION


def build_generation_messages(
    *,
    summary_type: str,
    target_id: str,
    beliefs: tuple[BeliefSnapshot, ...],
) -> list[dict[str, str]]:
    lines = [
        "Generate a concise summary from accepted beliefs only.",
        "Every sentence must cite one or more belief_ids from the input set.",
        "Preserve uncertainty and historical status; do not invent facts.",
        f"summary_type={summary_type}",
        f"target_id={target_id}",
        f"prompt_version={SUMMARY_PROMPT_VERSION}",
        "beliefs:",
    ]
    for belief in beliefs:
        lines.append(
            f"- id={belief.belief_id} status={belief.belief_status} "
            f"utility={belief.utility_class} polarity={belief.polarity} "
            f"schema={belief.schema_name}: {belief.statement}"
        )
    return [
        {"role": "system", "content": "You write belief-grounded memory summaries."},
        {"role": "user", "content": "\n".join(lines)},
    ]
