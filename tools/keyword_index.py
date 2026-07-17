import math
from collections import Counter

from tools.query_normalization import normalize_tool_query, normalized_query_tokens
from tools.schema import ToolSpec
from tools.ranking import keyword_action_bonus

# Bare tokens skipped in multi-word queries so "search gmail" does not also score as "search" → exa.
_GENERIC_MULTIWORD_SKIP = frozenset({"search", "find", "lookup", "query", "list", "get"})


def tokenize(text: str) -> set[str]:
    return set(normalized_query_tokens(text))


def ordered_query_tokens(text: str) -> list[str]:
    return normalized_query_tokens(text)


def expand_query_terms(query: str) -> list[str]:
    stripped = normalize_tool_query(query)
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
    BM25_K1 = 1.5
    BM25_B = 0.75

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

        scored = self.rank_multi(queries, candidates)
        positive = [tool for score, tool in scored if score > 0]
        if positive:
            return positive[:top_k]
        return candidates[:top_k]

    def rank_multi(
        self,
        queries: list[str],
        candidates: list[ToolSpec],
    ) -> list[tuple[float, ToolSpec]]:
        """Rank candidates with BM25 plus deterministic action/intent rules."""
        if not candidates:
            return []

        documents = [ordered_query_tokens(tool.index_text()) for tool in candidates]
        document_freq: Counter[str] = Counter()
        for tokens in documents:
            document_freq.update(set(tokens))
        average_length = sum(len(tokens) for tokens in documents) / len(candidates)
        intent_tokens = tokenize(queries[0]) if queries else set()

        scored: list[tuple[float, ToolSpec]] = []
        for tool, document in zip(candidates, documents):
            frequencies = Counter(document)
            term_scores: list[float] = []
            for term in queries:
                query_tokens = tokenize(term)
                if not query_tokens:
                    continue
                bm25 = 0.0
                for token in query_tokens:
                    frequency = frequencies.get(token, 0)
                    if not frequency:
                        continue
                    df = document_freq.get(token, 0)
                    inverse_df = math.log(
                        1 + (len(candidates) - df + 0.5) / (df + 0.5)
                    )
                    denominator = frequency + self.BM25_K1 * (
                        1 - self.BM25_B
                        + self.BM25_B * len(document) / max(average_length, 1.0)
                    )
                    bm25 += inverse_df * frequency * (self.BM25_K1 + 1) / denominator
                term_scores.append(bm25)
            if term_scores:
                scored.append(
                    (
                        max(term_scores)
                        + keyword_action_bonus(intent_tokens, tool.name),
                        tool,
                    )
                )

        scored.sort(key=lambda item: (-item[0], item[1].name))
        return scored
