"""Long multi-turn session scripts for chat memory eval."""

from __future__ import annotations

from typing import Any

# Core markers (short sessions + long sessions)
MEMEVAL_COLOR = "MEMEVAL_COLOR_Cobalt99"
MEMEVAL_DOG = "MEMEVAL_DOG_Rex887"
MEMEVAL_PLACE = "MEMEVAL_PLACE_Zephyr441"
MEMEVAL_BUDGET = "MEMEVAL_BUDGET_4200USD"
MEMEVAL_TRIP_MARKER = "MEMEVAL_TRIP_Tashkent88"

# Long-session / needle markers
MEMEVAL_HOTEL = "MEMEVAL_HOTEL_XK9921"
MEMEVAL_FLIGHT = "MEMEVAL_FLIGHT_SQ2288"
MEMEVAL_ALLERGY = "MEMEVAL_ALLERGY_shellfish"
MEMEVAL_SISTER = "MEMEVAL_SISTER_Alina445"
MEMEVAL_OFFICE = "MEMEVAL_OFFICE_14B_desk"
MEMEVAL_PROJECT = "MEMEVAL_PROJECT_Nebula42"
MEMEVAL_WIFI = "MEMEVAL_WIFI_NebulaGuest77"
MEMEVAL_PIN = "MEMEVAL_PIN_482913"
MEMEVAL_IBAN = "MEMEVAL_IBAN_UZ8612345678901234"
MEMEVAL_CAR = "MEMEVAL_CAR_01A777BA"
MEMEVAL_PHARMACY = "MEMEVAL_PHARMACY_Rx9912"
MEMEVAL_COACH = "MEMEVAL_COACH_Mira330"
MEMEVAL_REPO = "MEMEVAL_REPO_atlas-core"
MEMEVAL_VPN = "MEMEVAL_VPN_gw-east-19"
MEMEVAL_BIRTHDAY = "MEMEVAL_BDAY_March14"
MEMEVAL_PASSPORT = "MEMEVAL_PASS_AA9988771"
MEMEVAL_MEETING = "MEMEVAL_MEET_Thu1030"
MEMEVAL_CAFE_BETA = "MEMEVAL_PLACE_Beta7733"

Turn = tuple[str, list[dict[str, Any]]]


def _reply(text: str) -> list[dict[str, Any]]:
    return [{"role": "assistant", "content": text}]


def _noise_turns(prefix: str, count: int, *, start: int = 1) -> list[Turn]:
    """Generic filler turns that must not contain eval markers."""
    topics = [
        "weather forecast for the weekend",
        "best podcasts about productivity",
        "how to fix a slow laptop fan",
        "recipe ideas with chickpeas",
        "stretching routine after desk work",
        "comparison of noise-cancelling headphones",
        "tips for learning Spanish vocabulary",
        "calendar blocking for deep work",
        "packing list for a day hike",
        "simple home office lighting setup",
        "habit tracker app recommendations",
        "how to organize browser bookmarks",
        "morning routine without phone scrolling",
        "budget spreadsheet categories",
        "weekend farmers market checklist",
        "beginner guitar practice plan",
        "meal prep containers comparison",
        "standing desk mat options",
        "cloud backup strategy for photos",
        "note-taking method for meetings",
        "indoor plants that need low light",
        "quick bodyweight workout at home",
        "reading list for sci-fi novellas",
        "how to reduce inbox notifications",
        "timezone-friendly meeting scheduling",
    ]
    turns: list[Turn] = []
    for index in range(count):
        topic = topics[(start + index) % len(topics)]
        turns.append(
            (
                f"{prefix} turn {start + index}: tell me about {topic}.",
                _reply(
                    f"Here are a few practical notes on {topic}. "
                    "Nothing urgent — just general suggestions and examples."
                ),
            )
        )
    return turns


def long_trip_planning_session(
    *,
    color_marker: str,
    dog_marker: str,
    budget_marker: str,
    trip_marker: str,
) -> list[Turn]:
    """~20 turns: Tashkent trip planning with facts scattered in the middle."""
    turns: list[Turn] = [
        (
            f"Let's brainstorm a Tashkent trip {trip_marker}. Start with neighborhoods.",
            _reply(
                "Good start. For Tashkent I'd look at Yunusabad for calmer streets "
                "and the old city area for walking food routes."
            ),
        ),
        (
            "What museums are worth half a day?",
            _reply(
                "State Museum of History and Amir Timur Museum are common picks. "
                "Pair one museum morning with a cafe afternoon."
            ),
        ),
        *_noise_turns("trip", 3, start=1),
        (
            f"Personal note: my favorite color is {color_marker}. Keep that on file.",
            _reply(f"Saved personal preference — favorite color {color_marker}."),
        ),
        *_noise_turns("trip", 4, start=4),
        (
            f"Budget update for this trip: {budget_marker} total, flights included.",
            _reply(f"Noted trip budget {budget_marker} including flights."),
        ),
        *_noise_turns("trip", 3, start=8),
        (
            f"My dog is named {dog_marker}; I may need a pet sitter that week.",
            _reply(f"Dog name recorded as {dog_marker}. I can factor pet care into dates."),
        ),
        *_noise_turns("trip", 2, start=11),
        (
            f"Also store my birthday reminder: {MEMEVAL_BIRTHDAY}.",
            _reply(f"Birthday reminder saved: {MEMEVAL_BIRTHDAY}."),
        ),
        *_noise_turns("trip", 2, start=13),
        (
            f"Passport number for tickets: {MEMEVAL_PASSPORT}. Keep exact.",
            _reply(f"Passport number stored exactly as {MEMEVAL_PASSPORT}."),
        ),
        *_noise_turns("trip", 2, start=15),
        (
            "Draft a loose day-by-day outline with museums day 1 and cafes day 2.",
            _reply(
                f"Draft for {trip_marker}: Day 1 museums, Day 2 cafes, "
                "Day 3 open for shopping or a day trip."
            ),
        ),
    ]
    return turns


def long_work_session(
    *,
    office_marker: str,
    project_marker: str,
    sister_marker: str,
) -> list[Turn]:
    """~18 turns: work chat with office desk + project code buried."""
    turns: list[Turn] = [
        (
            "Morning standup notes: backend deploy is green, frontend has two UI bugs.",
            _reply("I'll track UI bugs separately. Backend deploy status logged."),
        ),
        *_noise_turns("work", 5, start=1),
        (
            f"I sit at {office_marker} — book the small room nearest that desk for reviews.",
            _reply(f"Desk location saved: {office_marker}."),
        ),
        *_noise_turns("work", 4, start=6),
        (
            f"Main initiative this quarter is {project_marker}. Use that codename in docs.",
            _reply(f"Project codename {project_marker} stored for doc references."),
        ),
        *_noise_turns("work", 4, start=10),
        (
            f"If I'm unreachable, my sister {sister_marker} can approve courier pickups.",
            _reply(f"Emergency contact note: sister {sister_marker}."),
        ),
        *_noise_turns("work", 2, start=14),
        (
            f"Primary git repo for this work is {MEMEVAL_REPO}.",
            _reply(f"Repo name saved: {MEMEVAL_REPO}."),
        ),
        *_noise_turns("work", 2, start=16),
        (
            f"Office VPN gateway to use: {MEMEVAL_VPN}.",
            _reply(f"VPN gateway recorded: {MEMEVAL_VPN}."),
        ),
        *_noise_turns("work", 1, start=18),
        (
            f"Standing sync with eng is {MEMEVAL_MEETING} every week.",
            _reply(f"Recurring meeting marker saved: {MEMEVAL_MEETING}."),
        ),
        (
            "Summarize open work threads from today in one short list.",
            _reply("Open threads: UI bugs, review room booking, project docs, courier contact."),
        ),
    ]
    return turns


def long_travel_logistics_session(
    *,
    hotel_marker: str,
    flight_marker: str,
    trip_marker: str,
) -> list[Turn]:
    """~22 turns: travel logistics; hotel code at turn ~14, flight at ~10."""
    turns: list[Turn] = [
        (
            f"Continue Tashkent logistics for {trip_marker}.",
            _reply("Continuing logistics planning for the trip."),
        ),
        *_noise_turns("travel", 6, start=1),
        (
            f"Flight booked — record locator {flight_marker} for check-in reminders.",
            _reply(f"Flight locator saved: {flight_marker}."),
        ),
        *_noise_turns("travel", 5, start=7),
        (
            f"Hotel confirmation code is {hotel_marker}. Need it for late arrival.",
            _reply(f"Hotel confirmation stored: {hotel_marker}."),
        ),
        *_noise_turns("travel", 2, start=12),
        (
            f"Hotel guest WiFi password is {MEMEVAL_WIFI}.",
            _reply(f"WiFi password stored: {MEMEVAL_WIFI}."),
        ),
        *_noise_turns("travel", 2, start=14),
        (
            f"Airport parking PIN for the lot: {MEMEVAL_PIN}.",
            _reply(f"Parking PIN saved: {MEMEVAL_PIN}."),
        ),
        *_noise_turns("travel", 2, start=16),
        (
            f"Rental car plate for pickup: {MEMEVAL_CAR}.",
            _reply(f"Car plate recorded: {MEMEVAL_CAR}."),
        ),
        *_noise_turns("travel", 1, start=18),
        (
            "List what still needs booking: airport transfer and museum tickets.",
            _reply("Still open: airport transfer and museum tickets."),
        ),
    ]
    return turns


def long_personal_health_session(*, allergy_marker: str) -> list[Turn]:
    """~16 turns: personal chat; allergy buried mid-session."""
    turns: list[Turn] = [
        (
            "Help me plan healthier lunches for the work week.",
            _reply("Consider grain bowls, lentil soups, and prep-friendly salads."),
        ),
        *_noise_turns("health", 5, start=1),
        (
            f"Important: I have {allergy_marker} allergy — avoid those ingredients.",
            _reply(f"Allergy on file: {allergy_marker}. I'll avoid suggesting those foods."),
        ),
        *_noise_turns("health", 3, start=6),
        (
            f"My pharmacy refill code is {MEMEVAL_PHARMACY}.",
            _reply(f"Pharmacy refill code saved: {MEMEVAL_PHARMACY}."),
        ),
        *_noise_turns("health", 2, start=9),
        (
            f"Personal trainer / coach name: {MEMEVAL_COACH}.",
            _reply(f"Coach name recorded: {MEMEVAL_COACH}."),
        ),
        *_noise_turns("health", 2, start=11),
        (
            "Give me a 3-day lunch rotation respecting my restrictions.",
            _reply("Rotation: day1 rice+veg, day2 chicken salad, day3 lentil stew."),
        ),
    ]
    return turns


def long_finance_session(*, iban_marker: str = MEMEVAL_IBAN) -> list[Turn]:
    """~16 turns: personal finance chat with IBAN buried mid-session."""
    turns: list[Turn] = [
        (
            "Help me organize monthly expense categories.",
            _reply("Split into housing, food, transport, subscriptions, and buffer."),
        ),
        *_noise_turns("finance", 5, start=1),
        (
            f"My transfer IBAN for reimbursements is {iban_marker}. Exact string.",
            _reply(f"IBAN stored exactly: {iban_marker}."),
        ),
        *_noise_turns("finance", 6, start=6),
        (
            "Draft a short checklist for month-end reconciliation.",
            _reply("Checklist: export statements, match transfers, flag unmatched."),
        ),
    ]
    return turns


def long_cafe_search_session(
    *,
    trip_marker: str,
    place_marker: str,
    tool_exchange: list[dict[str, Any]],
) -> list[Turn]:
    """~14 turns before cafe search; tool result turn at the end."""
    turns: list[Turn] = [
        (
            f"Research food scene for {trip_marker} before picking cafes.",
            _reply("Tashkent has strong plov spots, modern coffee places, and tea houses."),
        ),
        *_noise_turns("food", 8, start=1),
        (
            f"Now run the cafe search for Tashkent {trip_marker}.",
            [
                *tool_exchange,
                {"role": "assistant", "content": "Cafe list retrieved and archived."},
            ],
        ),
        *_noise_turns("food", 2, start=9),
        (
            f"Also note Cafe Beta place_id from the same search: {MEMEVAL_CAFE_BETA}.",
            _reply(f"Cafe Beta place_id noted as {MEMEVAL_CAFE_BETA}."),
        ),
        *_noise_turns("food", 1, start=11),
        (
            "Which of those cafes is best for a quiet laptop session?",
            _reply("I'd pick a smaller cafe off the main boulevard for quieter seating."),
        ),
    ]
    return turns
