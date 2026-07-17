from __future__ import annotations

import json
import math
import os
from pathlib import Path
from threading import RLock
from typing import Any

from tools.query_normalization import normalize_tool_query


def _enabled() -> bool:
    return os.getenv("TOOL_SEARCH_FEEDBACK_ENABLED", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class SearchFeedbackStore:
    """Small local learning-to-rank store for successful tool selections."""

    def __init__(self, path: str | None = None, eval_path: str | None = None) -> None:
        self.enabled = _enabled()
        self.path = Path(path or os.getenv("TOOL_SEARCH_FEEDBACK_PATH", "data/tool_search_feedback.json"))
        self.eval_path = Path(
            eval_path
            or os.getenv(
                "TOOL_SEARCH_EVAL_CANDIDATES_PATH",
                "data/tool_search_eval_candidates.jsonl",
            )
        )
        self._lock = RLock()
        self._choices: dict[str, dict[str, dict[str, int]]] = {}
        if self.enabled:
            self._load()

    @staticmethod
    def key(query: str, tags: list[str] | None) -> str:
        normalized_tags = ",".join(sorted(tag.lower().strip() for tag in (tags or []) if tag.strip()))
        return f"{normalized_tags}|{normalize_tool_query(query)}"

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            choices = payload.get("choices", {})
            if isinstance(choices, dict):
                self._choices = choices
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._choices = {}

    def boosts(self, query: str, tags: list[str] | None) -> dict[str, float]:
        if not self.enabled:
            return {}
        rows = self._choices.get(self.key(query, tags), {})
        result: dict[str, float] = {}
        for tool_name, counts in rows.items():
            success = max(int(counts.get("success", 0)), 0)
            failure = max(int(counts.get("failure", 0)), 0)
            result[tool_name] = math.log1p(success) - 0.75 * math.log1p(failure)
        return result

    def rerank(
        self,
        query: str,
        tags: list[str] | None,
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        boosts = self.boosts(query, tags)
        if not boosts:
            return tools
        indexed = list(enumerate(tools))
        indexed.sort(
            key=lambda item: (
                item[0]
                - 2.0 * boosts.get(str(item[1].get("name", "")), 0.0),
                item[0],
            )
        )
        return [tool for _, tool in indexed]

    def record(
        self,
        *,
        query: str,
        tags: list[str] | None,
        selected_tool: str,
        ok: bool,
        candidates: list[str],
    ) -> None:
        if not self.enabled or not query.strip():
            return
        key = self.key(query, tags)
        with self._lock:
            tools = self._choices.setdefault(key, {})
            counts = tools.setdefault(selected_tool, {"success": 0, "failure": 0})
            field = "success" if ok else "failure"
            counts[field] = int(counts.get(field, 0)) + 1
            self._save()
            if not ok or not candidates or candidates[0] != selected_tool:
                self._append_eval_candidate(
                    {
                        "query": normalize_tool_query(query),
                        "tags": tags or [],
                        "candidates": candidates,
                        "selected_tool": selected_tool,
                        "ok": ok,
                    }
                )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "choices": self._choices}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def _append_eval_candidate(self, payload: dict[str, Any]) -> None:
        self.eval_path.parent.mkdir(parents=True, exist_ok=True)
        with self.eval_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
