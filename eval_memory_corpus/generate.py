"""Generate ~200 sessions and 1000+ E2E memory cases."""

from __future__ import annotations

import hashlib
import itertools
import random
from typing import Any

from eval_memory_corpus.schema import (
    CorpusCase,
    CorpusFact,
    CorpusPack,
    CorpusSession,
    CorpusTurn,
)

_NOISE_TOPICS = (
    "weekend weather",
    "podcast recommendations",
    "laptop fan noise",
    "chickpea recipes",
    "desk stretches",
    "noise-cancelling headphones",
    "Spanish flashcards",
    "deep work calendar blocks",
    "day hike packing",
    "home office lighting",
    "habit trackers",
    "browser bookmarks",
    "morning routines",
    "spreadsheet categories",
    "farmers market list",
    "guitar practice",
    "meal prep containers",
    "standing desk mats",
    "photo backups",
    "meeting notes",
    "low-light plants",
    "bodyweight workouts",
    "sci-fi novellas",
    "inbox notifications",
    "timezone meetings",
    "tea vs coffee",
    "keyboard layouts",
    "commute options",
    "laundry schedules",
    "password managers",
)

_FACT_KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "color": (
        "favorite color",
        (
            "What is my favorite color from past chats?",
            "Which favorite color did I ask you to remember?",
        ),
    ),
    "dog": (
        "dog name",
        (
            "What is my dog's name from earlier chats?",
            "Which dog name did I store previously?",
        ),
    ),
    "hotel": (
        "hotel confirmation code",
        (
            "What hotel confirmation code did I save?",
            "Exact hotel confirmation string from travel chats?",
        ),
    ),
    "flight": (
        "flight locator",
        (
            "What flight locator did I record?",
            "Which flight record locator is in memory?",
        ),
    ),
    "budget": (
        "trip budget",
        (
            "How much trip budget did I mention?",
            "What travel budget marker did I store?",
        ),
    ),
    "office": (
        "office desk",
        (
            "Which desk should meeting rooms be booked near?",
            "What office desk location did I save?",
        ),
    ),
    "project": (
        "project codename",
        (
            "What project codename should docs use?",
            "Which project codename did I store?",
        ),
    ),
    "allergy": (
        "food allergy",
        (
            "What food allergy did I mention?",
            "Which allergy should meal plans avoid?",
        ),
    ),
    "wifi": (
        "wifi password",
        (
            "What WiFi password did I save?",
            "Guest WiFi password from past chats?",
        ),
    ),
    "pin": (
        "parking pin",
        (
            "What parking PIN did I store?",
            "Airport parking PIN from memory?",
        ),
    ),
    "iban": (
        "iban",
        (
            "What IBAN did I store for reimbursements?",
            "Exact IBAN from finance chats?",
        ),
    ),
    "car": (
        "car plate",
        (
            "What rental car plate did I record?",
            "Car plate from travel logistics?",
        ),
    ),
    "pharmacy": (
        "pharmacy code",
        (
            "What pharmacy refill code did I mention?",
            "Pharmacy code from health chats?",
        ),
    ),
    "coach": (
        "coach name",
        (
            "What is my coach name from past chats?",
            "Trainer / coach name stored earlier?",
        ),
    ),
    "repo": (
        "git repo",
        (
            "What primary git repo name did I save?",
            "Repo name from work chats?",
        ),
    ),
    "vpn": (
        "vpn gateway",
        (
            "Which VPN gateway did I ask you to use?",
            "Office VPN gateway from memory?",
        ),
    ),
    "birthday": (
        "birthday",
        (
            "What birthday reminder did I store?",
            "Birthday marker from past chats?",
        ),
    ),
    "passport": (
        "passport number",
        (
            "What passport number did I give for tickets?",
            "Exact passport marker from trip chats?",
        ),
    ),
    "sister": (
        "sister contact",
        (
            "Who can approve courier pickups if I'm unreachable?",
            "Sister contact name from work chats?",
        ),
    ),
    "meeting": (
        "standing meeting",
        (
            "What standing meeting marker did I save?",
            "Eng sync meeting marker from work chats?",
        ),
    ),
    "place": (
        "place_id",
        (
            "What exact place_id did I store for Cafe Alpha?",
            "Cafe Alpha place_id from archived tool results?",
        ),
    ),
    "phone": (
        "phone number",
        (
            "What phone number did I save?",
            "Contact phone from past chats?",
        ),
    ),
    "email": (
        "email address",
        (
            "What email address did I store?",
            "Contact email from memory?",
        ),
    ),
    "city": (
        "home city",
        (
            "What home city did I mention?",
            "Which city did I say I live in?",
        ),
    ),
    "nickname": (
        "nickname",
        (
            "What nickname did I ask you to use?",
            "Preferred nickname from past chats?",
        ),
    ),
}

_TOPIC_POOLS: dict[str, tuple[str, ...]] = {
    "travel": ("hotel", "flight", "budget", "wifi", "pin", "car", "passport", "city"),
    "work": ("office", "project", "repo", "vpn", "sister", "meeting", "email"),
    "health": ("allergy", "pharmacy", "coach", "birthday"),
    "finance": ("iban", "budget", "pin"),
    "personal": ("color", "dog", "nickname", "birthday", "phone", "city", "email"),
    "food": ("allergy", "place", "city"),
    "tech": ("repo", "vpn", "wifi", "email"),
    "family": ("sister", "dog", "birthday", "phone"),
    "shopping": ("budget", "pin", "car"),
    "calendar": ("meeting", "birthday", "flight"),
}


def _token(seed: str, n: int = 6) -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest().upper()
    return digest[:n]


def _marker(kind: str, session_idx: int, fact_idx: int, suffix: str = "") -> str:
    token = _token(f"{kind}:{session_idx}:{fact_idx}:{suffix}")
    return f"MEMEVAL_{kind.upper()}_{token}{suffix}"


def _noise_turn(rng: random.Random, prefix: str, index: int) -> CorpusTurn:
    topic = _NOISE_TOPICS[index % len(_NOISE_TOPICS)]
    return CorpusTurn(
        user=f"{prefix} note {index}: tell me about {topic}.",
        assistant=(
            f"Here are a few practical notes on {topic}. "
            "Nothing urgent — general suggestions only."
        ),
    )


def _fact_statement(kind: str, marker: str) -> tuple[str, str]:
    label = _FACT_KINDS[kind][0]
    user = f"Remember this: my {label} is {marker}."
    assistant = f"Saved {label}: {marker}."
    if kind == "allergy":
        user = f"Important: I have {marker} allergy — avoid those ingredients."
        assistant = f"Allergy on file: {marker}."
    elif kind == "place":
        user = f"Cafe Alpha place_id from search is {marker}. Keep exact."
        assistant = f"Cafe Alpha place_id stored: {marker}."
    elif kind == "budget":
        user = f"Trip budget update: {marker} total."
        assistant = f"Budget saved: {marker}."
    elif kind == "hotel":
        user = f"Hotel confirmation code is {marker}."
        assistant = f"Hotel confirmation stored: {marker}."
    elif kind == "flight":
        user = f"Flight locator is {marker}."
        assistant = f"Flight locator saved: {marker}."
    elif kind == "iban":
        user = f"My transfer IBAN is {marker}. Exact string."
        assistant = f"IBAN stored exactly: {marker}."
    return user, assistant


def _make_fact(
    *,
    kind: str,
    session_idx: int,
    fact_idx: int,
    turn: int,
    status: str = "active",
    superseded_by: str | None = None,
    suffix: str = "",
) -> CorpusFact:
    marker = _marker(kind, session_idx, fact_idx, suffix=suffix)
    label, templates = _FACT_KINDS[kind]
    return CorpusFact(
        id=f"f_{session_idx}_{fact_idx}_{kind}{suffix}",
        kind=kind,
        marker=marker,
        value=label,
        turn=turn,
        status=status,  # type: ignore[arg-type]
        superseded_by=superseded_by,
        question_templates=templates,
    )


def _build_session(
    *,
    session_idx: int,
    length: str,
    topics: tuple[str, ...],
    contradiction: bool,
    with_tool: bool,
    rng: random.Random,
) -> CorpusSession:
    kind_pool = list(
        dict.fromkeys(
            kind
            for topic in topics
            for kind in _TOPIC_POOLS.get(topic, ("color", "city"))
        )
    )
    rng.shuffle(kind_pool)

    if length == "short":
        target_turns = rng.randint(3, 8)
        fact_count = rng.randint(1, 2)
    elif length == "medium":
        target_turns = rng.randint(15, 30)
        fact_count = rng.randint(3, 6)
    else:
        target_turns = rng.randint(40, 70)
        fact_count = rng.randint(6, 10)

    if contradiction:
        fact_count = max(fact_count, 2)

    turns: list[CorpusTurn] = []
    facts: list[CorpusFact] = []
    fact_kinds = kind_pool[:fact_count] if kind_pool else ["color"]
    while len(fact_kinds) < fact_count:
        fact_kinds.append(rng.choice(list(_FACT_KINDS)))

    # Opening
    turns.append(
        CorpusTurn(
            user=f"Let's continue our {topics[0]} chat (session {session_idx}).",
            assistant=f"Continuing {topics[0]} discussion for session {session_idx}.",
        )
    )

    fact_slots = sorted(
        {
            max(2, int((i + 1) * target_turns / (fact_count + 1)))
            for i in range(fact_count)
        }
    )
    while len(fact_slots) < fact_count:
        fact_slots.append(min(target_turns - 1, fact_slots[-1] + 2))

    contradiction_kind = fact_kinds[0] if contradiction else None
    tool_kind_index = 0 if with_tool and "place" in fact_kinds else -1
    if with_tool and tool_kind_index < 0:
        fact_kinds[0] = "place"
        tool_kind_index = 0

    noise_i = 1
    fact_i = 0
    while len(turns) < target_turns:
        next_turn_no = len(turns) + 1
        if fact_i < len(fact_slots) and next_turn_no >= fact_slots[fact_i]:
            kind = fact_kinds[fact_i]
            if contradiction and kind == contradiction_kind and fact_i == 0:
                old = _make_fact(
                    kind=kind,
                    session_idx=session_idx,
                    fact_idx=fact_i,
                    turn=next_turn_no,
                    status="superseded",
                    suffix="OLD",
                )
                user, assistant = _fact_statement(kind, old.marker)
                turns.append(CorpusTurn(user=user, assistant=assistant, fact_ids=(old.id,)))
                facts.append(old)
                # fill a bit of noise then supersede
                for _ in range(rng.randint(2, 5)):
                    if len(turns) >= target_turns - 2:
                        break
                    turns.append(_noise_turn(rng, topics[0], noise_i))
                    noise_i += 1
                new_turn = len(turns) + 1
                new = _make_fact(
                    kind=kind,
                    session_idx=session_idx,
                    fact_idx=fact_i,
                    turn=new_turn,
                    status="active",
                    suffix="NEW",
                )
                # link supersession
                facts[-1] = CorpusFact(
                    id=old.id,
                    kind=old.kind,
                    marker=old.marker,
                    value=old.value,
                    turn=old.turn,
                    status="superseded",
                    superseded_by=new.id,
                    question_templates=old.question_templates,
                )
                label = _FACT_KINDS[kind][0]
                user2 = (
                    f"Actually no — ignore the previous {label}. "
                    f"The correct one is {new.marker}."
                )
                assistant2 = f"Updated {label} to {new.marker}."
                turns.append(
                    CorpusTurn(user=user2, assistant=assistant2, fact_ids=(new.id,))
                )
                facts.append(new)
            elif with_tool and fact_i == tool_kind_index:
                fact = _make_fact(
                    kind="place",
                    session_idx=session_idx,
                    fact_idx=fact_i,
                    turn=next_turn_no,
                )
                wrong = f"place_wrong_{_token(f'wrong:{session_idx}', 4)}"
                payload = {
                    "tool_name": "exa.web_search",
                    "ok": True,
                    "result": {
                        "items": [
                            {"name": "Cafe Alpha", "place_id": fact.marker},
                            {"name": "Cafe Beta", "place_id": wrong},
                        ]
                    },
                    "summary": f"Cafe Alpha place_id {fact.marker}",
                }
                turns.append(
                    CorpusTurn(
                        user=f"Search cafes and keep Cafe Alpha place_id exact.",
                        assistant="Cafe list retrieved and archived.",
                        fact_ids=(fact.id,),
                        tool_result=payload,
                    )
                )
                facts.append(fact)
            else:
                fact = _make_fact(
                    kind=kind,
                    session_idx=session_idx,
                    fact_idx=fact_i,
                    turn=next_turn_no,
                )
                user, assistant = _fact_statement(kind, fact.marker)
                # topic switch flavor on long sessions
                if length == "long" and fact_i == fact_count // 2 and len(topics) > 1:
                    user = (
                        f"Switching topics to {topics[1]} for a moment. "
                        + user
                    )
                turns.append(
                    CorpusTurn(user=user, assistant=assistant, fact_ids=(fact.id,))
                )
                facts.append(fact)
            fact_i += 1
            continue

        turns.append(_noise_turn(rng, topics[0], noise_i))
        noise_i += 1

    active = [f for f in facts if f.status == "active"]
    summary_bits = ", ".join(f"{f.kind}={f.marker}" for f in active[:6])
    title = f"{topics[0].title()} session {session_idx}"
    summary = (
        f"Session about {', '.join(topics)}. Key stored facts: {summary_bits}."
    )
    return CorpusSession(
        slug=f"sess_{session_idx:03d}_{topics[0]}",
        topic_tags=topics,
        turns=tuple(turns),
        facts=tuple(facts),
        summary=summary,
        title=title,
        started_offset_hours=session_idx * 3,
    )


def _question_for_fact(fact: CorpusFact, session: CorpusSession) -> str:
    templates = fact.question_templates or (
        f"What is my {fact.value} from past chats?",
    )
    template = templates[hash(fact.id) % len(templates)]
    return (
        f"{template} It was in the '{session.title}' chat — "
        "search past conversations, do not invent details."
    )


def _emit_cases(sessions: list[CorpusSession], rng: random.Random) -> list[CorpusCase]:
    cases: list[CorpusCase] = []
    by_slug = {s.slug: s for s in sessions}
    active_facts: list[tuple[CorpusSession, CorpusFact]] = []
    for session in sessions:
        for fact in session.facts:
            if fact.status == "active":
                active_facts.append((session, fact))

    # Single-fact + needle
    for session, fact in active_facts:
        difficulty = "needle" if len(session.turns) >= 35 else "easy"
        cases.append(
            CorpusCase(
                id=f"recall_{fact.id}",
                question=_question_for_fact(fact, session),
                must_include=(fact.marker,),
                seed_sessions=(session.slug,),
                difficulty=difficulty,  # type: ignore[arg-type]
                tier="full",
                expected_session_slug=session.slug,
                require_any_tools=("chat.search", "chat.turns.read", "chat.session.summary"),
            )
        )

    # Contradiction latest-wins (~80 cases from ~20 sessions via paraphrases)
    contradiction_prompts = (
        "What is my current {value}? I changed it earlier — use the latest statement, not the old one.",
        "I corrected my {value} later in chat. What is the up-to-date value now?",
        "Ignore any older {value} I mentioned first. What did I say it is after the correction?",
        "Latest-wins: after I said 'actually no', what is my {value}?",
    )
    for session in sessions:
        superseded = [f for f in session.facts if f.status == "superseded" and f.superseded_by]
        for old in superseded:
            new = next((f for f in session.facts if f.id == old.superseded_by), None)
            if new is None:
                continue
            for vi, prompt in enumerate(contradiction_prompts):
                cases.append(
                    CorpusCase(
                        id=f"contradiction_v{vi}_{new.id}",
                        question=prompt.format(value=new.value),
                        must_include=(new.marker,),
                        must_not_include=(old.marker,),
                        seed_sessions=(session.slug,),
                        difficulty="contradiction",
                        tier="full",
                        expected_session_slug=session.slug,
                    )
                )

    # Tool-ref cases
    for session in sessions:
        for turn in session.turns:
            if not turn.tool_result:
                continue
            fact_id = turn.fact_ids[0] if turn.fact_ids else None
            fact = next((f for f in session.facts if f.id == fact_id), None)
            if fact is None:
                continue
            cases.append(
                CorpusCase(
                    id=f"toolref_{fact.id}",
                    question=(
                        "From the cafe search chat: what is the exact place_id for Cafe Alpha? "
                        "Use archived tool results for the precise value."
                    ),
                    must_include=(fact.marker,),
                    must_not_include=("place_wrong_",),
                    required_tools=("tool_results.get",),
                    require_any_tools=("chat.search", "tool_results.get"),
                    seed_sessions=(session.slug,),
                    difficulty="tool_ref",
                    tier="full",
                    expected_session_slug=session.slug,
                    expected_tool_ref_fact=fact.id,
                )
            )

    # Multi-fact same session (bounded)
    multi_count = 0
    for session in sessions:
        actives = [f for f in session.facts if f.status == "active"]
        if len(actives) < 2:
            continue
        combos = list(itertools.combinations(actives[:5], 2))
        if len(actives) >= 3:
            combos.extend(list(itertools.combinations(actives[:5], 3))[:3])
        rng.shuffle(combos)
        for combo in combos[:4]:
            markers = tuple(f.marker for f in combo)
            labels = " and ".join(f.value for f in combo)
            cases.append(
                CorpusCase(
                    id=f"multi_{session.slug}_{'_'.join(f.kind for f in combo)}",
                    question=(
                        f"From '{session.title}': what are my {labels}? "
                        "Search carefully for all of them."
                    ),
                    must_include=markers,
                    seed_sessions=(session.slug,),
                    difficulty="multi_fact",
                    tier="full",
                    expected_session_slug=session.slug,
                )
            )
            multi_count += 1
            if multi_count >= 200:
                break
        if multi_count >= 200:
            break

    # Cross-session
    for i in range(0, len(active_facts) - 1, 3):
        left_s, left_f = active_facts[i]
        right_s, right_f = active_facts[i + 1]
        if left_s.slug == right_s.slug:
            continue
        cases.append(
            CorpusCase(
                id=f"cross_{left_f.id}_{right_f.id}",
                question=(
                    f"Across archived chats: what is my {left_f.value} and my {right_f.value}? "
                    "They were stored in different sessions."
                ),
                must_include=(left_f.marker, right_f.marker),
                seed_sessions=(left_s.slug, right_s.slug),
                difficulty="cross_session",
                tier="full",
                require_any_tools=(
                    "chat.search",
                    "chat.turns.read",
                    "chat.sessions.list",
                ),
            )
        )

    # Overview
    for session in sessions:
        if len(session.turns) < 10:
            continue
        marker = next((f.marker for f in session.facts if f.status == "active"), session.slug)
        cases.append(
            CorpusCase(
                id=f"overview_{session.slug}",
                question=(
                    f"Briefly summarize what we discussed in session '{session.title}'. "
                    "Use session summary or search — do not invent dates."
                ),
                must_include=(marker,),
                seed_sessions=(session.slug,),
                difficulty="overview",
                tier="full",
                require_any_tools=(
                    "chat.session.summary",
                    "chat.search",
                    "chat.turns.read",
                ),
                expected_session_slug=session.slug,
            )
        )

    # World-noise subset: seed many sessions, ask one fact
    world_slugs = tuple(s.slug for s in sessions)
    for session, fact in active_facts[:: max(1, len(active_facts) // 20)][:20]:
        cases.append(
            CorpusCase(
                id=f"world_{fact.id}",
                question=(
                    f"Among many past chats, what is my {fact.value}? "
                    f"Look carefully; marker starts with MEMEVAL_."
                ),
                must_include=(fact.marker,),
                seed_sessions=world_slugs,
                difficulty="world",
                tier="full",
                expected_session_slug=session.slug,
                world_seed=True,
            )
        )

    # Deduplicate by id
    unique: dict[str, CorpusCase] = {}
    for case in cases:
        unique[case.id] = case
    ordered = list(unique.values())
    rng.shuffle(ordered)

    # Ensure >= 1000 by adding paraphrased single-fact variants if needed
    variant_i = 0
    while len(ordered) < 1000 and active_facts:
        session, fact = active_facts[variant_i % len(active_facts)]
        ordered.append(
            CorpusCase(
                id=f"recall_v{variant_i}_{fact.id}",
                question=(
                    f"Quick memory check: remind me of my {fact.value} "
                    f"from '{session.title}'. Exact stored value."
                ),
                must_include=(fact.marker,),
                seed_sessions=(session.slug,),
                difficulty="easy",
                tier="full",
                expected_session_slug=session.slug,
            )
        )
        variant_i += 1

    # Smoke tier: first 40 diverse cases
    smoke_ids: set[str] = set()
    for difficulty in (
        "easy",
        "needle",
        "multi_fact",
        "contradiction",
        "cross_session",
        "tool_ref",
        "overview",
    ):
        for case in ordered:
            if case.difficulty == difficulty and case.id not in smoke_ids:
                smoke_ids.add(case.id)
                if len(smoke_ids) >= 40:
                    break
        if len(smoke_ids) >= 40:
            break

    final: list[CorpusCase] = []
    for case in ordered:
        tier = "smoke" if case.id in smoke_ids else "full"
        final.append(
            CorpusCase(
                id=case.id,
                question=case.question,
                must_include=case.must_include,
                must_not_include=case.must_not_include,
                required_tools=case.required_tools,
                require_any_tools=case.require_any_tools,
                seed_sessions=case.seed_sessions,
                difficulty=case.difficulty,
                tier=tier,  # type: ignore[arg-type]
                expected_session_slug=case.expected_session_slug,
                expected_tool_ref_fact=case.expected_tool_ref_fact,
                world_seed=case.world_seed,
            )
        )
    return final


def generate_pack(*, seed: int = 42) -> CorpusPack:
    rng = random.Random(seed)
    topic_names = list(_TOPIC_POOLS.keys())
    sessions: list[CorpusSession] = []

    # 40 short, 80 medium, 60 long, 20 contradiction (overlap with lengths)
    plan: list[tuple[str, bool, bool]] = []
    plan.extend([("short", False, False) for _ in range(40)])
    plan.extend([("medium", False, idx % 10 == 0) for idx in range(80)])
    plan.extend([("long", False, idx % 8 == 0) for idx in range(60)])
    for idx in range(20):
        length = "medium" if idx % 2 == 0 else "long"
        plan.append((length, True, False))

    # Trim/pad to ~200
    plan = plan[:200]
    while len(plan) < 200:
        plan.append(("medium", False, False))

    for idx, (length, contradiction, with_tool) in enumerate(plan, start=1):
        topics = tuple(rng.sample(topic_names, k=rng.randint(1, 3)))
        sessions.append(
            _build_session(
                session_idx=idx,
                length=length,
                topics=topics,
                contradiction=contradiction,
                with_tool=with_tool,
                rng=rng,
            )
        )

    cases = _emit_cases(sessions, rng)
    return CorpusPack(
        version="1",
        sessions=tuple(sessions),
        cases=tuple(cases),
        meta={
            "seed": seed,
            "session_count": len(sessions),
            "case_count": len(cases),
            "smoke_count": sum(1 for c in cases if c.tier == "smoke"),
            "fact_count": sum(len(s.facts) for s in sessions),
        },
    )
