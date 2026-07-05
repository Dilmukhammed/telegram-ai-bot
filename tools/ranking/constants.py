from __future__ import annotations

from dataclasses import dataclass

# Shared query token sets used across ranking rule modules.
POSITIVE_LIKE_TOKENS = frozenset(
    {"like", "liked", "likes", "favorite", "favorites", "library", "heart"}
)
NEGATIVE_LIKE_TOKENS = frozenset(
    {"dislike", "disliked", "dislikes", "recommend", "ban", "hidden"}
)
YANDEX_LIKES_ENTITIES: tuple[str, ...] = ("tracks", "albums", "artists", "clips", "playlists")
YANDEX_LIKES_WRITE_TOKENS = frozenset({"add", "remove"})
CALENDAR_TOKENS = frozenset(
    {"calendar", "events", "event", "today", "upcoming", "schedule", "meeting"}
)
DOMAIN_SEARCH_TOKENS = frozenset(
    {
        "gmail",
        "drive",
        "calendar",
        "workspace",
        "grep",
        "maps",
        "places",
        "sheets",
        "spreadsheet",
        "music",
        "yandex",
    }
)
OAUTH_INTENT_TOKENS = frozenset(
    {"status", "connection", "connected", "oauth", "auth", "linked"}
)

SEARCH_SIBLINGS: frozenset[str] = frozenset(
    {
        "exa.web_search",
        "google.calendar.search_events",
        "google.drive.search_files",
        "google.gmail.search_messages",
        "google.maps.places_nearby_search",
        "google.maps.places_text_search",
        "google.tasks.search_tasks",
        "yandex.music.search",
        "yandex.music.search_suggest",
        "workspace.find",
        "workspace.grep",
    }
)

DOMAIN_SEARCH_WINNERS: dict[str, tuple[str, ...]] = {
    "gmail": ("google.gmail.search_messages",),
    "drive": ("google.drive.search_files",),
    "calendar": ("google.calendar.search_events",),
    "tasks": ("google.tasks.search_tasks",),
    "maps": (
        "google.maps.places_text_search",
        "google.maps.places_nearby_search",
    ),
    "places": (
        "google.maps.places_text_search",
        "google.maps.places_nearby_search",
    ),
    "nearby": ("google.maps.places_nearby_search",),
    "music": ("yandex.music.search",),
    "yandex": ("yandex.music.search",),
    "workspace": ("workspace.grep",),
    "grep": ("workspace.grep",),
    "web": ("exa.web_search",),
    "internet": ("exa.web_search",),
}


@dataclass(frozen=True)
class AntonymRuleSpec:
    id: str
    query_tokens: frozenset[str]
    boost_methods: tuple[str, ...] = ()
    boost_tool_names: tuple[str, ...] = ()
    penalty_methods: tuple[str, ...] = ()
    penalty_tool_names: tuple[str, ...] = ()
    penalty_substrings: tuple[str, ...] = ()
    unless_query_tokens: frozenset[str] = frozenset()
    all_query_tokens: frozenset[str] = frozenset()
    any_query_tokens: frozenset[str] = frozenset()
    boost_amount: float = 3.0
    penalty_amount: float = 3.0


ANTONYM_RULES: tuple[AntonymRuleSpec, ...] = (
    AntonymRuleSpec(
        id="geocode_vs_reverse",
        query_tokens=frozenset({"reverse"}),
        boost_methods=("reverse_geocode",),
        penalty_methods=("geocode",),
        boost_amount=5.0,
        penalty_amount=5.0,
    ),
    AntonymRuleSpec(
        id="sheets_read_vs_append",
        query_tokens=frozenset({"values", "spreadsheet", "sheets", "cell", "cells"}),
        boost_methods=("get_values", "read_sheet"),
        penalty_methods=("append_values",),
        unless_query_tokens=frozenset({"append", "rows"}),
        boost_amount=4.0,
        penalty_amount=3.5,
    ),
    AntonymRuleSpec(
        id="sheets_read_vs_workspace",
        query_tokens=frozenset({"spreadsheet", "sheets", "values", "cell", "cells"}),
        unless_query_tokens=frozenset({"workspace", "sandbox", "append", "rows"}),
        penalty_tool_names=("workspace.read_file", "workspace.read_lines"),
        penalty_amount=4.0,
    ),
    AntonymRuleSpec(
        id="sheets_append_vs_read",
        query_tokens=frozenset({"append", "rows", "sheets", "spreadsheet"}),
        all_query_tokens=frozenset({"append"}),
        boost_methods=("append_values",),
        penalty_methods=("get_values", "read_sheet"),
        boost_amount=5.0,
        penalty_amount=3.5,
    ),
    AntonymRuleSpec(
        id="tasks_list_vs_tasklists",
        query_tokens=frozenset({"tasks", "task", "list"}),
        boost_methods=("list_tasks", "list_default_tasks"),
        penalty_methods=("list_tasklists",),
        unless_query_tokens=frozenset({"tasklists", "tasklist"}),
        boost_amount=3.0,
        penalty_amount=2.5,
    ),
    AntonymRuleSpec(
        id="tasks_tasklists_vs_tasks",
        query_tokens=frozenset({"tasklists", "tasklist", "list"}),
        boost_methods=("list_tasklists",),
        penalty_methods=("list_tasks", "list_default_tasks"),
        boost_amount=3.0,
        penalty_amount=2.5,
    ),
    AntonymRuleSpec(
        id="track_download_vs_info",
        query_tokens=frozenset({"download"}),
        any_query_tokens=frozenset({"mp3", "music", "yandex", "track"}),
        unless_query_tokens=frozenset({"drive", "gmail", "attachment", "workspace"}),
        boost_methods=("track_download",),
        penalty_methods=("tracks_download_info",),
        boost_amount=3.5,
        penalty_amount=3.0,
    ),
    AntonymRuleSpec(
        id="drive_download_vs_music",
        query_tokens=frozenset({"download", "file"}),
        any_query_tokens=frozenset({"drive"}),
        unless_query_tokens=frozenset({"mp3", "music", "yandex"}),
        boost_methods=("download_file",),
        penalty_methods=("track_download", "tracks_download_info"),
        boost_amount=3.0,
        penalty_amount=3.0,
    ),
    AntonymRuleSpec(
        id="gmail_attachment_vs_music",
        query_tokens=frozenset({"download", "attachment"}),
        any_query_tokens=frozenset({"gmail", "email", "mail"}),
        boost_methods=("get_attachment",),
        penalty_methods=("track_download", "tracks_download_info"),
        boost_amount=3.0,
        penalty_amount=3.0,
    ),
    AntonymRuleSpec(
        id="telegram_send_vs_gmail",
        query_tokens=frozenset({"telegram", "file", "send"}),
        all_query_tokens=frozenset({"telegram"}),
        boost_tool_names=("telegram.send_file",),
        penalty_methods=("send_message",),
        boost_amount=4.0,
        penalty_amount=2.5,
    ),
    AntonymRuleSpec(
        id="gmail_send_vs_telegram",
        query_tokens=frozenset({"send", "email", "gmail", "mail"}),
        all_query_tokens=frozenset({"send"}),
        boost_methods=("send_message",),
        boost_tool_names=("google.gmail.send_message",),
        penalty_tool_names=("telegram.send_file",),
        unless_query_tokens=frozenset({"telegram"}),
        boost_amount=2.5,
        penalty_amount=2.5,
    ),
    AntonymRuleSpec(
        id="google_auth_vs_yandex",
        query_tokens=OAUTH_INTENT_TOKENS | frozenset({"google"}),
        all_query_tokens=frozenset({"google"}),
        boost_tool_names=("google.auth.status",),
        penalty_substrings=("yandex.auth.",),
        boost_amount=2.0,
        penalty_amount=4.0,
    ),
    AntonymRuleSpec(
        id="yandex_auth_vs_google",
        query_tokens=OAUTH_INTENT_TOKENS | frozenset({"yandex"}),
        all_query_tokens=frozenset({"yandex"}),
        boost_tool_names=("yandex.auth.status",),
        penalty_substrings=("google.auth.",),
        boost_amount=2.0,
        penalty_amount=4.0,
    ),
)

# Backward-compatible export for docs / introspection.
ANTONYM_RULE_SPECS: tuple[dict[str, object], ...] = tuple(
    {
        "id": rule.id,
        "query_tokens": rule.query_tokens,
        "boost_methods": rule.boost_methods,
        "boost_tool_names": rule.boost_tool_names,
        "penalty_methods": rule.penalty_methods,
        "penalty_tool_names": rule.penalty_tool_names,
        "penalty_substrings": rule.penalty_substrings,
        "unless_query_tokens": rule.unless_query_tokens,
        "all_query_tokens": rule.all_query_tokens,
        "any_query_tokens": rule.any_query_tokens,
    }
    for rule in ANTONYM_RULES
)


@dataclass(frozen=True)
class ListIntentRuleSpec:
    id: str
    required_tokens: frozenset[str]
    any_tokens: frozenset[str] = frozenset()
    all_tokens: frozenset[str] = frozenset()
    unless_tokens: frozenset[str] = frozenset()
    boost_methods: tuple[str, ...] = ()
    boost_tool_names: tuple[str, ...] = ()
    penalty_methods: tuple[str, ...] = ()
    penalty_tool_names: tuple[str, ...] = ()
    penalty_prefixes: tuple[str, ...] = ()
    penalty_method_substrings: tuple[str, ...] = ()
    boost_amount: float = 3.5
    penalty_amount: float = 3.0


LIST_INTENT_RULES: tuple[ListIntentRuleSpec, ...] = (
    ListIntentRuleSpec(
        id="list_drive_files",
        required_tokens=frozenset({"list"}),
        any_tokens=frozenset({"files", "file", "folder", "drive"}),
        boost_methods=("list_files", "list_folder", "list_recent", "list_starred", "list_shared_with_me"),
        boost_tool_names=(
            "google.drive.list_files",
            "google.drive.list_folder",
            "google.drive.list_recent",
        ),
        penalty_methods=("create_tasklist", "delete_tasklist", "update_tasklist", "patch_tasklist"),
        penalty_prefixes=("google.tasks.",),
        boost_amount=4.0,
        penalty_amount=3.5,
    ),
    ListIntentRuleSpec(
        id="list_calendar_events",
        required_tokens=frozenset({"list"}),
        any_tokens=frozenset({"events", "event", "calendar"}),
        unless_tokens=frozenset({"tasks", "task", "tasklists", "tasklist"}),
        boost_methods=("list_events", "list_today", "list_upcoming", "list_calendars"),
        penalty_prefixes=("google.tasks.",),
        boost_amount=4.0,
        penalty_amount=3.5,
    ),
    ListIntentRuleSpec(
        id="list_gmail_inbox",
        required_tokens=frozenset({"list"}),
        any_tokens=frozenset({"inbox", "unread", "mail", "gmail", "messages"}),
        unless_tokens=frozenset({"send", "tasks", "task"}),
        boost_methods=("list_inbox", "list_unread", "list_messages", "list_threads"),
        penalty_methods=("send_message", "create_tasklist", "delete_tasklist"),
        boost_amount=4.0,
        penalty_amount=3.0,
    ),
    ListIntentRuleSpec(
        id="list_user_playlists",
        required_tokens=frozenset({"list"}),
        any_tokens=frozenset({"playlist", "playlists"}),
        all_tokens=frozenset({"user"}),
        boost_methods=("users_playlists_list",),
        penalty_method_substrings=("playlists",),
        boost_amount=4.0,
        penalty_amount=2.5,
    ),
    ListIntentRuleSpec(
        id="list_skills",
        required_tokens=frozenset({"list"}),
        any_tokens=frozenset({"skills", "skill", "agent", "playbook"}),
        boost_tool_names=("skills.list",),
        penalty_prefixes=("google.tasks.",),
        boost_amount=3.0,
        penalty_amount=3.0,
    ),
)

LIST_ONLY_NOISE_METHODS: frozenset[str] = frozenset(
    {
        "create_tasklist",
        "delete_tasklist",
        "update_tasklist",
        "patch_tasklist",
        "get_tasklist",
    }
)

LIST_INTENT_SPECS: tuple[dict[str, object], ...] = tuple(
    {
        "id": rule.id,
        "required_tokens": rule.required_tokens,
        "any_tokens": rule.any_tokens,
        "all_tokens": rule.all_tokens,
        "unless_tokens": rule.unless_tokens,
        "boost_methods": rule.boost_methods,
        "boost_tool_names": rule.boost_tool_names,
        "penalty_methods": rule.penalty_methods,
        "penalty_prefixes": rule.penalty_prefixes,
    }
    for rule in LIST_INTENT_RULES
)

SEARCH_SIBLING_PENALTY = 2.5
DOMAIN_SEARCH_WINNER_BOOST = 2.0

YANDEX_LIKES_BOOST = 3.0
YANDEX_DISLIKES_PENALTY = 4.0
YANDEX_LIKES_WRITE_PENALTY = 2.5
YANDEX_GENERIC_TRACKS_PENALTY = 2.5
