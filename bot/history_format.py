from __future__ import annotations

import re

_DETAILS_BLOCK_RE = re.compile(r"\n*<details>.*?</details>", re.DOTALL | re.IGNORECASE)


def strip_rich_appendices(text: str) -> str:
    """Remove Telegram HTML appendices (sources, maps) from text stored for LLM history."""
    return _DETAILS_BLOCK_RE.sub("", text).rstrip()
