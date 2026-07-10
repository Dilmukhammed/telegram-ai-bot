from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from config import Settings
from llm import LLMClient
from thorough.output import extract_plan_yaml, plan_yaml_valid, planner_response_text

RetryCallback = Callable[[int, float], Awaitable[None] | None]

_YAML_RETRY_HINT = """\
Your previous reply was rejected: it contained thinking/analysis instead of YAML.
Reply again with ONLY valid YAML. First line MUST be `{root}:` — no text before it.
"""


async def complete_plan_yaml(
    settings: Settings,
    *,
    profile: str,
    label: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    root: str,
    operation: str,
    on_retry: RetryCallback | None = None,
) -> tuple[str, str, str]:
    """Call LLM; strip thinking; retry once if YAML root missing."""
    client = LLMClient(settings, profile=profile)
    model = client._completion_kwargs(messages=[])["model"]
    short = model.rsplit("/", 1)[-1]
    print(f"[{operation}] {label} start -> {short}", flush=True)
    started = time.perf_counter()

    attempt_messages = list(messages)
    raw = ""
    yaml_body = ""

    for attempt in (1, 2):
        response = await client._call_with_timeout_retry(
            f"{operation}_{profile}",
            lambda msgs=attempt_messages: client._client.chat.completions.create(
                **client._completion_kwargs(messages=msgs, max_tokens=max_tokens),
            ),
            on_retry=on_retry,
        )
        raw = planner_response_text(response.choices[0].message)
        yaml_body = extract_plan_yaml(raw, root=root)
        if plan_yaml_valid(yaml_body, root=root):
            break
        if attempt == 1:
            print(
                f"[{operation}] {label} invalid YAML (no {root}:), retrying...",
                flush=True,
            )
            attempt_messages = [
                *messages,
                {"role": "assistant", "content": raw[:2000]},
                {
                    "role": "user",
                    "content": _YAML_RETRY_HINT.format(root=root),
                },
            ]
        else:
            preview = raw[:200].replace("\n", " ")
            raise RuntimeError(
                f"{label} did not return valid {root} YAML after 2 attempts "
                f"({model}); preview: {preview!r}"
            )

    elapsed = time.perf_counter() - started
    print(
        f"[{operation}] {label} done in {elapsed:.1f}s "
        f"({len(yaml_body)} yaml chars, raw {len(raw)})",
        flush=True,
    )
    return model, raw, yaml_body
