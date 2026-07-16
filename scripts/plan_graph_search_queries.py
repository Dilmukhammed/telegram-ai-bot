"""Standalone, no-database LLM probe for graph-search query planning.

The only input sent to the model is the hard-coded public example below.  This
script never imports the memory service, opens SQLite, or starts any worker.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_settings
from llm import LLMClient
from memory.attachment.context import lexical_overlap
from memory.attachment.taxonomy import normalize_label
from memory.retrieval.fusion import rrf_fuse
from memory.retrieval.schemas import RetrievalHit


EXAMPLE_INPUT: dict[str, Any] = {
    "anchor_entity": {"label": "пицца", "entity_type": "food"},
    "anchor_edge": {"edge_type": "likes_eat", "direction": "user_to_food"},
    "known_graph_contract": {
        "node_kinds": ["user", "food", "cuisine", "country", "group", "concept"],
        "example_edge_types": [
            "likes_eat",
            "prefers_food",
            "cuisine_of",
            "instance_of",
            "alias_of",
            "part_of",
            "located_in",
            "add_to_group",
        ],
        "max_graph_hops": 3,
    },
}

# Public synthetic fixture. It is deliberately small and is the only graph the
# probe can search; no real memory data is ever read.
SYNTHETIC_GRAPH: dict[str, Any] = {
    "entities": [
        {"id": "e_self", "label": "self", "kind": "user", "aliases": ["user"], "semantic_terms": ["person"]},
        {"id": "e_pizza", "label": "пицца", "kind": "food", "aliases": ["pizza", "пиццы", "pizza pie"], "semantic_terms": ["pizza", "italian", "food", "baked"]},
        {"id": "e_italian", "label": "Italian Cuisine", "kind": "cuisine", "aliases": ["Italian food", "итальянская кухня", "итальянская еда"], "semantic_terms": ["italian", "cuisine", "food", "pasta"]},
        {"id": "e_pasta", "label": "spaghetti", "kind": "food", "aliases": ["паста", "спагетти"], "semantic_terms": ["italian", "pasta", "food"]},
        {"id": "e_fast", "label": "fast food", "kind": "group", "aliases": ["quick service food"], "semantic_terms": ["fast", "food"]},
        {"id": "e_sushi", "label": "sushi", "kind": "food", "aliases": ["суши"], "semantic_terms": ["japanese", "food", "fish"]},
        {"id": "e_japanese", "label": "Japanese Cuisine", "kind": "cuisine", "aliases": ["японская кухня", "Japanese food"], "semantic_terms": ["japanese", "cuisine", "food"]},
        {"id": "e_taco", "label": "taco", "kind": "food", "aliases": ["тако"], "semantic_terms": ["mexican", "food"]},
        {"id": "e_mexican", "label": "Mexican Cuisine", "kind": "cuisine", "aliases": ["мексиканская кухня", "Mexican food"], "semantic_terms": ["mexican", "cuisine", "food"]},
        {"id": "e_italy", "label": "Italy", "kind": "country", "aliases": ["Italia", "Италия"], "semantic_terms": ["italy", "europe"]},
        {"id": "e_japan", "label": "Japan", "kind": "country", "aliases": ["Япония"], "semantic_terms": ["japan", "asia"]},
        {"id": "e_tashkent", "label": "Tashkent", "kind": "place", "aliases": ["Ташкент"], "semantic_terms": ["uzbekistan", "city"]},
        {"id": "e_berlin", "label": "Berlin", "kind": "place", "aliases": ["Берлин"], "semantic_terms": ["germany", "city"]},
        {"id": "e_alice", "label": "Alice", "kind": "person", "aliases": ["Алиса"], "semantic_terms": ["person", "coworker"]},
        {"id": "e_acme", "label": "Acme Corp", "kind": "organization", "aliases": ["Acme"], "semantic_terms": ["company", "work"]},
        {"id": "e_python", "label": "Python", "kind": "software", "aliases": ["Python language"], "semantic_terms": ["programming", "language"]},
        {"id": "e_fastapi", "label": "FastAPI", "kind": "software", "aliases": ["Fast API"], "semantic_terms": ["python", "web", "framework"]},
        {"id": "e_ml", "label": "machine learning", "kind": "topic", "aliases": ["ML", "машинное обучение"], "semantic_terms": ["ai", "models", "data"]},
        {"id": "e_guitar", "label": "guitar", "kind": "hobby", "aliases": ["гитара"], "semantic_terms": ["music", "instrument"]},
        {"id": "e_jazz", "label": "jazz", "kind": "music", "aliases": ["джаз"], "semantic_terms": ["music", "genre"]},
        {"id": "e_running", "label": "running", "kind": "activity", "aliases": ["бег"], "semantic_terms": ["sport", "fitness"]},
        {"id": "e_margherita", "label": "Margherita pizza", "kind": "food", "aliases": ["маргарита"], "semantic_terms": ["pizza", "italian", "tomato", "cheese"]},
        {"id": "e_pepperoni", "label": "pepperoni pizza", "kind": "food", "aliases": ["пепперони"], "semantic_terms": ["pizza", "meat", "italian"]},
        {"id": "e_dough", "label": "pizza dough", "kind": "ingredient", "aliases": ["тесто"], "semantic_terms": ["pizza", "baked", "flour"]},
        {"id": "e_tomato", "label": "tomato", "kind": "ingredient", "aliases": ["помидор"], "semantic_terms": ["pizza", "vegetable", "sauce"]},
        {"id": "e_mozzarella", "label": "mozzarella", "kind": "ingredient", "aliases": ["моцарелла"], "semantic_terms": ["pizza", "cheese", "italian"]},
        {"id": "e_neapolitan", "label": "Neapolitan cuisine", "kind": "cuisine", "aliases": ["Naples cuisine"], "semantic_terms": ["italian", "pizza", "naples"]},
        {"id": "e_naples", "label": "Naples", "kind": "place", "aliases": ["Napoli"], "semantic_terms": ["italy", "city", "pizza"]},
        {"id": "e_europe", "label": "Europe", "kind": "region", "aliases": ["European region"], "semantic_terms": ["region", "italy", "germany"]},
        {"id": "e_restaurant", "label": "Trattoria Roma", "kind": "place", "aliases": ["Roma trattoria"], "semantic_terms": ["restaurant", "italian", "pizza"]},
        {"id": "e_bob", "label": "Bob", "kind": "person", "aliases": ["Боб"], "semantic_terms": ["person", "coworker", "friend"]},
        {"id": "e_product", "label": "memory graph project", "kind": "project", "aliases": ["graph memory"], "semantic_terms": ["software", "memory", "ai"]},
        {"id": "e_postgres", "label": "PostgreSQL", "kind": "software", "aliases": ["Postgres"], "semantic_terms": ["database", "sql", "backend"]},
        {"id": "e_docker", "label": "Docker", "kind": "software", "aliases": ["containers"], "semantic_terms": ["devops", "container", "backend"]},
        {"id": "e_retrieval", "label": "hybrid retrieval", "kind": "topic", "aliases": ["RRF retrieval"], "semantic_terms": ["search", "embeddings", "ranking"]},
        {"id": "e_embeddings", "label": "embeddings", "kind": "topic", "aliases": ["vector embeddings"], "semantic_terms": ["vector", "semantic", "search"]},
        {"id": "e_llm", "label": "LLM agents", "kind": "topic", "aliases": ["language-model agents"], "semantic_terms": ["ai", "agent", "models"]},
        {"id": "e_course", "label": "distributed systems course", "kind": "course", "aliases": ["systems course"], "semantic_terms": ["learning", "software", "systems"]},
        {"id": "e_book", "label": "Designing Data-Intensive Applications", "kind": "book", "aliases": ["DDIA"], "semantic_terms": ["database", "systems", "book"]},
        {"id": "e_tokyo", "label": "Tokyo", "kind": "place", "aliases": ["Токио"], "semantic_terms": ["japan", "city", "travel"]},
        {"id": "e_kyoto", "label": "Kyoto", "kind": "place", "aliases": ["Киото"], "semantic_terms": ["japan", "city", "travel"]},
        {"id": "e_photography", "label": "photography", "kind": "hobby", "aliases": ["фотография"], "semantic_terms": ["camera", "art", "travel"]},
        {"id": "e_camera", "label": "mirrorless camera", "kind": "equipment", "aliases": ["camera"], "semantic_terms": ["photography", "camera", "travel"]},
        {"id": "e_cycling", "label": "cycling", "kind": "activity", "aliases": ["велосипед"], "semantic_terms": ["sport", "fitness", "outdoor"]},
        {"id": "e_bicycle", "label": "road bicycle", "kind": "equipment", "aliases": ["bike"], "semantic_terms": ["cycling", "sport", "outdoor"]},
    ],
    "groups": [
        {"id": "g_italian", "label": "Italian dishes", "kind": "cuisine_group", "members": ["e_pizza", "e_pasta"]},
        {"id": "g_baked", "label": "baked goods", "kind": "category", "members": ["e_pizza"]},
        {"id": "g_asian", "label": "Asian dishes", "kind": "cuisine_group", "members": ["e_sushi"]},
        {"id": "g_work", "label": "work context", "kind": "community", "members": ["e_alice", "e_acme"]},
        {"id": "g_software", "label": "software engineering", "kind": "community", "members": ["e_python", "e_fastapi", "e_ml"]},
        {"id": "g_music", "label": "music hobbies", "kind": "community", "members": ["e_guitar", "e_jazz"]},
        {"id": "g_fitness", "label": "fitness", "kind": "community", "members": ["e_running"]},
        {"id": "g_travel", "label": "travel places", "kind": "community", "members": ["e_tashkent", "e_berlin", "e_italy", "e_japan"]},
        {"id": "g_pizza", "label": "pizza varieties", "kind": "food_group", "members": ["e_pizza", "e_margherita", "e_pepperoni"]},
        {"id": "g_ingredients", "label": "pizza ingredients", "kind": "ingredient_group", "members": ["e_dough", "e_tomato", "e_mozzarella"]},
        {"id": "g_european", "label": "European travel", "kind": "community", "members": ["e_italy", "e_berlin", "e_naples"]},
        {"id": "g_japan", "label": "Japan itinerary", "kind": "community", "members": ["e_japan", "e_tokyo", "e_kyoto"]},
        {"id": "g_backend", "label": "backend stack", "kind": "community", "members": ["e_python", "e_fastapi", "e_postgres", "e_docker"]},
        {"id": "g_ai_search", "label": "AI search", "kind": "topic_group", "members": ["e_ml", "e_llm", "e_retrieval", "e_embeddings"]},
        {"id": "g_learning", "label": "systems learning", "kind": "community", "members": ["e_course", "e_book", "e_postgres"]},
        {"id": "g_outdoors", "label": "outdoor hobbies", "kind": "community", "members": ["e_running", "e_cycling", "e_photography"]},
    ],
    "edges": [
        {"id": "edge_1", "from": "e_self", "to": "e_pizza", "type": "likes_eat"},
        {"id": "edge_2", "from": "e_pizza", "to": "e_italian", "type": "cuisine_of"},
        {"id": "edge_3", "from": "e_pizza", "to": "e_fast", "type": "instance_of"},
        {"id": "edge_4", "from": "e_pasta", "to": "e_italian", "type": "cuisine_of"},
        {"id": "edge_5", "from": "e_italian", "to": "e_italy", "type": "located_in"},
        {"id": "edge_6", "from": "e_self", "to": "e_sushi", "type": "prefers_food"},
        {"id": "edge_7", "from": "e_sushi", "to": "e_japanese", "type": "cuisine_of"},
        {"id": "edge_8", "from": "e_japanese", "to": "e_japan", "type": "located_in"},
        {"id": "edge_9", "from": "e_self", "to": "e_taco", "type": "likes_eat"},
        {"id": "edge_10", "from": "e_taco", "to": "e_mexican", "type": "cuisine_of"},
        {"id": "edge_11", "from": "e_alice", "to": "e_acme", "type": "works_at"},
        {"id": "edge_12", "from": "e_self", "to": "e_tashkent", "type": "lives_in"},
        {"id": "edge_13", "from": "e_self", "to": "e_berlin", "type": "visited"},
        {"id": "edge_14", "from": "e_fastapi", "to": "e_python", "type": "built_with"},
        {"id": "edge_15", "from": "e_self", "to": "e_python", "type": "uses"},
        {"id": "edge_16", "from": "e_self", "to": "e_ml", "type": "studies"},
        {"id": "edge_17", "from": "e_self", "to": "e_guitar", "type": "plays"},
        {"id": "edge_18", "from": "e_self", "to": "e_jazz", "type": "likes_music"},
        {"id": "edge_19", "from": "e_self", "to": "e_running", "type": "does"},
        {"id": "edge_20", "from": "e_margherita", "to": "e_pizza", "type": "variant_of"},
        {"id": "edge_21", "from": "e_pepperoni", "to": "e_pizza", "type": "variant_of"},
        {"id": "edge_22", "from": "e_pizza", "to": "e_dough", "type": "has_ingredient"},
        {"id": "edge_23", "from": "e_pizza", "to": "e_tomato", "type": "has_ingredient"},
        {"id": "edge_24", "from": "e_pizza", "to": "e_mozzarella", "type": "has_ingredient"},
        {"id": "edge_25", "from": "e_pizza", "to": "e_neapolitan", "type": "originates_from"},
        {"id": "edge_26", "from": "e_neapolitan", "to": "e_naples", "type": "located_in"},
        {"id": "edge_27", "from": "e_naples", "to": "e_italy", "type": "located_in"},
        {"id": "edge_28", "from": "e_italy", "to": "e_europe", "type": "part_of"},
        {"id": "edge_29", "from": "e_restaurant", "to": "e_pizza", "type": "serves"},
        {"id": "edge_30", "from": "e_self", "to": "e_restaurant", "type": "visited"},
        {"id": "edge_31", "from": "e_bob", "to": "e_acme", "type": "works_at"},
        {"id": "edge_32", "from": "e_alice", "to": "e_bob", "type": "collaborates_with"},
        {"id": "edge_33", "from": "e_acme", "to": "e_product", "type": "owns"},
        {"id": "edge_34", "from": "e_product", "to": "e_retrieval", "type": "uses"},
        {"id": "edge_35", "from": "e_product", "to": "e_llm", "type": "uses"},
        {"id": "edge_36", "from": "e_retrieval", "to": "e_embeddings", "type": "uses"},
        {"id": "edge_37", "from": "e_fastapi", "to": "e_postgres", "type": "connects_to"},
        {"id": "edge_38", "from": "e_product", "to": "e_fastapi", "type": "built_with"},
        {"id": "edge_39", "from": "e_product", "to": "e_docker", "type": "deployed_with"},
        {"id": "edge_40", "from": "e_self", "to": "e_course", "type": "studies"},
        {"id": "edge_41", "from": "e_course", "to": "e_book", "type": "recommends"},
        {"id": "edge_42", "from": "e_course", "to": "e_postgres", "type": "covers"},
        {"id": "edge_43", "from": "e_tokyo", "to": "e_japan", "type": "located_in"},
        {"id": "edge_44", "from": "e_kyoto", "to": "e_japan", "type": "located_in"},
        {"id": "edge_45", "from": "e_self", "to": "e_tokyo", "type": "visited"},
        {"id": "edge_46", "from": "e_self", "to": "e_photography", "type": "practices"},
        {"id": "edge_47", "from": "e_photography", "to": "e_camera", "type": "uses"},
        {"id": "edge_48", "from": "e_self", "to": "e_cycling", "type": "does"},
        {"id": "edge_49", "from": "e_cycling", "to": "e_bicycle", "type": "uses"},
    ],
}

# These are reporting cut-offs, deliberately explicit for the experiment.
# A production implementation should obtain them from the retrieval policy.
REPORT_LIMIT = 10
REPORT_THRESHOLDS = {
    "entity_searches": 0.20,
    "group_searches": 0.20,
    "edge_searches": 0.55,
    "pair_and_path_searches": 0.55,
}


SYSTEM_PROMPT = """You are designing search actions for a future read-only agent over a graph.
This is a synthetic example only. There is no real user graph, no database access, and you
must not claim that any node or edge actually exists.

Given one anchor entity and one anchor edge type, generate diverse search variants a later
agent could run to discover related entities, groups and edges. Think separately about:
- entity search: spelling variants, aliases, translations, morphology and semantic labels;
- group search: possible cuisine/category/topic/community/group labels;
- edge search: exact edge type, near edge types, incoming/outgoing/bidirectional traversal,
  and paths up to the supplied hop limit;
- pair search: ways to find paths and motifs connecting the anchor entity to nodes incident
  to the anchor edge type.

Do not choose a final attachment and do not invent facts. Every result must be a QUERY PLAN,
not a claim about the graph. Keep the plans concrete enough that code could execute them.

Return exactly one JSON object:
{
  "entity_queries": [{"query":"string","channel":"lexical|alias|vector|taxonomy","reason":"string"}],
  "group_queries": [{"query":"string","group_kind":"string","reason":"string"}],
  "edge_queries": [{"edge_types":["string"],"direction":"incoming|outgoing|both","max_hops":1,"reason":"string"}],
  "pair_and_path_queries": [{"from":"string","via_edge_types":["string"],"to_kind":"string","max_hops":1,"reason":"string"}],
  "agent_tool_sequence": ["short imperative action"],
  "ambiguities": ["string"],
  "write_decision": "abstain"
}
Use at most 8 entries per list. Do not output markdown.
"""


async def run_probe() -> dict[str, Any]:
    settings = get_settings()
    client = LLMClient(settings, profile="extraction")
    raw = await client.chat_structured(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(EXAMPLE_INPUT, ensure_ascii=False)},
        ],
        max_tokens=3000,
        response_format={"type": "json_object"},
    )
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("planner returned incomplete or invalid JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("planner response must be a JSON object")
    result["_meta"] = {
        "mode": "synthetic_no_database_probe",
        "model": client.model_name,
        "input": EXAMPLE_INPUT,
        "sqlite_opened": False,
        "db_written": False,
    }
    return result


def _entity_index() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in SYNTHETIC_GRAPH["entities"]}


def _entity_search(query: str, channel: str) -> list[dict[str, Any]]:
    needle = normalize_label(query)
    hits: list[dict[str, Any]] = []
    query_terms = set(needle.split())
    for entity in SYNTHETIC_GRAPH["entities"]:
        label = str(entity["label"])
        aliases = [str(item) for item in entity.get("aliases", [])]
        if channel == "alias":
            score = 1.0 if needle in {normalize_label(x) for x in aliases} else 0.0
        elif channel == "vector":
            terms = {normalize_label(x) for x in entity.get("semantic_terms", [])}
            score = len(query_terms & terms) / len(query_terms | terms) if query_terms and terms else 0.0
        elif channel == "taxonomy":
            score = 1.0 if needle in {"italian food", "italian cuisine", "итальянская кухня", "итальянская еда"} and entity["id"] == "e_italian" else 0.0
        else:
            score = max([lexical_overlap(query, label), *(lexical_overlap(query, item) for item in aliases)])
        if score > 0.0:
            hits.append({"entity_id": entity["id"], "label": label, "kind": entity["kind"], "score": round(score, 4), "channel": channel})
    return sorted(hits, key=lambda item: (-float(item["score"]), str(item["entity_id"])))


def _group_search(query: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for group in SYNTHETIC_GRAPH["groups"]:
        score = lexical_overlap(query, str(group["label"]))
        if score > 0.0:
            hits.append({"group_id": group["id"], "label": group["label"], "kind": group["kind"], "members": group["members"], "score": round(score, 4)})
    return sorted(hits, key=lambda item: (-float(item["score"]), str(item["group_id"])))


def _edge_search(
    edge_types: list[str],
    direction: str,
    max_hops: int,
    target_kind: str | None = None,
) -> list[dict[str, Any]]:
    # This fixture starts from the public anchor entity. A real tool would take
    # the resolved seed ID produced by entity search.
    seed = "e_pizza"
    frontier = [(seed, [])]
    visited = {seed}
    found: list[dict[str, Any]] = []
    entities = _entity_index()
    allowed = set(edge_types)
    for _depth in range(max(1, min(max_hops, 3))):
        next_frontier: list[tuple[str, list[dict[str, Any]]]] = []
        for node_id, path in frontier:
            for edge in SYNTHETIC_GRAPH["edges"]:
                outgoing = edge["from"] == node_id
                incoming = edge["to"] == node_id
                if edge["type"] not in allowed or not ((direction in {"outgoing", "both"} and outgoing) or (direction in {"incoming", "both"} and incoming)):
                    continue
                other = edge["to"] if outgoing else edge["from"]
                step = {"edge_id": edge["id"], "edge_type": edge["type"], "from": edge["from"], "to": edge["to"]}
                candidate_path = [*path, step]
                if target_kind is None or entities[other]["kind"] == target_kind:
                    # Graph proximity score: direct neighbour > two-hop > three-hop.
                    found.append({"target_id": other, "target_label": entities[other]["label"], "path": candidate_path, "hops": len(candidate_path), "score": round(max(0.0, 0.90 - 0.15 * (len(candidate_path) - 1)), 4)})
                if other not in visited:
                    visited.add(other)
                    next_frontier.append((other, candidate_path))
        frontier = next_frontier
        if not frontier:
            break
    return sorted(found, key=lambda item: (-float(item["score"]), str(item["target_id"])))


def execute_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Execute all model-proposed searches against the synthetic graph only."""
    entity_results = []
    for item in plan.get("entity_queries", [])[:8]:
        if isinstance(item, dict):
            entity_results.append({"plan": item, "hits": _entity_search(str(item.get("query", "")), str(item.get("channel", "lexical")))})
    group_results = []
    for item in plan.get("group_queries", [])[:8]:
        if isinstance(item, dict):
            group_results.append({"plan": item, "hits": _group_search(str(item.get("query", "")))})
    edge_results = []
    for item in plan.get("edge_queries", [])[:8]:
        if isinstance(item, dict):
            edge_results.append({"plan": item, "hits": _edge_search(list(item.get("edge_types") or []), str(item.get("direction", "both")), int(item.get("max_hops", 1)))})
    path_results = []
    for item in plan.get("pair_and_path_queries", [])[:8]:
        if isinstance(item, dict):
            path_results.append({"plan": item, "hits": _edge_search(list(item.get("via_edge_types") or []), "both", int(item.get("max_hops", 1)), str(item.get("to_kind") or "") or None)})
    channel_best: dict[str, dict[str, dict[str, Any]]] = {}
    for search in entity_results:
        for hit in search["hits"]:
            channel = str(hit["channel"])
            current = channel_best.setdefault(channel, {}).get(str(hit["entity_id"]))
            if current is None or float(hit["score"]) > float(current["score"]):
                channel_best[channel][str(hit["entity_id"])] = hit
    fusion_inputs: dict[str, list[RetrievalHit]] = {}
    for channel, by_id in channel_best.items():
        fusion_inputs[channel] = [
            RetrievalHit(
                channel=channel,
                item_id=str(hit["entity_id"]),
                item_kind="entity",
                entity_id=str(hit["entity_id"]),
                label=str(hit["label"]),
                score=float(hit["score"]),
                metadata={"kind": hit["kind"]},
            )
            for hit in sorted(by_id.values(), key=lambda item: (-float(item["score"]), str(item["entity_id"])))
        ]
    fused = rrf_fuse(fusion_inputs, limit=20)
    fused_entities = [
        {
            "entity_id": hit.entity_id,
            "label": hit.label,
            "hybrid_rrf_score": round(hit.score, 6),
            "representative_channel": hit.channel,
            "metadata": dict(hit.metadata),
        }
        for hit in fused
    ]
    return {
        "entity_searches": entity_results,
        "fused_entity_candidates": fused_entities,
        "group_searches": group_results,
        "edge_searches": edge_results,
        "pair_and_path_searches": path_results,
    }


def _describe_search(name: str, plan_item: dict[str, Any]) -> str:
    if name == "entity_searches":
        return f"entity `{plan_item.get('query', '')}` via `{plan_item.get('channel', 'lexical')}`"
    if name == "group_searches":
        return f"group/community `{plan_item.get('query', '')}` (kind: `{plan_item.get('group_kind', 'any')}`)"
    if name == "edge_searches":
        return f"edges `{', '.join(plan_item.get('edge_types', []))}`; direction `{plan_item.get('direction', 'both')}`; max_hops `{plan_item.get('max_hops', 1)}`"
    return f"paths from `{plan_item.get('from', '')}` through `{', '.join(plan_item.get('via_edge_types', []))}` to kind `{plan_item.get('to_kind', 'any')}`; max_hops `{plan_item.get('max_hops', 1)}`"


def _format_hit(name: str, hit: dict[str, Any]) -> str:
    score = float(hit["score"])
    if name == "entity_searches":
        return f"`{hit['label']}` — score **{score:.4f}**; id `{hit['entity_id']}`; kind `{hit['kind']}`; channel `{hit['channel']}`"
    if name == "group_searches":
        return f"`{hit['label']}` — score **{score:.4f}**; id `{hit['group_id']}`; kind `{hit['kind']}`; members `{', '.join(hit['members'])}`"
    path = " → ".join(step["edge_type"] for step in hit["path"])
    return f"`{hit['target_label']}` — score **{score:.4f}**; id `{hit['target_id']}`; hops `{hit['hops']}`; path `{path}`"


def _markdown_report(report: dict[str, Any]) -> str:
    plan = report["llm_plan"]
    results = report["search_results"]
    input_data = plan.get("_meta", {}).get("input", EXAMPLE_INPUT)
    anchor = input_data.get("anchor_entity", {})
    edge = input_data.get("anchor_edge", {})
    lines = [
        "# Graph Search Results",
        "",
        "## User request",
        "",
        f"Find everything related to entity `{anchor.get('label', '')}` (type: `{anchor.get('entity_type', '')}`) and edge `{edge.get('edge_type', '')}` (direction: `{edge.get('direction', '')}`).",
        "",
    ]
    for name in ("entity_searches", "group_searches", "edge_searches", "pair_and_path_searches"):
        threshold = REPORT_THRESHOLDS[name]
        lines.extend([f"## {name.replace('_', ' ').title()}", ""])
        for index, item in enumerate(results.get(name, []), start=1):
            plan_item = item.get("plan", {})
            hits = sorted(item.get("hits", []), key=lambda hit: -float(hit.get("score", 0.0)))
            accepted = [hit for hit in hits if float(hit.get("score", 0.0)) >= threshold][:REPORT_LIMIT]
            lines.extend([
                f"### {index}. Searched: {_describe_search(name, plan_item)}",
                "",
            ])
            if accepted:
                for rank, hit in enumerate(accepted, start=1):
                    lines.append(f"{rank}. {_format_hit(name, hit)}")
            else:
                lines.append("No results.")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reuse-plan",
        type=Path,
        help="Reuse llm_plan from an existing synthetic report; makes no LLM request.",
    )
    args = parser.parse_args()
    if args.reuse_plan:
        prior = json.loads(args.reuse_plan.read_text(encoding="utf-8"))
        plan = prior.get("llm_plan")
        if not isinstance(plan, dict):
            parser.error("--reuse-plan must contain a JSON object field named llm_plan")
    else:
        plan = asyncio.run(run_probe())
    report = {
        "_meta": {"mode": "synthetic_no_database_probe", "sqlite_opened": False, "db_written": False},
        "synthetic_graph": SYNTHETIC_GRAPH,
        "llm_plan": plan,
        "search_results": execute_plan(plan),
    }
    output = ROOT / "data" / "memory_eval" / "synthetic_graph_search_probe.json"
    handoff = ROOT / "data" / "memory_eval" / "synthetic_graph_search_handoff.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    handoff.write_text(_markdown_report(report), encoding="utf-8")
    print(json.dumps({"json_report": str(output), "text_handoff": str(handoff), "plan": plan, "search_results": report["search_results"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
