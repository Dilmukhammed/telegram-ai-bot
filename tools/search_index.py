from __future__ import annotations

import re

_NAME_PART_RE = re.compile(r"[a-z0-9]+")

# Extra discovery phrases for embedding + keyword index (English agent queries).
SEGMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "search": ("find", "lookup", "query", "discover"),
    "download": ("fetch", "save", "file", "mp3", "audio"),
    "attachment": ("download", "file", "email", "message"),
    "status": ("connection", "connected", "oauth", "check", "linked"),
    "read": ("open", "view", "load", "get", "content"),
    "write": ("create", "save", "append", "update"),
    "grep": ("search", "find", "pattern", "scan", "files"),
    "usage": ("quota", "disk", "storage", "space", "limit"),
    "load": ("expand", "playbook", "skill", "open"),
    "geocode": ("address", "coordinates", "location", "lat", "lng"),
    "reverse": ("coordinates", "address", "lat", "lng", "geocode"),
    "tracks": ("track", "metadata", "by", "id"),
    "track": ("download", "mp3", "music", "audio", "file"),
    "list": ("show", "enumerate", "all"),
    "send": ("email", "message", "mail"),
    "export": ("download", "convert", "file", "pdf"),
    "connect": ("oauth", "link", "authorize"),
    "disconnect": ("revoke", "unlink", "logout"),
    "playlist": ("playlists", "user", "collection"),
    "playlists": ("playlist", "user", "collection", "list"),
    "inbox": ("mail", "messages", "email", "unread"),
    "unread": ("inbox", "mail", "messages"),
    "calendar": ("events", "schedule", "meeting"),
    "events": ("calendar", "schedule", "meeting"),
    "today": ("calendar", "events", "schedule"),
    "upcoming": ("calendar", "events", "schedule"),
    "spreadsheet": ("sheet", "cells", "values", "rows"),
    "values": ("cells", "spreadsheet", "sheet", "read"),
    "sheet": ("spreadsheet", "cells", "values"),
    "routes": ("directions", "driving", "travel", "maps"),
    "travel": ("directions", "duration", "route", "maps"),
    "maps": ("directions", "places", "route", "location"),
    "sandbox": ("workspace", "files", "server"),
    "workspace": ("sandbox", "files", "server"),
    "telegram": ("send", "user", "chat", "file"),
    "navigate": ("open", "visit", "browse", "load", "url", "goto"),
    "snapshot": ("screenshot", "page", "dom", "accessibility", "refs"),
    "screenshot": ("capture", "image", "png", "page", "photo"),
    "session": ("browser", "steel", "tab", "open", "close"),
}

# Hand-tuned phrases for tools that lose to noisy neighbors in hybrid search.
TOOL_ALIASES: dict[str, tuple[str, ...]] = {
    "google.gmail.get_attachment": (
        "download gmail email attachment file message",
    ),
    "google.gmail.send_message": (
        "send compose email gmail message",
    ),
    "google.gmail.search_messages": (
        "search find query gmail email messages",
    ),
    "google.gmail.list_inbox": (
        "inbox mail messages list unread gmail",
    ),
    "google.gmail.list_unread": (
        "unread inbox mail messages gmail",
    ),
    "google.drive.search_files": (
        "search find query drive google files documents pdf spreadsheet metadata",
        "not download not export not list folder",
    ),
    "google.drive.download_file": (
        "download file from google drive binary pdf bytes file_ref",
        "not export google doc not gmail attachment not music mp3",
    ),
    "google.drive.export_file": (
        "export google doc sheets slides pdf csv file from drive",
        "not download binary not search not list",
    ),
    "google.tasks.search_tasks": (
        "search find query google tasks todos title notes",
        "not exa web not calendar events not drive files",
    ),
    "google.tasks.list_tasks": (
        "list google tasks todos task list due dates shopping",
        "not tasklists not calendar not drive not create delete",
    ),
    "google.tasks.list_default_tasks": (
        "list my todos default tasks my tasks open items",
        "not tasklists not calendar events not drive files",
    ),
    "google.calendar.list_today": (
        "calendar events today schedule meetings agenda today",
        "not tasks todos not auth oauth not upcoming week",
    ),
    "google.calendar.list_upcoming": (
        "upcoming calendar events next schedule week ahead",
        "not today only not tasks todos not auth oauth",
    ),
    "google.calendar.freebusy": (
        "free busy availability calendar busy blocks time range",
        "not tasks not create event not auth oauth",
    ),
    "google.calendar.find_free_slots": (
        "find free slots meeting availability bookable time calendar",
        "not tasks not freebusy raw not auth oauth",
    ),
    "google.calendar.search_events": (
        "search find calendar events meetings query schedule",
        "not tasks not drive not web exa",
    ),
    "google.sheets.append_values": (
        "append add rows end sheet spreadsheet log new record",
        "not read get values not update overwrite cells not clear",
    ),
    "workspace.find": (
        "find glob pattern workspace files directories path locate",
        "not grep regex text search not read write content",
    ),
    "telegram.send_file": (
        "send file document photo video to telegram user chat",
        "not gmail email not drive download export",
    ),
    "google.auth.status": (
        "google oauth connection status check connected linked account",
    ),
    "google.auth.connect_url": (
        "google oauth connect authorize link url login",
    ),
    "workspace.read_file": (
        "read open view load file workspace sandbox server",
    ),
    "workspace.write_file": (
        "write create save append file workspace sandbox",
    ),
    "workspace.grep": (
        "grep search find pattern text workspace files",
    ),
    "workspace.usage": (
        "workspace disk quota storage usage limit sandbox",
    ),
    "yandex.music.search": (
        "search find query lookup tracks albums artists yandex music catalog",
    ),
    "yandex.music.tracks": (
        "get track metadata by id fetch single track not search",
    ),
    "yandex.music.track_download": (
        "download mp3 track file yandex music audio send telegram",
    ),
    "yandex.music.users_playlists_list": (
        "list user playlists yandex music collection",
    ),
    "yandex.music.users_likes_tracks": (
        "liked tracks favorites favorite library user collection "
        "heart tracks list get fetch me nravitsya",
    ),
    "yandex.music.users_likes_albums": (
        "liked albums favorites favorite library user collection heart",
    ),
    "yandex.music.users_likes_artists": (
        "liked artists favorites favorite library user collection heart",
    ),
    "yandex.music.users_dislikes_tracks": (
        "disliked tracks not recommend ban hidden user collection",
    ),
    "yandex.auth.status": (
        "yandex music oauth connection status check connected linked",
    ),
    "google.maps.compute_routes": (
        "driving directions route travel time maps navigation",
    ),
    "google.maps.travel_time": (
        "driving directions route duration travel time maps",
    ),
    "google.maps.reverse_geocode": (
        "reverse geocode coordinates to address lat lng maps",
    ),
    "google.maps.geocode": (
        "geocode address to coordinates lat lng maps",
    ),
    "skills.load": (
        "load expand open agent skill playbook workflow",
    ),
    "skills.unload": (
        "unload collapse close agent skill playbook",
    ),
    "google.sheets.get_values": (
        "read spreadsheet cell values rows columns sheets",
    ),
    "google.calendar.list_events": (
        "list calendar events schedule meetings range",
    ),
    "google.drive.list_files": (
        "list files folders drive google recent starred shared",
    ),
    "google.drive.list_folder": (
        "list folder files drive google directory",
    ),
    "browser.session_open": (
        "open browser login google website interactive hitl steel session",
        "not exa web search not google oauth api",
    ),
    "browser.session_close": (
        "close browser session release save profile persist cookies",
    ),
    "browser.navigate": (
        "open url in browser navigate website page goto",
        "not exa web_search not google maps",
    ),
    "browser.snapshot": (
        "browser accessibility snapshot refs clickable elements page tree",
    ),
    "browser.screenshot": (
        "web page screenshot image capture png browser",
        "not pdf.render not maps static",
    ),
    "browser.profile.status": (
        "browser profile login status cookies steel saved session",
    ),
    "browser.profile.import_cookies": (
        "import chrome cookies seed google login editthiscookie cookie-editor json",
        "not google oauth api connect_google not exa search",
    ),
    "browser.tabs.list": (
        "list browser tabs open pages windows",
        "not session_open not exa",
    ),
    "browser.download": (
        "download file from browser page click save file_ref",
        "not drive download not gmail attachment",
    ),
    "browser.evaluate": (
        "run javascript evaluate js in browser page",
        "not snapshot click not python code",
    ),
    "agent.wait": (
        "sleep pause delay wait seconds backoff retry upload processing",
        "not browser.wait selector not exa search",
    ),
}


def tool_method_name(tool_name: str) -> str:
    return tool_name.rsplit(".", 1)[-1]


def tool_name_segments(tool_name: str) -> list[str]:
    tail = tool_method_name(tool_name)
    return _NAME_PART_RE.findall(tail.lower())


def enriched_index_text(
    *,
    name: str,
    description: str,
    tags: tuple[str, ...] = (),
    examples: tuple[str, ...] = (),
) -> str:
    parts: list[str] = [name, description, *tags, *examples]
    parts.extend(TOOL_ALIASES.get(name, ()))
    for segment in tool_name_segments(name):
        parts.extend(SEGMENT_ALIASES.get(segment, ()))
    return " ".join(parts).lower()

