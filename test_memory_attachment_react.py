from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from memory.attachment.context import AttachmentContextPack
from memory.attachment.react import run_attachment_research
from memory.attachment.react_tools import AttachmentReactTools
from memory.attachment.schemas import AttachmentConfig
from memory.db import MemoryDatabase, utc_now_iso


class FakeReactModel:
    model_profile = "agent"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        structured_schema: str | None = None,
    ) -> str:
        if not self.responses:
            raise RuntimeError("no response")
        return json.dumps(self.responses.pop(0))


class FakeTools:
    def graph_snapshot(self) -> dict[str, Any]:
        return {"graph_revision": 7, "active_nodes": 4, "active_edges": 3}

    def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == "search_entities":
            return {
                "query": arguments["query"],
                "hits": [
                    {
                        "entity_id": "e_pizza",
                        "label": "пицца",
                        "entity_type": "food",
                        "score": 1.0,
                    }
                ],
            }
        return {"error": "unexpected_tool"}


def _config(**overrides: Any) -> AttachmentConfig:
    values = {
        "enabled": True,
        "generation_enabled": True,
        "verify_enabled": True,
        "two_generator_enabled": False,
        "vector_enabled": True,
        "curated_taxonomy_enabled": True,
        "inferred_preference_enabled": True,
        "write_graph_edges": False,
        "write_possible_events": False,
        "scan_interval_seconds": 1.0,
        "scan_batch_size": 10,
        "debounce_seconds": 0.0,
        "max_candidates": 12,
        "max_llm_calls": 6,
        "model_profile": "extraction",
        "support_model_profile": "extraction",
        "adversarial_model_profile": "agent",
        "cluster_model_profile": "agent",
        "max_tokens": 1536,
        "react_enabled": True,
        "react_mode": "shadow",
        "react_model_profile": "agent",
        "react_max_actions": 4,
        "react_max_hops": 3,
        "react_max_results": 10,
        "react_max_nodes": 60,
        "react_max_tokens": 1536,
    }
    values.update(overrides)
    return AttachmentConfig(**values)


def _context() -> AttachmentContextPack:
    return AttachmentContextPack(
        belief_id="belief_1",
        schema_name="likes_food",
        polarity="positive",
        epistemic={},
        statement="Я люблю пиццу",
        source_entity_id="e_source",
        source_label="пицца",
        source_entity_type="food",
        attach_domains=("food",),
        neighbor_entities=(),
        existing_attachments=(),
        domain_preferences=(),
        recent_corrections=(),
    )


def _action(
    *,
    kind: str,
    tool: str = "",
    arguments: dict[str, Any] | None = None,
    decision: str = "continue",
    recommendations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "tool": tool,
        "arguments": arguments or {},
        "why": "test",
        "decision": decision,
        "recommendations": recommendations or [],
        "confirmed_existing": [],
        "missing_information": [],
    }


class AttachmentReactTests(unittest.TestCase):
    def test_real_tools_are_user_scoped_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = MemoryDatabase(str(Path(tmp) / "memory.sqlite"))
            now = utc_now_iso()
            with db.transaction() as conn:
                for entity_id, user_id, label in (
                    ("e_u1", 1, "пицца"),
                    ("e_u2", 2, "пицца secret"),
                ):
                    conn.execute(
                        """
                        INSERT INTO memory_entities(
                          entity_id,user_id,entity_type,identity_key,canonical_label,
                          status,resolver_version,created_at,updated_at
                        ) VALUES (?,?,?,?,?,'active','test',?,?)
                        """,
                        (entity_id, user_id, "food", f"label:{label}", label, now, now),
                    )
            with db.connection() as conn:
                tools = AttachmentReactTools(
                    conn, user_id=1, max_results=1, max_hops=3
                )
                result = tools.search_entities(query="пицца", limit=99)
            self.assertEqual(len(result["hits"]), 1)
            self.assertEqual(result["hits"][0]["entity_id"], "e_u1")

    def test_shadow_research_uses_tools_and_writes_nothing(self) -> None:
        model = FakeReactModel(
            [
                _action(
                    kind="tool",
                    tool="search_entities",
                    arguments={"query": "пицца"},
                ),
                _action(
                    kind="final",
                    decision="recommend_candidates",
                    recommendations=[
                        {
                            "target_id": "e_pizza",
                            "op": "cuisine_of",
                            "why": "exact entity",
                            "evidence_step_ids": [1],
                        }
                    ],
                ),
                {"report_markdown": "Exact entity found [step 1]."},
            ]
        )
        report = asyncio.run(
            run_attachment_research(
                tools=FakeTools(),  # type: ignore[arg-type]
                model=model,
                config=_config(),
                context=_context(),
                shortlist=(),
            )
        )
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["final"]["decision"], "recommend_candidates")
        self.assertEqual(report["final"]["recommendations"][0]["target_id"], "e_pizza")
        self.assertEqual(report["report_markdown"], "Exact entity found [step 1].")
        self.assertFalse(report["write_performed"])

    def test_unobserved_target_is_removed_and_forces_abstain(self) -> None:
        model = FakeReactModel(
            [
                _action(
                    kind="final",
                    decision="recommend_candidates",
                    recommendations=[
                        {
                            "target_id": "invented",
                            "op": "same_as",
                            "why": "invented",
                            "evidence_step_ids": [1],
                        }
                    ],
                )
            ]
        )
        report = asyncio.run(
            run_attachment_research(
                tools=FakeTools(),  # type: ignore[arg-type]
                model=model,
                config=_config(),
                context=_context(),
                shortlist=(),
            )
        )
        self.assertEqual(report["final"]["decision"], "abstain")
        self.assertEqual(report["final"]["recommendations"], [])
        self.assertFalse(report["write_performed"])


if __name__ == "__main__":
    unittest.main()
