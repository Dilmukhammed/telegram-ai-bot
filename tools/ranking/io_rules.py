from __future__ import annotations

from tools.ranking.constants import POSITIVE_LIKE_TOKENS


def io_action_bonus(query_tokens: set[str], tool_name: str, method: str) -> float:
    bonus = 0.0

    if query_tokens & {"download", "attachment"}:
        if "download" in method or method in {"get_attachment", "track_download"}:
            bonus += 2.5
        if method == "export_file":
            bonus += 2.0

    if "read" in query_tokens:
        if method.startswith("read_") or method in {"get_values", "read_sheet", "get_attachment"}:
            bonus += 2.0
        if method == "read_file":
            bonus += 3.0
        if method == "read_lines" and "lines" not in query_tokens:
            bonus -= 2.0
        if tool_name == "workspace.read_file" and query_tokens & {"spreadsheet", "sheets", "values", "cell", "cells"}:
            bonus -= 4.0

    if "write" in query_tokens and method == "write_file":
        bonus += 2.0

    if query_tokens & {"grep", "pattern"} and method == "grep":
        bonus += 3.0

    if query_tokens & {"usage", "quota", "disk", "storage"} and method == "usage":
        bonus += 3.0

    if "load" in query_tokens and tool_name == "skills.load":
        bonus += 5.0
    if "load" in query_tokens and tool_name == "skills.unload":
        bonus -= 5.0

    if query_tokens & {"routes", "directions", "driving", "travel"}:
        if method in {"compute_routes", "travel_time"}:
            bonus += 2.5

    if (
        "tracks" in query_tokens
        and method == "tracks"
        and "search" not in query_tokens
        and not query_tokens & POSITIVE_LIKE_TOKENS
        and "users" not in query_tokens
    ):
        bonus += 1.0

    if "export" in query_tokens and query_tokens & {"drive", "doc", "google"}:
        if method == "export_file":
            bonus += 4.0
        if ".auth." in tool_name:
            bonus -= 3.0

    return bonus
