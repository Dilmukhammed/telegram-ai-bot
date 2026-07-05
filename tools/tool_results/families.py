from __future__ import annotations

SUMMARY_RELIABILITY_WARNING = (
    "Summary is approximate — do not rely on it for exact quotes, IDs, counts, URLs, "
    "or precision-critical decisions. Use tool_results.get with this ref for the full "
    "stored result."
)


def tool_family(tool_name: str) -> str:
    if tool_name.startswith("exa."):
        return "exa"
    if tool_name.startswith("yandex."):
        return "yandex"
    if tool_name.startswith("google."):
        return "google"
    if tool_name.startswith("workspace."):
        return "workspace"
    if tool_name.startswith("skills."):
        return "skills"
    if tool_name.startswith("telegram."):
        return "telegram"
    return "default"


def summarize_system_prompt(family: str) -> str:
    common = (
        "You summarize tool results for an AI agent. Output 2-5 concise sentences in the "
        "same language as the payload when obvious. Preserve key facts: names, IDs, counts, "
        "URLs, errors, and actionable outcomes. No markdown fences."
    )
    by_family = {
        "exa": (
            f"{common} Focus on search hits: page titles, URLs, and what each source says. "
            "Note lyrics/themes/mood when the query is about songs."
        ),
        "yandex": (
            f"{common} Focus on tracks/playlists: titles, artists, track IDs, counts, "
            "library actions, auth status, and API errors."
        ),
        "google": (
            f"{common} Focus on emails/events/files/tasks: senders, subjects, dates, "
            "action items, and operation outcomes."
        ),
        "workspace": (
            f"{common} Focus on paths, file sizes, operation success, and short content previews."
        ),
        "skills": (
            f"{common} Focus on which skill loaded/unloaded and operational status."
        ),
        "telegram": (
            f"{common} Focus on delivery status and file metadata."
        ),
        "default": common,
    }
    return by_family.get(family, by_family["default"])
