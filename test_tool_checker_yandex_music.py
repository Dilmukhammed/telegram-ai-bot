import json
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock

from agent.run_trace import ToolStep
from agent.tool_checker import should_run_tool_checker
from agent.tool_checker_live import _fetch_by_kind
from config import get_settings
from tools.builtins.yandex.music_checker import (
    MUSIC_CHECKER_ALL_TOOL_NAMES,
    MUSIC_CHECKER_QUESTIONS_BY_TOOL,
    MUSIC_CHECKER_READ_TOOL_NAMES,
    MUSIC_CHECKER_TIER1_TOOL_NAMES,
    MUSIC_CHECKER_TIER2_TOOL_NAMES,
    MUSIC_CHECKER_WRITE_TOOL_NAMES,
    YANDEX_MUSIC_TRACK_DOWNLOAD_QUESTIONS,
)
from tools.builtins.yandex.music_tools import YANDEX_MUSIC_TOOLS
from tools.checker.registry import get_checker_questions
from tools.checker.templates import template_questions_for
from tools.verification import EVIDENCE_LIVE_FETCH, FETCH_YANDEX_TRACK


class YandexMusicCheckerPackTests(unittest.TestCase):
    def test_all_62_tier_tools_have_handcrafted_questions(self) -> None:
        tools_by_name = {tool.name: tool for tool in YANDEX_MUSIC_TOOLS}
        self.assertEqual(len(MUSIC_CHECKER_ALL_TOOL_NAMES), 62)
        self.assertEqual(len(MUSIC_CHECKER_TIER1_TOOL_NAMES), 23)
        self.assertEqual(len(MUSIC_CHECKER_TIER2_TOOL_NAMES), 39)
        for name in MUSIC_CHECKER_ALL_TOOL_NAMES:
            self.assertIn(name, tools_by_name, msg=name)
            questions = get_checker_questions(tools_by_name[name])
            self.assertGreaterEqual(len(questions), 1, msg=name)
            self.assertEqual(questions, MUSIC_CHECKER_QUESTIONS_BY_TOOL[name], msg=name)

    def test_tier_partitions_cover_all(self) -> None:
        self.assertEqual(
            set(MUSIC_CHECKER_TIER1_TOOL_NAMES) | set(MUSIC_CHECKER_TIER2_TOOL_NAMES),
            set(MUSIC_CHECKER_ALL_TOOL_NAMES),
        )
        self.assertEqual(
            set(MUSIC_CHECKER_READ_TOOL_NAMES) | set(MUSIC_CHECKER_WRITE_TOOL_NAMES),
            set(MUSIC_CHECKER_ALL_TOOL_NAMES),
        )
        self.assertEqual(len(MUSIC_CHECKER_READ_TOOL_NAMES), 22)
        self.assertEqual(len(MUSIC_CHECKER_WRITE_TOOL_NAMES), 40)

    def test_track_download_has_live_fetch_and_not_download_info(self) -> None:
        question_ids = {q.id for q in YANDEX_MUSIC_TRACK_DOWNLOAD_QUESTIONS}
        self.assertIn("not_download_info", question_ids)
        self.assertIn("track_exists_live", question_ids)
        fetches = {
            ref.fetch
            for q in YANDEX_MUSIC_TRACK_DOWNLOAD_QUESTIONS
            for ref in q.evidence
            if ref.kind == EVIDENCE_LIVE_FETCH
        }
        self.assertEqual(fetches, {FETCH_YANDEX_TRACK})

    def test_non_tier_tool_uses_template_fallback(self) -> None:
        tool = next(t for t in YANDEX_MUSIC_TOOLS if t.name == "yandex.music.tracks_download_info")
        self.assertNotIn(tool.name, MUSIC_CHECKER_QUESTIONS_BY_TOOL)
        self.assertEqual(get_checker_questions(tool), template_questions_for(tool))

    def test_allowlist_glob_matches_yandex_music(self) -> None:
        settings = replace(
            get_settings(),
            agent_checker_enabled=True,
            checker_tools_allowlist="yandex.music.*",
        )
        step = ToolStep(
            turn=1,
            meta_tool="use_tool",
            target_tool="yandex.music.search",
            arguments_raw={},
            arguments_normalized={"query": "Radiohead"},
            result_ok=True,
            result_json=json.dumps({"ok": True, "result": {"tracks": []}}),
        )
        tool = next(t for t in YANDEX_MUSIC_TOOLS if t.name == "yandex.music.search")
        self.assertTrue(should_run_tool_checker(spec=tool, step=step, settings=settings))


class YandexMusicLiveFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_track_download_live_fetch_uses_tracks_api(self) -> None:
        runtime = AsyncMock()
        runtime.use_tool = AsyncMock(
            return_value={
                "ok": True,
                "result": {"tracks": [{"id": "123", "title": "Test Track"}]},
            }
        )
        step = ToolStep(
            turn=2,
            meta_tool="use_tool",
            target_tool="yandex.music.track_download",
            arguments_raw={},
            arguments_normalized={"track_id": "123:456", "codec": "mp3"},
            result_ok=True,
            result_json=json.dumps(
                {
                    "tool_name": "yandex.music.track_download",
                    "ok": True,
                    "result": {
                        "file_ref": "run:abc",
                        "track_id": "123:456",
                        "title": "Test Track",
                    },
                }
            ),
        )
        snippet = await _fetch_by_kind(
            FETCH_YANDEX_TRACK,
            current_step=step,
            user_id=7,
            runtime=runtime,
            label="yandex_track_live",
        )
        self.assertIsNotNone(snippet)
        assert snippet is not None
        runtime.use_tool.assert_awaited_once()
        call_args = runtime.use_tool.await_args
        self.assertEqual(call_args.args[0], "yandex.music.tracks")
        self.assertEqual(call_args.args[1], {"track_ids": "123"})
        payload = json.loads(snippet.content)
        self.assertTrue(payload.get("exists"))


if __name__ == "__main__":
    unittest.main()
