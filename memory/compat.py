"""Python version shims for the memory package."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum as StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Minimal backport of enum.StrEnum (3.11+) for Ubuntu 22.04 / Python 3.10."""

        def __str__(self) -> str:
            return str(self.value)
