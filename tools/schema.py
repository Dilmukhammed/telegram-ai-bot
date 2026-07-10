from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tools.search_index import enriched_index_text

if TYPE_CHECKING:
    from tools.verification import VerificationQuestion

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    tags: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    cache_ttl_seconds: int | None = None
    rate_limit: tuple[int, int] | None = None
    parallel_safe: bool = True
    verification_questions: tuple["VerificationQuestion", ...] = ()
    checker_enabled: bool = True

    def to_search_result(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "tags": list(self.tags),
            "examples": list(self.examples),
        }

    def to_catalog_result(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
        }

    def index_text(self) -> str:
        return enriched_index_text(
            name=self.name,
            description=self.description,
            tags=self.tags,
            examples=self.examples,
        )
