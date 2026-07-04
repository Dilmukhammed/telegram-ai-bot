import json

from agent.tool_search_hints import (
    build_search_tools_hint,
    group_key_for_tool_name,
    maybe_append_tool_search_hint,
    tags_for_tool_name,
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
