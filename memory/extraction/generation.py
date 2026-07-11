from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ModelGeneration:
    text: str
    metadata: Mapping[str, Any]

