import json

from agent.tool_search_hints import (
    build_search_tools_hint,
    build_skill_load_hint,
    group_key_for_tool_name,
    maybe_append_skill_load_hint,
    maybe_append_tool_hints,
    maybe_append_tool_search_hint,
    tags_for_tool_name,
)
from skills.pending import mark_skill_loaded, reset_skill_run_state
from skills.usage_tracker import record_tool_use, reset_skill_usage_tracker


def _prime_distinct_tools(*tool_names: str) -> None:
    reset_skill_usage_tracker()
    for tool_name in tool_names:
        record_tool_use(tool_name)


def _prime_maps_for_hint() -> None:
    _prime_distinct_tools(
        "google.maps.geocode",
        "google.maps.directions",
        "google.maps.travel_time",
    )


def test_tags_for_tool_name():
    assert tags_for_tool_name("google.calendar.list_events") == ("google", "calendar")
    assert tags_for_tool_name("google.gmail.send") == ("google", "gmail")
    assert tags_for_tool_name("google.auth.status") == ("google", "auth")
    assert tags_for_tool_name("google.drive.list_files") == ("google", "drive")
    assert tags_for_tool_name("google.sheets.read_sheet") == ("google", "sheets")
    assert tags_for_tool_name("exa.web_search") == ("web", "search")
    assert tags_for_tool_name("workspace.stat") == ("workspace", "filesystem")
    assert tags_for_tool_name("telegram.send_file") == ("telegram", "bot")
    assert tags_for_tool_name("echo.test") is None


def test_group_key_for_tool_name():
    assert group_key_for_tool_name("google.tasks.list") == "google|tasks"


def test_maybe_append_hint_once_per_group():
    hinted: set[str] = set()
    ok_result = json.dumps(
        {
            "ok": True,
            "tool_name": "google.calendar.list_events",
            "result": {"events": []},
        }
    )
    first = maybe_append_tool_search_hint(ok_result, hinted_groups=hinted)
    first_payload = json.loads(first)
    assert "search_tools_hint" in first_payload
    assert "calendar" in first_payload["search_tools_hint"]
    assert "google|calendar" in hinted

    second = maybe_append_tool_search_hint(
        json.dumps(
            {
                "ok": True,
                "tool_name": "google.calendar.create_event",
                "result": {},
            }
        ),
        hinted_groups=hinted,
    )
    second_payload = json.loads(second)
    assert "search_tools_hint" not in second_payload


def test_no_hint_on_failure():
    hinted: set[str] = set()
    result = maybe_append_tool_search_hint(
        json.dumps({"ok": False, "tool_name": "google.calendar.list_events", "error": "x"}),
        hinted_groups=hinted,
    )
    assert "search_tools_hint" not in json.loads(result)
    assert not hinted


def test_no_hint_for_unknown_tool():
    hinted: set[str] = set()
    result = maybe_append_tool_search_hint(
        json.dumps({"ok": True, "tool_name": "echo.test", "result": "pong"}),
        hinted_groups=hinted,
    )
    assert "search_tools_hint" not in json.loads(result)


def test_maybe_append_hint_for_workspace():
    hinted: set[str] = set()
    result = maybe_append_tool_search_hint(
        json.dumps({"ok": True, "tool_name": "workspace.read_file", "result": {"ok": True}}),
        hinted_groups=hinted,
    )
    payload = json.loads(result)
    assert "search_tools_hint" in payload
    assert "workspace" in payload["search_tools_hint"]
    assert "filesystem" in payload["search_tools_hint"]


def test_build_search_tools_hint_includes_tags():
    hint = build_search_tools_hint(("google", "maps"))
    assert '"google"' in hint
    assert '"maps"' in hint
    assert "search_tools" in hint
    assert "accurate" in hint


def test_no_skill_load_hint_on_first_tool():
    reset_skill_run_state()
    reset_skill_usage_tracker()
    hinted: set[str] = set()
    result = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "google.maps.directions", "result": {}}),
        hinted_skill_groups=hinted,
    )
    assert "skill_load_hint" not in json.loads(result)
    assert not hinted


def test_skill_load_hint_after_second_distinct_maps_tool():
    reset_skill_run_state()
    _prime_maps_for_hint()
    hinted: set[str] = set()
    result = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "google.maps.directions", "result": {}}),
        hinted_skill_groups=hinted,
    )
    payload = json.loads(result)
    assert "skill_load_hint" in payload
    assert "google.maps" in payload["skill_load_hint"]
    assert "skills.load" in payload["skill_load_hint"]
    assert "google|maps" in hinted


def test_skill_load_hint_once_per_group():
    reset_skill_run_state()
    _prime_maps_for_hint()
    hinted: set[str] = set()
    first = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "google.maps.geocode", "result": {}}),
        hinted_skill_groups=hinted,
    )
    assert "skill_load_hint" in json.loads(first)

    second = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "google.maps.travel_time", "result": {}}),
        hinted_skill_groups=hinted,
    )
    assert "skill_load_hint" not in json.loads(second)


def test_no_skill_load_hint_when_skill_already_loaded():
    reset_skill_run_state()
    _prime_maps_for_hint()
    mark_skill_loaded("google.maps")
    hinted: set[str] = set()
    result = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "google.maps.geocode", "result": {}}),
        hinted_skill_groups=hinted,
    )
    assert "skill_load_hint" not in json.loads(result)
    assert not hinted


def test_skill_load_hint_after_second_calendar_tool():
    reset_skill_run_state()
    _prime_distinct_tools(
        "google.calendar.list_events",
        "google.calendar.create_event",
        "google.calendar.patch_event",
    )
    hinted: set[str] = set()
    result = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "google.calendar.list_events", "result": {}}),
        hinted_skill_groups=hinted,
    )
    payload = json.loads(result)
    assert "skill_load_hint" in payload
    assert "google.calendar" in payload["skill_load_hint"]
    assert "google|calendar" in hinted


def test_maybe_append_tool_hints_includes_both_on_maps():
    reset_skill_run_state()
    _prime_maps_for_hint()
    search_hinted: set[str] = set()
    skill_hinted: set[str] = set()
    result = maybe_append_tool_hints(
        json.dumps({"ok": True, "tool_name": "google.maps.directions", "result": {}}),
        hinted_search_groups=search_hinted,
        hinted_skill_groups=skill_hinted,
    )
    payload = json.loads(result)
    assert "search_tools_hint" in payload
    assert "skill_load_hint" in payload


def test_skill_load_hint_after_second_drive_tool():
    reset_skill_run_state()
    _prime_distinct_tools(
        "google.drive.search_files",
        "google.drive.get_file",
        "google.drive.download_file",
    )
    hinted: set[str] = set()
    result = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "google.drive.search_files", "result": {}}),
        hinted_skill_groups=hinted,
    )
    payload = json.loads(result)
    assert "skill_load_hint" in payload
    assert "google.drive" in payload["skill_load_hint"]


def test_skill_load_hint_after_second_sheets_tool():
    reset_skill_run_state()
    _prime_distinct_tools(
        "google.sheets.get_values",
        "google.sheets.update_values",
        "google.sheets.append_values",
    )
    hinted: set[str] = set()
    result = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "google.sheets.get_values", "result": {}}),
        hinted_skill_groups=hinted,
    )
    payload = json.loads(result)
    assert "skill_load_hint" in payload
    assert "google.sheets" in payload["skill_load_hint"]


def test_skill_load_hint_after_second_tasks_tool():
    reset_skill_run_state()
    _prime_distinct_tools(
        "google.tasks.list_default_tasks",
        "google.tasks.complete_task",
        "google.tasks.patch_task",
    )
    hinted: set[str] = set()
    result = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "google.tasks.list_default_tasks", "result": {}}),
        hinted_skill_groups=hinted,
    )
    payload = json.loads(result)
    assert "skill_load_hint" in payload
    assert "google.tasks" in payload["skill_load_hint"]
    assert "google|tasks" in hinted


def test_skill_load_hint_after_second_gmail_tool():
    reset_skill_run_state()
    _prime_distinct_tools(
        "google.gmail.list_inbox",
        "google.gmail.get_message",
        "google.gmail.reply_to_message",
    )
    hinted: set[str] = set()
    result = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "google.gmail.list_inbox", "result": {}}),
        hinted_skill_groups=hinted,
    )
    payload = json.loads(result)
    assert "skill_load_hint" in payload
    assert "google.gmail" in payload["skill_load_hint"]
    assert "google|gmail" in hinted


def test_skill_load_hint_after_second_workspace_tool():
    reset_skill_run_state()
    _prime_distinct_tools("workspace.stat", "workspace.read_file", "workspace.grep")
    hinted: set[str] = set()
    result = maybe_append_skill_load_hint(
        json.dumps({"ok": True, "tool_name": "workspace.read_file", "result": {}}),
        hinted_skill_groups=hinted,
    )
    payload = json.loads(result)
    assert "skill_load_hint" in payload
    assert "workspace" in payload["skill_load_hint"]
    assert "workspace|filesystem" in hinted
