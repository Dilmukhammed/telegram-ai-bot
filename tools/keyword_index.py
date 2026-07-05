import math
import re

from tools.schema import ToolSpec
from tools.ranking import keyword_action_bonus

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Bare tokens skipped in multi-word queries so "search gmail" does not also score as "search" → exa.
_GENERIC_MULTIWORD_SKIP = frozenset({"search", "find", "lookup", "query", "list", "get"})


def tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def ordered_query_tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def expand_query_terms(query: str) -> list[str]:
    stripped = query.strip()
    if not stripped:
        return []

    tokens = ordered_query_tokens(stripped)
    terms = [stripped.lower()]
    for token in tokens:
        if token in terms:
            continue
        if token in _GENERIC_MULTIWORD_SKIP and len(tokens) > 1:
            continue
        terms.append(token)
    return terms


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class KeywordToolIndex:
    def score(self, query: str, tool: ToolSpec) -> float:
        query_tokens = tokenize(query)
        if not query_tokens:
            return 0.0

        tool_tokens = tokenize(tool.index_text())
        overlap = len(query_tokens & tool_tokens)
        name_bonus = 2 if any(token in tool.name.lower() for token in query_tokens) else 0
        tag_bonus = sum(1 for tag in tool.tags if tag.lower() in query_tokens)
        action_bonus = keyword_action_bonus(query_tokens, tool.name)
        raw = overlap + name_bonus + tag_bonus + action_bonus
        return raw / (len(query_tokens) + 2)

    def search(self, query: str, candidates: list[ToolSpec], top_k: int = 5) -> list[ToolSpec]:
        return self.search_multi(expand_query_terms(query) or [query], candidates, top_k=top_k)

    def search_multi(
        self,
        queries: list[str],
        candidates: list[ToolSpec],
        top_k: int = 5,
    ) -> list[ToolSpec]:
        if not candidates:
            return []

        scored: list[tuple[float, ToolSpec]] = []
        for tool in candidates:
            term_scores = [self.score(term, tool) for term in queries if term.strip()]
            if not term_scores:
                continue
            scored.append((max(term_scores), tool))

        scored.sort(key=lambda item: item[0], reverse=True)
        positive = [tool for score, tool in scored if score > 0]
        if positive:
            return positive[:top_k]
        return candidates[:top_k]
