"""Benchmark cases for end-to-end chat memory eval (agent + real LLM)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from eval_chat_memory_sessions import (
    MEMEVAL_ALLERGY,
    MEMEVAL_BIRTHDAY,
    MEMEVAL_BUDGET,
    MEMEVAL_CAFE_BETA,
    MEMEVAL_CAR,
    MEMEVAL_COACH,
    MEMEVAL_COLOR,
    MEMEVAL_DOG,
    MEMEVAL_FLIGHT,
    MEMEVAL_HOTEL,
    MEMEVAL_IBAN,
    MEMEVAL_MEETING,
    MEMEVAL_OFFICE,
    MEMEVAL_PASSPORT,
    MEMEVAL_PHARMACY,
    MEMEVAL_PIN,
    MEMEVAL_PLACE,
    MEMEVAL_PROJECT,
    MEMEVAL_REPO,
    MEMEVAL_SISTER,
    MEMEVAL_TRIP_MARKER,
    MEMEVAL_VPN,
    MEMEVAL_WIFI,
    long_cafe_search_session,
    long_finance_session,
    long_personal_health_session,
    long_travel_logistics_session,
    long_trip_planning_session,
    long_work_session,
)

# Re-export for tests
MEMEVAL_COLOR_Cobalt99 = MEMEVAL_COLOR  # backwards compat alias in tests if any


@dataclass(frozen=True)
class MemoryEvalCase:
    id: str
    question: str
    must_include: tuple[str, ...]
    required_tools: tuple[str, ...] = ()
    require_any_tools: tuple[str, ...] = ()
    must_not_include: tuple[str, ...] = ()
    ground_truth: str = ""


SeedFn = Callable[[Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class MemoryEvalScenario:
    case: MemoryEvalCase
    seed: SeedFn


async def _seed_long_trip_session(fixture) -> dict[str, Any]:
    session_id = fixture.seed_session_turns(
        long_trip_planning_session(
            color_marker=MEMEVAL_COLOR,
            dog_marker=MEMEVAL_DOG,
            budget_marker=MEMEVAL_BUDGET,
            trip_marker=MEMEVAL_TRIP_MARKER,
        ),
        trace_every=5,
    )
    fixture.open_fresh_active_session()
    fixture.reindex()
    return {"archived_session_id": session_id, "turn_count": 20}


async def _seed_color_from_long(fixture) -> dict[str, Any]:
    return await _seed_long_trip_session(fixture)


async def _seed_dog_from_long(fixture) -> dict[str, Any]:
    return await _seed_long_trip_session(fixture)


async def _seed_budget_from_long(fixture) -> dict[str, Any]:
    return await _seed_long_trip_session(fixture)


async def _seed_multi_fact_long(fixture) -> dict[str, Any]:
    return await _seed_long_trip_session(fixture)


async def _seed_place_id_long(fixture) -> dict[str, Any]:
    payload = {
        "tool_name": "exa.web_search",
        "ok": True,
        "result": {
            "items": [
                {"name": "Cafe Alpha", "place_id": MEMEVAL_PLACE},
                {"name": "Cafe Beta", "place_id": "place_wrong_999"},
            ],
        },
    }
    record = fixture.insert_tool_result(
        turn=12,
        summary=f"Tashkent cafes including Cafe Alpha place_id {MEMEVAL_PLACE}",
        payload=payload,
    )
    archived = fixture.archived_tool_json(record)
    session_id = fixture.seed_session_turns(
        long_cafe_search_session(
            trip_marker=MEMEVAL_TRIP_MARKER,
            place_marker=MEMEVAL_PLACE,
            tool_exchange=fixture.use_tool_exchange(
                tool_name="exa.web_search",
                tool_args={"query": f"Tashkent cafes {MEMEVAL_TRIP_MARKER}"},
                tool_content=archived,
                call_id="memeval_place_long",
            ),
        ),
        trace_every=4,
    )
    fixture.open_fresh_active_session()
    fixture.reindex()
    return {"archived_session_id": session_id, "tool_ref": record.display_ref}


async def _seed_archived_session_summary_long(fixture) -> dict[str, Any]:
    session_id = fixture.seed_session_turns(
        long_trip_planning_session(
            color_marker=MEMEVAL_COLOR,
            dog_marker=MEMEVAL_DOG,
            budget_marker=MEMEVAL_BUDGET,
            trip_marker=MEMEVAL_TRIP_MARKER,
        ),
        trace_every=1,
    )
    fixture.open_fresh_active_session()
    await fixture.summarize_archived(session_id)
    fixture.reindex()
    return {"archived_session_id": session_id}


async def _seed_hotel_needle_long(fixture) -> dict[str, Any]:
    session_id = fixture.seed_session_turns(
        long_travel_logistics_session(
            hotel_marker=MEMEVAL_HOTEL,
            flight_marker=MEMEVAL_FLIGHT,
            trip_marker=MEMEVAL_TRIP_MARKER,
        ),
        trace_every=5,
    )
    fixture.open_fresh_active_session()
    fixture.reindex()
    return {"archived_session_id": session_id}


async def _seed_flight_needle_long(fixture) -> dict[str, Any]:
    return await _seed_hotel_needle_long(fixture)


async def _seed_work_office_long(fixture) -> dict[str, Any]:
    session_id = fixture.seed_session_turns(
        long_work_session(
            office_marker=MEMEVAL_OFFICE,
            project_marker=MEMEVAL_PROJECT,
            sister_marker=MEMEVAL_SISTER,
        ),
        trace_every=4,
    )
    fixture.open_fresh_active_session()
    fixture.reindex()
    return {"archived_session_id": session_id}


async def _seed_allergy_second_session(fixture) -> dict[str, Any]:
    await _seed_work_office_long(fixture)
    session_id = fixture.seed_session_turns(
        long_personal_health_session(allergy_marker=MEMEVAL_ALLERGY),
        trace_every=4,
    )
    fixture.open_fresh_active_session()
    fixture.reindex()
    return {"archived_session_id": session_id}


async def _seed_project_cross_session(fixture) -> dict[str, Any]:
    work = await _seed_work_office_long(fixture)
    fixture.seed_session_turns(
        long_personal_health_session(allergy_marker=MEMEVAL_ALLERGY),
        trace_every=4,
    )
    fixture.open_fresh_active_session()
    fixture.reindex()
    return work


async def _seed_sister_from_work(fixture) -> dict[str, Any]:
    return await _seed_work_office_long(fixture)


async def _seed_repo_from_work(fixture) -> dict[str, Any]:
    return await _seed_work_office_long(fixture)


async def _seed_vpn_from_work(fixture) -> dict[str, Any]:
    return await _seed_work_office_long(fixture)


async def _seed_meeting_from_work(fixture) -> dict[str, Any]:
    return await _seed_work_office_long(fixture)


async def _seed_wifi_from_travel(fixture) -> dict[str, Any]:
    return await _seed_hotel_needle_long(fixture)


async def _seed_pin_from_travel(fixture) -> dict[str, Any]:
    return await _seed_hotel_needle_long(fixture)


async def _seed_car_from_travel(fixture) -> dict[str, Any]:
    return await _seed_hotel_needle_long(fixture)


async def _seed_birthday_from_trip(fixture) -> dict[str, Any]:
    return await _seed_long_trip_session(fixture)


async def _seed_passport_from_trip(fixture) -> dict[str, Any]:
    return await _seed_long_trip_session(fixture)


async def _seed_pharmacy_from_health(fixture) -> dict[str, Any]:
    return await _seed_allergy_second_session(fixture)


async def _seed_coach_from_health(fixture) -> dict[str, Any]:
    return await _seed_allergy_second_session(fixture)


async def _seed_finance_iban(fixture) -> dict[str, Any]:
    session_id = fixture.seed_session_turns(
        long_finance_session(iban_marker=MEMEVAL_IBAN),
        trace_every=4,
    )
    fixture.open_fresh_active_session()
    fixture.reindex()
    return {"archived_session_id": session_id}


async def _seed_cafe_beta_from_search(fixture) -> dict[str, Any]:
    return await _seed_place_id_long(fixture)


async def _seed_triple_fact_trip(fixture) -> dict[str, Any]:
    return await _seed_long_trip_session(fixture)


async def _seed_work_and_health_combo(fixture) -> dict[str, Any]:
    return await _seed_allergy_second_session(fixture)


CHAT_MEMORY_BENCHMARK: tuple[MemoryEvalScenario, ...] = (
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_color",
            question=(
                "What is my favorite color? It was buried in a long earlier chat — "
                "search past conversations, do not guess."
            ),
            must_include=(MEMEVAL_COLOR,),
            require_any_tools=("chat.search", "chat.turns.read", "chat.session.summary"),
        ),
        seed=_seed_color_from_long,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_dog_name",
            question="What is my dog's name from our long past Tashkent planning chat?",
            must_include=(MEMEVAL_DOG,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_dog_from_long,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="exact_place_id_tool_result",
            question=(
                "From our long cafe research chat: what is the exact place_id "
                "string for Cafe Alpha? Use archived tool results for the precise value."
            ),
            must_include=(MEMEVAL_PLACE,),
            required_tools=("tool_results.get",),
            require_any_tools=("chat.search", "tool_results.get"),
            must_not_include=("place_wrong_999",),
        ),
        seed=_seed_place_id_long,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_trip_budget",
            question="How much travel budget did I mention in the long Tashkent planning conversation?",
            must_include=("4200",),
            require_any_tools=("chat.search", "chat.turns.read", "chat.session.summary"),
        ),
        seed=_seed_budget_from_long,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="archived_session_overview",
            question=(
                "Briefly summarize what we discussed in the previous long chat session. "
                "Use session summary or search — do not invent dates or facts."
            ),
            must_include=("Tashkent", MEMEVAL_TRIP_MARKER),
            require_any_tools=("chat.session.summary", "chat.search", "chat.turns.read"),
        ),
        seed=_seed_archived_session_summary_long,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="multi_fact_turn_range",
            question=(
                "From the long Tashkent planning chat: what is my favorite color AND my dog's name? "
                "Both were stored in that session."
            ),
            must_include=(MEMEVAL_COLOR, MEMEVAL_DOG),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_multi_fact_long,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="needle_hotel_code",
            question=(
                "What is my hotel confirmation code from the long travel logistics chat? "
                "Exact string only."
            ),
            must_include=(MEMEVAL_HOTEL,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_hotel_needle_long,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="needle_flight_locator",
            question="What flight locator did I save in the travel logistics session?",
            must_include=(MEMEVAL_FLIGHT,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_flight_needle_long,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="work_desk_location",
            question="Which desk should meeting rooms be booked near, from the long work chat?",
            must_include=(MEMEVAL_OFFICE,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_work_office_long,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="cross_session_allergy",
            question=(
                "I had a long personal health chat after work sessions — "
                "what food allergy did I mention there?"
            ),
            must_include=(MEMEVAL_ALLERGY,),
            require_any_tools=("chat.search", "chat.turns.read", "chat.sessions.list"),
        ),
        seed=_seed_allergy_second_session,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="cross_session_project_codename",
            question=(
                "From archived work chats (not the health chat): "
                "what is the project codename I asked you to use in docs?"
            ),
            must_include=(MEMEVAL_PROJECT,),
            must_not_include=(MEMEVAL_ALLERGY,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_project_cross_session,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_sister_contact",
            question="Who can approve courier pickups if I'm unreachable, from the work chat?",
            must_include=(MEMEVAL_SISTER,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_sister_from_work,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_git_repo",
            question="What is the primary git repo name from our long work chat?",
            must_include=(MEMEVAL_REPO,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_repo_from_work,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_vpn_gateway",
            question="Which office VPN gateway did I ask you to use?",
            must_include=(MEMEVAL_VPN,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_vpn_from_work,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_standing_meeting",
            question="What is the standing eng sync marker from the work session?",
            must_include=(MEMEVAL_MEETING,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_meeting_from_work,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="needle_wifi_password",
            question="What hotel guest WiFi password did I save in travel logistics?",
            must_include=(MEMEVAL_WIFI,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_wifi_from_travel,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="needle_parking_pin",
            question="What airport parking PIN did I store in the travel chat?",
            must_include=(MEMEVAL_PIN,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_pin_from_travel,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="needle_car_plate",
            question="What rental car plate did I record for pickup?",
            must_include=(MEMEVAL_CAR,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_car_from_travel,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_birthday",
            question="What birthday reminder marker did I store in the Tashkent planning chat?",
            must_include=(MEMEVAL_BIRTHDAY,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_birthday_from_trip,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_passport_number",
            question="What exact passport number did I give for tickets in the trip chat?",
            must_include=(MEMEVAL_PASSPORT,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_passport_from_trip,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_pharmacy_code",
            question="What pharmacy refill code did I mention in the personal health chat?",
            must_include=(MEMEVAL_PHARMACY,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_pharmacy_from_health,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_coach_name",
            question="What is my coach / trainer name from the health session?",
            must_include=(MEMEVAL_COACH,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_coach_from_health,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_iban",
            question="What exact IBAN did I store for reimbursements in the finance chat?",
            must_include=(MEMEVAL_IBAN,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_finance_iban,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="recall_cafe_beta_place",
            question="From the cafe research chat, what place_id did I note for Cafe Beta?",
            must_include=(MEMEVAL_CAFE_BETA,),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_cafe_beta_from_search,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="triple_fact_trip",
            question=(
                "From the long Tashkent planning chat: favorite color, dog name, AND trip budget. "
                "Search carefully for all three."
            ),
            must_include=(MEMEVAL_COLOR, MEMEVAL_DOG, "4200"),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_triple_fact_trip,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="combo_desk_and_allergy",
            question=(
                "Across archived chats: which desk for meeting rooms, and what food allergy "
                "did I mention later in the health chat?"
            ),
            must_include=(MEMEVAL_OFFICE, MEMEVAL_ALLERGY),
            require_any_tools=("chat.search", "chat.turns.read", "chat.sessions.list"),
        ),
        seed=_seed_work_and_health_combo,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="combo_hotel_and_flight",
            question=(
                "From travel logistics: give me both the hotel confirmation code and the "
                "flight locator. Exact strings."
            ),
            must_include=(MEMEVAL_HOTEL, MEMEVAL_FLIGHT),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_hotel_needle_long,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="combo_wifi_and_pin",
            question="From travel logistics: hotel WiFi password AND airport parking PIN?",
            must_include=(MEMEVAL_WIFI, MEMEVAL_PIN),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_wifi_from_travel,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="combo_repo_and_vpn",
            question="From the work chat: primary git repo name and VPN gateway?",
            must_include=(MEMEVAL_REPO, MEMEVAL_VPN),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_repo_from_work,
    ),
    MemoryEvalScenario(
        case=MemoryEvalCase(
            id="combo_passport_and_birthday",
            question="From trip planning: passport number and birthday reminder marker?",
            must_include=(MEMEVAL_PASSPORT, MEMEVAL_BIRTHDAY),
            require_any_tools=("chat.search", "chat.turns.read"),
        ),
        seed=_seed_passport_from_trip,
    ),
)
