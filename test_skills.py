import asyncio
import json

from agent.tool_search_hints import tags_for_tool_name
from skills.auto_load import apply_pending_skill_unloads
from skills.collapse import SKILL_COLLAPSED_PREFIX, SkillContextCollapser, parse_expanded_skill_id
from skills.pending import is_skill_loaded, mark_skill_loaded, reset_skill_run_state, take_pending_skills
from skills.registry import get_skill, list_skills
from tools.builtins.skills_tools import SKILLS_LOAD, SKILLS_LIST, SKILLS_UNLOAD


def test_skill_registry_loads_google_maps():
    spec = get_skill("google.maps")
    assert spec is not None
    assert spec.skill_id == "google.maps"
    assert "google" in spec.tags
    assert len(spec.content) > 1000


def test_skill_registry_loads_google_sheets():
    spec = get_skill("google.sheets")
    assert spec is not None
    assert spec.skill_id == "google.sheets"
    assert "sheets" in spec.tags
    assert "get_values" in spec.content
    assert len(spec.content) > 1000


def test_skill_registry_loads_google_calendar():
    spec = get_skill("google.calendar")
    assert spec is not None
    assert spec.skill_id == "google.calendar"
    assert "calendar" in spec.tags
    assert "list_today" in spec.content
    assert len(spec.content) > 1000


def test_skill_registry_loads_google_tasks():
    spec = get_skill("google.tasks")
    assert spec is not None
    assert spec.skill_id == "google.tasks"
    assert "tasks" in spec.tags
    assert "quick_add_task" in spec.content
    assert len(spec.content) > 1000


def test_skill_registry_loads_google_gmail():
    spec = get_skill("google.gmail")
    assert spec is not None
    assert spec.skill_id == "google.gmail"
    assert "gmail" in spec.tags
    assert "search_messages" in spec.content
    assert len(spec.content) > 1000


def test_skill_registry_loads_workspace():
    spec = get_skill("workspace")
    assert spec is not None
    assert spec.skill_id == "workspace"
    assert "filesystem" in spec.tags
    assert "read_file" in spec.content
    assert len(spec.content) > 500


def test_skill_registry_loads_yandex_music():
    spec = get_skill("yandex.music")
    assert spec is not None
    assert spec.skill_id == "yandex.music"
    assert "music" in spec.tags
    assert "yandex.music.search" in spec.content
    assert len(spec.content) > 500


def test_list_skills_includes_google_maps():
    ids = [item.skill_id for item in list_skills()]
    assert "google.maps" in ids
    assert "google.drive" in ids
    assert "google.sheets" in ids
    assert "google.calendar" in ids
    assert "google.tasks" in ids
    assert "google.gmail" in ids
    assert "yandex.music" in ids
    assert "workspace" in ids


async def test_skills_load_injects_full_content():
    reset_skill_run_state()
    result = await SKILLS_LOAD.handler({"skill_id": "google.maps"})
    payload = json.loads(json.dumps(result))
    assert payload["ok"] is True
    assert payload["already_loaded"] is False
    assert is_skill_loaded("google.maps")

    pending = take_pending_skills()
    assert len(pending) == 1
    skill_id, content = pending[0]
    assert skill_id == "google.maps"
    assert content == get_skill("google.maps").content


async def test_skills_load_idempotent_per_run():
    reset_skill_run_state()
    first = await SKILLS_LOAD.handler({"skill_id": "google.maps"})
    assert first["already_loaded"] is False
    assert take_pending_skills()

    second = await SKILLS_LOAD.handler({"skill_id": "google.maps"})
    assert second["already_loaded"] is True
    assert take_pending_skills() == []


async def test_skills_list():
    result = await SKILLS_LIST.handler({})
    assert result["count"] >= 1
    assert any(item["skill_id"] == "google.maps" for item in result["skills"])


async def test_skills_unload_collapses_pending():
    reset_skill_run_state()
    result = await SKILLS_LOAD.handler({"skill_id": "google.maps"})
    assert result["already_loaded"] is False
    pending = take_pending_skills()
    messages = [
        {
            "role": "user",
            "content": f"[Skill loaded: google.maps]\n\n{pending[0][1]}",
        }
    ]
    mark_skill_loaded("google.maps")

    unload = await SKILLS_UNLOAD.handler({"skill_id": "google.maps"})
    assert unload["already_unloaded"] is False
    collapser = SkillContextCollapser()
    collapser.sync_from_messages(messages)
    apply_pending_skill_unloads(messages, collapser)

    assert parse_expanded_skill_id(messages[0]["content"]) is None
    assert SKILL_COLLAPSED_PREFIX in messages[0]["content"]
    assert "skills.unload" in messages[0]["content"]
    assert not is_skill_loaded("google.maps")

    second = await SKILLS_UNLOAD.handler({"skill_id": "google.maps"})
    assert second["already_unloaded"] is True


def test_tool_search_hint_tags_for_skills():
    assert tags_for_tool_name("skills.load") == ("skills", "agent")


def test_tool_search_hint_tags_for_skills_unload():
    assert tags_for_tool_name("skills.unload") == ("skills", "agent")


async def _run_async_tests() -> None:
    await test_skills_load_injects_full_content()
    await test_skills_load_idempotent_per_run()
    await test_skills_list()
    await test_skills_unload_collapses_pending()


if __name__ == "__main__":
    test_skill_registry_loads_google_maps()
    test_skill_registry_loads_google_sheets()
    test_skill_registry_loads_google_calendar()
    test_skill_registry_loads_google_tasks()
    test_skill_registry_loads_google_gmail()
    test_skill_registry_loads_workspace()
    test_list_skills_includes_google_maps()
    test_tool_search_hint_tags_for_skills()
    test_tool_search_hint_tags_for_skills_unload()
    asyncio.run(_run_async_tests())
    print("all ok")
