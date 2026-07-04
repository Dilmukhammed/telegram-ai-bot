from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.context import RunContext, reset_run_context, set_run_context
from tools.run_files import RunFileStore, reset_run_file_store, set_run_file_store
from tools.workspace.errors import WorkspacePathError
from tools.workspace.paths import resolve_workspace_path, sanitize_relative_path
from tools.workspace.store import (
    clear_zone,
    delete_path,
    find_files,
    grep_files,
    read_file_preview,
    read_lines,
    save_bytes,
    stat_path,
    unzip_file,
    write_file,
)
from tools.workspace.vision_pending import clear_pending_vision, take_pending_vision


class WorkspacePathsTests(unittest.TestCase):
    def test_rejects_traversal(self) -> None:
        with self.assertRaises(WorkspacePathError):
            sanitize_relative_path("../etc/passwd")

    def test_resolve_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tools.workspace.paths.get_settings") as mock_settings:
                mock_settings.return_value.workspace_root = tmp
                path = resolve_workspace_path(42, "agent/notes.md")
                self.assertTrue(str(path).endswith("42\\agent\\notes.md") or path.as_posix().endswith("42/agent/notes.md"))


class WorkspaceStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name)
        self._settings_patch = patch("tools.workspace.store.get_settings")
        self._paths_patch = patch("tools.workspace.paths.get_settings")
        settings = self._settings_patch.start()
        paths_settings = self._paths_patch.start()
        from config import get_settings

        base = get_settings()
        settings.return_value = base
        paths_settings.return_value = base
        object.__setattr__(settings.return_value, "workspace_root", str(self._root))
        object.__setattr__(paths_settings.return_value, "workspace_root", str(self._root))
        object.__setattr__(settings.return_value, "workspace_max_bytes_per_user", 10 * 1024 * 1024)
        object.__setattr__(settings.return_value, "workspace_max_file_bytes", 5 * 1024 * 1024)
        object.__setattr__(settings.return_value, "workspace_max_files_per_user", 100)
        object.__setattr__(settings.return_value, "workspace_read_preview_lines", 5)
        object.__setattr__(settings.return_value, "workspace_read_preview_lines_max", 5)
        object.__setattr__(settings.return_value, "workspace_read_lines_max", 500)
        object.__setattr__(settings.return_value, "workspace_upload_max_bytes", 5 * 1024 * 1024)
        object.__setattr__(settings.return_value, "workspace_grep_max_matches", 50)
        object.__setattr__(settings.return_value, "workspace_grep_max_files", 20)
        object.__setattr__(settings.return_value, "workspace_unzip_max_files", 100)
        object.__setattr__(settings.return_value, "workspace_unzip_max_bytes", 10 * 1024 * 1024)

        self._ctx_token = set_run_context(RunContext(user_id=7))
        store = RunFileStore(run_id="testrun01", user_id=7)
        self._store_token = set_run_file_store(store)
        clear_pending_vision()

    async def asyncTearDown(self) -> None:
        reset_run_file_store(self._store_token)
        reset_run_context(self._ctx_token)
        self._settings_patch.stop()
        self._paths_patch.stop()
        self._tmp.cleanup()
        clear_pending_vision()

    async def test_write_and_stat(self) -> None:
        result = write_file(7, relative="agent/hello.txt", content_text="hello\nworld\n")
        self.assertTrue(result["ok"])
        stat = stat_path(7, "agent/hello.txt")
        self.assertTrue(stat["ok"])
        self.assertEqual(stat["kind"], "text")
        self.assertEqual(stat["total_lines"], 2)

    async def test_read_file_preview_not_full(self) -> None:
        lines = "\n".join(f"line {index}" for index in range(1, 51))
        write_file(7, relative="agent/big.txt", content_text=lines)
        preview = read_file_preview(7, relative="agent/big.txt")
        self.assertEqual(preview["total_lines"], 50)
        self.assertEqual(preview["preview_lines"], 5)
        self.assertEqual(len(preview["lines"]), 5)

    async def test_read_lines_range(self) -> None:
        lines = "\n".join(f"line {index}" for index in range(1, 101))
        write_file(7, relative="agent/range.txt", content_text=lines)
        chunk = read_lines(7, relative="agent/range.txt", start_line=20, end_line=25)
        self.assertEqual(len(chunk["lines"]), 6)
        self.assertEqual(chunk["lines"][0]["n"], 20)
        self.assertEqual(chunk["lines"][-1]["n"], 25)

    async def test_image_read_queues_vision(self) -> None:
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        save_bytes(7, relative="uploads/test.png", data=png_header, mime_type="image/png")
        result = read_file_preview(7, relative="uploads/test.png")
        self.assertEqual(result["kind"], "image")
        pending = take_pending_vision()
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending[0][1].startswith("data:image/png;base64,"))

    async def test_stat_missing(self) -> None:
        stat = stat_path(7, "agent/missing.txt")
        self.assertFalse(stat["ok"])
        self.assertFalse(stat["exists"])

    async def test_find_glob(self) -> None:
        write_file(7, relative="agent/a.md", content_text="# A")
        write_file(7, relative="agent/b.txt", content_text="b")
        found = find_files(7, pattern="agent/*.md")
        self.assertTrue(found["ok"])
        self.assertEqual(len(found["matches"]), 1)
        self.assertEqual(found["matches"][0]["path"], "agent/a.md")

    async def test_grep_finds_line(self) -> None:
        write_file(7, relative="agent/log.txt", content_text="ok\nERROR: boom\nfine\n")
        hits = grep_files(7, pattern="ERROR", relative="agent")
        self.assertEqual(len(hits["matches"]), 1)
        self.assertEqual(hits["matches"][0]["line"], 2)

    async def test_delete_requires_confirm(self) -> None:
        write_file(7, relative="agent/tmp.txt", content_text="x")
        with self.assertRaises(ValueError):
            delete_path(7, relative="agent/tmp.txt", confirm=False)

    async def test_clear_zone(self) -> None:
        write_file(7, relative="agent/x.txt", content_text="x")
        result = clear_zone(7, zone="agent", confirm=True)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["files_removed"], 1)

    async def test_unzip_extract(self) -> None:
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("inner/hello.txt", "hello zip")
        save_bytes(7, relative="uploads/test.zip", data=buffer.getvalue(), mime_type="application/zip")
        extracted = unzip_file(7, relative="uploads/test.zip")
        self.assertTrue(extracted["ok"])
        self.assertEqual(extracted["files_extracted"], 1)
        stat = stat_path(7, str(extracted["entries"][0]["path"]))
        self.assertTrue(stat["ok"])


if __name__ == "__main__":
    unittest.main()
