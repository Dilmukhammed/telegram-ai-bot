"""Benchmark queries for tool search quality (agent-style discovery phrasing)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSearchCase:
    query: str
    expected: tuple[str, ...]
    tags: tuple[str, ...] = ()
    note: str = ""


# Queries mirror how the agent should phrase search_tools (capability, not user question).
TOOL_SEARCH_BENCHMARK: tuple[ToolSearchCase, ...] = (
    ToolSearchCase("web search on the internet", ("exa.web_search",)),
    ToolSearchCase("fetch webpage content from url", ("exa.web_fetch",)),
    ToolSearchCase("echo test message", ("echo.test",)),
    ToolSearchCase("Google Calendar events today", ("google.calendar.list_today",)),
    ToolSearchCase("Google Calendar upcoming events", ("google.calendar.list_upcoming",)),
    ToolSearchCase("create Google Calendar event", ("google.calendar.create_event", "google.calendar.quick_add_event")),
    ToolSearchCase("Google Calendar free busy availability", ("google.calendar.freebusy", "google.calendar.find_free_slots")),
    ToolSearchCase("search Google Calendar events", ("google.calendar.search_events",)),
    ToolSearchCase("Gmail inbox unread messages", ("google.gmail.list_inbox", "google.gmail.list_unread")),
    ToolSearchCase("search Gmail messages", ("google.gmail.search_messages",)),
    ToolSearchCase("send email via Gmail", ("google.gmail.send_message",)),
    ToolSearchCase("Gmail email attachment download", ("google.gmail.get_attachment",)),
    ToolSearchCase("Google Drive search files", ("google.drive.search_files",)),
    ToolSearchCase("download file from Google Drive", ("google.drive.download_file",)),
    ToolSearchCase("export Google Doc from Drive", ("google.drive.export_file",)),
    ToolSearchCase("Google Maps driving directions route", ("google.maps.compute_routes", "google.maps.travel_time")),
    ToolSearchCase("Google Maps nearby places search", ("google.maps.places_nearby_search",)),
    ToolSearchCase("geocode address to coordinates", ("google.maps.geocode",)),
    ToolSearchCase("reverse geocode coordinates to address", ("google.maps.reverse_geocode",)),
    ToolSearchCase("Google Sheets read cell values", ("google.sheets.get_values", "google.sheets.read_sheet")),
    ToolSearchCase("append rows Google Sheets", ("google.sheets.append_values",)),
    ToolSearchCase("Google Tasks list tasks", ("google.tasks.list_tasks", "google.tasks.list_default_tasks")),
    ToolSearchCase("Google OAuth connection status", ("google.auth.status",)),
    ToolSearchCase("Yandex Music search tracks", ("yandex.music.search",), tags=("yandex", "music")),
    ToolSearchCase("download Yandex Music track mp3", ("yandex.music.track_download",), tags=("yandex", "music")),
    ToolSearchCase("Yandex Music user playlists", ("yandex.music.users_playlists_list",), tags=("yandex", "music")),
    ToolSearchCase("Yandex OAuth connection status", ("yandex.auth.status",)),
    ToolSearchCase("read file from workspace sandbox", ("workspace.read_file",)),
    ToolSearchCase("write file to workspace", ("workspace.write_file",)),
    ToolSearchCase("grep search workspace files", ("workspace.grep",)),
    ToolSearchCase("workspace disk usage quota", ("workspace.usage",)),
    ToolSearchCase("send file to Telegram user", ("telegram.send_file",)),
    ToolSearchCase("load agent skill playbook", ("skills.load",)),
    ToolSearchCase("list available agent skills", ("skills.list",)),
    # Tag-scoped (agent often adds tags after first miss)
    ToolSearchCase("list calendar events", ("google.calendar.list_events",), tags=("google", "calendar")),
    ToolSearchCase("spreadsheet values", ("google.sheets.get_values",), tags=("google", "sheets")),
    ToolSearchCase("search tracks", ("yandex.music.search",), tags=("yandex", "music")),
    # Real agent phrasing from prod
    ToolSearchCase(
        "get user liked tracks or library tracks or favorite tracks",
        ("yandex.music.users_likes_tracks",),
        tags=("yandex", "music"),
        note="agent prod",
    ),
    ToolSearchCase(
        "liked tracks or user tracks",
        ("yandex.music.users_likes_tracks",),
        tags=("yandex", "music"),
        note="agent prod",
    ),
    # Wave 1 — domain search siblings
    ToolSearchCase("search tasks", ("google.tasks.search_tasks",)),
    ToolSearchCase("search", ("exa.web_search",)),
    ToolSearchCase("search workspace files", ("workspace.grep",)),
    ToolSearchCase("search drive files", ("google.drive.search_files",)),
    ToolSearchCase("search maps places nearby", ("google.maps.places_nearby_search", "google.maps.places_text_search")),
    # Wave 2 — antonym pairs
    ToolSearchCase(
        "liked albums favorites",
        ("yandex.music.users_likes_albums",),
        tags=("yandex", "music"),
    ),
    ToolSearchCase(
        "favorite artists library",
        ("yandex.music.users_likes_artists",),
        tags=("yandex", "music"),
    ),
    ToolSearchCase(
        "user disliked tracks not recommend",
        ("yandex.music.users_dislikes_tracks",),
        tags=("yandex", "music"),
    ),
    ToolSearchCase("list Google Tasklists", ("google.tasks.list_tasklists",)),
    ToolSearchCase(
        "read spreadsheet cell values only",
        ("google.sheets.get_values", "google.sheets.read_sheet"),
    ),
    # Wave 3 — list intent
    ToolSearchCase("list files", ("google.drive.list_files", "google.drive.list_folder")),
    ToolSearchCase("list events", ("google.calendar.list_events",)),
    ToolSearchCase("list", ("skills.list",)),
    ToolSearchCase(
        "list user playlists",
        ("yandex.music.users_playlists_list",),
        tags=("yandex", "music"),
    ),
    # Wave 4 — targeted aliases
    ToolSearchCase("find workspace files by pattern", ("workspace.find",)),
    # Multilingual discovery: direct user phrasing should still work if the
    # agent passes Russian text through unchanged.
    ToolSearchCase(
        "покажи мои плейлисты в Яндекс Музыке",
        ("yandex.music.users_playlists_list",),
    ),
    ToolSearchCase(
        "найди мои любимые треки в Яндекс Музыке",
        ("yandex.music.users_likes_tracks",),
    ),
    ToolSearchCase(
        "найди файлы по маске в рабочей папке",
        ("workspace.find",),
    ),
    ToolSearchCase(
        "покажи события календаря на сегодня",
        ("google.calendar.list_today",),
    ),
    # Terse/noisy agent discovery phrasing. The agent sometimes omits the
    # provider and relies on tags, or emits only a domain noun plus an action.
    ToolSearchCase(
        "music like track",
        ("yandex.music.users_likes_tracks_add",),
    ),
    ToolSearchCase(
        "like track",
        ("yandex.music.users_likes_tracks_add",),
        tags=("yandex", "music"),
    ),
    ToolSearchCase(
        "music add like to track",
        ("yandex.music.users_likes_tracks_add",),
    ),
    ToolSearchCase(
        "music unlike track",
        ("yandex.music.users_likes_tracks_remove",),
    ),
    ToolSearchCase(
        "music remove like from track",
        ("yandex.music.users_likes_tracks_remove",),
    ),
    ToolSearchCase(
        "music liked tracks",
        ("yandex.music.users_likes_tracks",),
    ),
    ToolSearchCase(
        "music favorites",
        ("yandex.music.users_likes_tracks",),
    ),
    ToolSearchCase(
        "music playlist",
        ("yandex.music.users_playlists_list",),
    ),
    ToolSearchCase(
        "playlist",
        ("yandex.music.users_playlists_list",),
        tags=("yandex", "music"),
    ),
    ToolSearchCase(
        "create music playlist",
        ("yandex.music.users_playlists_create",),
    ),
    ToolSearchCase(
        "delete music playlist",
        ("yandex.music.users_playlists_delete",),
    ),
    ToolSearchCase(
        "add track to music playlist",
        ("yandex.music.users_playlists_insert_track",),
    ),
    ToolSearchCase(
        "remove track from music playlist",
        ("yandex.music.users_playlists_delete_track",),
    ),
    ToolSearchCase(
        "search music track",
        ("yandex.music.search",),
    ),
    ToolSearchCase(
        "download music track",
        ("yandex.music.track_download",),
    ),
)
