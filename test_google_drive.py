import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.bootstrap import create_tool_runtime
from tools.builtins.google.auth import DRIVE_SCOPE, auth_status_payload, user_has_drive_scope
from tools.builtins.google.drive_files import _append_trash_filter, _require_confirm
from tools.builtins.google.drive_serialize import (
    build_access_proposals_list_response,
    build_apps_list_response,
    build_approvals_list_response,
    build_changes_list_response,
    build_comments_list_response,
    build_labels_list_response,
    build_list_response,
    build_permissions_list_response,
    build_replies_list_response,
    build_revisions_list_response,
    build_shared_drives_list_response,
    compact_about,
    compact_access_proposal,
    compact_app,
    compact_approval,
    compact_change,
    compact_comment,
    compact_created_file,
    compact_file_summary,
    compact_label,
    compact_permission,
    compact_reply,
    compact_revision,
    compact_shared_drive,
    default_export_mime,
    is_google_workspace_file,
    truncate_text,
)
from tools.builtins.google.drive_tools import (
    DRIVE2_TOOL_NAMES,
    DRIVE3_TOOL_NAMES,
    DRIVE4_TOOL_NAMES,
    DRIVE5_TOOL_NAMES,
    DRIVE6_TOOL_NAMES,
    DRIVE7_TOOL_NAMES,
    DRIVE8_TOOL_NAMES,
    DRIVE_TOOL_NAMES,
)
from tools.builtins.google.errors import DriveScopeMissingError
from tools.builtins.google.token_store import get_token_store
from tools.context import RunContext, reset_run_context, set_run_context


class DriveSerializeTests(unittest.TestCase):
    def test_compact_file_summary(self) -> None:
        summary = compact_file_summary(
            {
                "id": "file1",
                "name": "Report.pdf",
                "mimeType": "application/pdf",
                "size": "1234",
                "modifiedTime": "2026-07-03T10:00:00.000Z",
                "parents": ["folder1"],
                "starred": False,
                "trashed": False,
                "webViewLink": "https://drive.google.com/file/d/file1/view",
                "owners": [{"emailAddress": "user@example.com"}],
            }
        )
        self.assertEqual(summary["id"], "file1")
        self.assertEqual(summary["name"], "Report.pdf")
        self.assertEqual(summary["owners"], ["user@example.com"])

    def test_compact_about(self) -> None:
        about = compact_about(
            {
                "user": {"displayName": "User", "emailAddress": "user@example.com"},
                "storageQuota": {"limit": "1000", "usage": "100"},
                "maxUploadSize": "5242880",
                "canCreateDrives": True,
            }
        )
        self.assertEqual(about["user"]["email"], "user@example.com")
        self.assertTrue(about["can_create_drives"])

    def test_build_list_response(self) -> None:
        payload = build_list_response(
            {
                "files": [{"id": "a", "name": "A"}],
                "nextPageToken": "tok",
            }
        )
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["next_page_token"], "tok")

    def test_google_workspace_detection(self) -> None:
        self.assertTrue(is_google_workspace_file("application/vnd.google-apps.document"))
        self.assertFalse(is_google_workspace_file("application/pdf"))

    def test_default_export_mime(self) -> None:
        self.assertEqual(
            default_export_mime("application/vnd.google-apps.spreadsheet"),
            "text/csv",
        )

    def test_truncate_text(self) -> None:
        self.assertEqual(truncate_text("hello", 10), "hello")
        self.assertTrue(truncate_text("x" * 20, 10).endswith("…"))

    def test_compact_created_file(self) -> None:
        created = compact_created_file(
            {
                "id": "new1",
                "name": "Notes.txt",
                "mimeType": "text/plain",
                "webViewLink": "https://drive.google.com/file/d/new1/view",
                "size": "42",
                "parents": ["root"],
            }
        )
        self.assertEqual(created["id"], "new1")
        self.assertEqual(created["web_view_link"], "https://drive.google.com/file/d/new1/view")

    def test_require_confirm(self) -> None:
        _require_confirm({"confirm": True}, "need confirm")
        with self.assertRaises(ValueError):
            _require_confirm({"confirm": False}, "need confirm")
        with self.assertRaises(ValueError):
            _require_confirm({}, "need confirm")

    def test_append_trash_filter(self) -> None:
        self.assertEqual(_append_trash_filter("name contains 'x'", include_trashed=False), "name contains 'x' and trashed=false")
        self.assertEqual(_append_trash_filter("trashed=true", include_trashed=False), "trashed=true")

    def test_compact_permission(self) -> None:
        perm = compact_permission(
            {
                "id": "perm1",
                "type": "user",
                "role": "reader",
                "emailAddress": "friend@example.com",
                "displayName": "Friend",
            }
        )
        self.assertEqual(perm["email_address"], "friend@example.com")
        self.assertEqual(perm["role"], "reader")

    def test_build_permissions_list_response(self) -> None:
        payload = build_permissions_list_response(
            {
                "permissions": [{"id": "p1", "type": "anyone", "role": "reader"}],
                "nextPageToken": "tok",
            }
        )
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["next_page_token"], "tok")

    def test_compact_comment(self) -> None:
        comment = compact_comment(
            {
                "id": "c1",
                "content": "Looks good",
                "author": {"displayName": "User", "emailAddress": "user@example.com"},
                "createdTime": "2026-07-03T10:00:00.000Z",
                "replyCount": 2,
            }
        )
        self.assertEqual(comment["content"], "Looks good")
        self.assertEqual(comment["author"]["email"], "user@example.com")
        self.assertEqual(comment["reply_count"], 2)

    def test_build_comments_list_response(self) -> None:
        payload = build_comments_list_response(
            {"comments": [{"id": "c1", "content": "Hi"}], "nextPageToken": "tok"}
        )
        self.assertEqual(payload["count"], 1)

    def test_compact_reply(self) -> None:
        reply = compact_reply({"id": "r1", "content": "Thanks"})
        self.assertEqual(reply["content"], "Thanks")

    def test_build_replies_list_response(self) -> None:
        payload = build_replies_list_response({"replies": [{"id": "r1", "content": "Ok"}]})
        self.assertEqual(payload["count"], 1)


class DriveRevisionSerializeTests(unittest.TestCase):
    def test_compact_revision(self) -> None:
        revision = compact_revision(
            {
                "id": "rev1",
                "mimeType": "application/pdf",
                "modifiedTime": "2026-07-03T10:00:00.000Z",
                "keepForever": True,
                "size": "12345",
            }
        )
        self.assertEqual(revision["id"], "rev1")
        self.assertTrue(revision["keep_forever"])

    def test_build_revisions_list_response(self) -> None:
        payload = build_revisions_list_response(
            {"revisions": [{"id": "rev1", "size": "1"}], "nextPageToken": "tok"}
        )
        self.assertEqual(payload["count"], 1)

    def test_compact_change(self) -> None:
        change = compact_change(
            {
                "changeType": "file",
                "time": "2026-07-03T10:00:00.000Z",
                "removed": False,
                "fileId": "file1",
                "file": {"id": "file1", "name": "Report.pdf"},
            }
        )
        self.assertEqual(change["file_id"], "file1")
        self.assertEqual(change["file"]["name"], "Report.pdf")

    def test_build_changes_list_response(self) -> None:
        payload = build_changes_list_response(
            {
                "changes": [{"fileId": "f1", "removed": True}],
                "newStartPageToken": "newtok",
            }
        )
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["new_start_page_token"], "newtok")


class DriveSharedDriveSerializeTests(unittest.TestCase):
    def test_compact_shared_drive(self) -> None:
        drive = compact_shared_drive(
            {
                "id": "team1",
                "name": "Engineering",
                "colorRgb": "#4285F4",
                "hidden": False,
            }
        )
        self.assertEqual(drive["id"], "team1")
        self.assertEqual(drive["color_rgb"], "#4285F4")

    def test_build_shared_drives_list_response(self) -> None:
        payload = build_shared_drives_list_response(
            {"drives": [{"id": "team1", "name": "Eng"}], "nextPageToken": "tok"}
        )
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["shared_drives"][0]["name"], "Eng")


class DriveLabelAppSerializeTests(unittest.TestCase):
    def test_compact_label(self) -> None:
        label = compact_label({"id": "lbl1", "revisionId": "rev1", "fields": {"title": "Confidential"}})
        self.assertEqual(label["id"], "lbl1")
        self.assertEqual(label["fields"]["title"], "Confidential")

    def test_build_labels_list_response(self) -> None:
        payload = build_labels_list_response({"labels": [{"id": "lbl1"}], "nextPageToken": "tok"})
        self.assertEqual(payload["count"], 1)

    def test_compact_app(self) -> None:
        app = compact_app({"id": "app1", "name": "Docs", "supportsCreate": True})
        self.assertEqual(app["name"], "Docs")
        self.assertTrue(app["supports_create"])

    def test_build_apps_list_response(self) -> None:
        payload = build_apps_list_response({"items": [{"id": "app1", "name": "Sheets"}]})
        self.assertEqual(payload["count"], 1)


class DriveWorkspaceSerializeTests(unittest.TestCase):
    def test_compact_access_proposal(self) -> None:
        proposal = compact_access_proposal(
            {
                "fileId": "f1",
                "proposalId": "p1",
                "requesterEmailAddress": "req@example.com",
                "recipientEmailAddress": "rec@example.com",
                "rolesAndViews": [{"role": "reader"}],
            }
        )
        self.assertEqual(proposal["proposal_id"], "p1")
        self.assertEqual(proposal["roles_and_views"][0]["role"], "reader")

    def test_build_access_proposals_list_response(self) -> None:
        payload = build_access_proposals_list_response(
            {"accessProposals": [{"proposalId": "p1"}], "nextPageToken": "tok"}
        )
        self.assertEqual(payload["count"], 1)

    def test_compact_approval(self) -> None:
        approval = compact_approval(
            {
                "approvalId": "a1",
                "targetFileId": "f1",
                "status": "IN_PROGRESS",
                "reviewerResponses": [{"response": "NO_RESPONSE"}],
            }
        )
        self.assertEqual(approval["approval_id"], "a1")
        self.assertEqual(approval["status"], "IN_PROGRESS")

    def test_build_approvals_list_response(self) -> None:
        payload = build_approvals_list_response({"items": [{"approvalId": "a1"}]})
        self.assertEqual(payload["count"], 1)


class DriveAuthTests(unittest.TestCase):
    def test_user_has_drive_scope(self) -> None:
        store = get_token_store()
        store.save(
            telegram_user_id=901,
            email="drive@example.com",
            refresh_token="refresh",
            access_token="access",
            token_expiry=None,
            scopes=(DRIVE_SCOPE,),
        )
        self.assertTrue(user_has_drive_scope(store.get(901)))
        store.delete(901)

    def test_auth_status_includes_drive_ready(self) -> None:
        status = auth_status_payload(999998)
        self.assertIn("drive_ready", status)
        self.assertFalse(status["drive_ready"])

    def test_drive_scope_missing_error_type(self) -> None:
        error = DriveScopeMissingError("Drive access is not granted.")
        self.assertIsInstance(error, DriveScopeMissingError)


class DriveHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_file_rejects_google_doc(self) -> None:
        from tools.builtins.google.drive_files import download_file_handler

        service = MagicMock()
        service.files.return_value.get.return_value.execute.return_value = {
            "id": "doc1",
            "name": "Notes",
            "mimeType": "application/vnd.google-apps.document",
        }

        token = set_run_context(RunContext(user_id=1))
        try:
            with patch(
                "tools.builtins.google.drive_files.run_drive_call",
                new=AsyncMock(
                    return_value={
                        "id": "doc1",
                        "name": "Notes",
                        "mimeType": "application/vnd.google-apps.document",
                    }
                ),
            ):
                result = await download_file_handler({"file_id": "doc1"})
        finally:
            reset_run_context(token)
        self.assertFalse(result["ok"])
        self.assertIn("export_file", result["error"])


class DriveUploadContentTests(unittest.TestCase):
    def test_decode_requires_exactly_one_source(self) -> None:
        from tools.builtins.google.drive_files import _decode_upload_content

        with self.assertRaises(ValueError):
            _decode_upload_content({})
        with self.assertRaises(ValueError):
            _decode_upload_content(
                {"content_text": "hi", "content_base64": "YQ=="},
                user_id=1,
            )
        with self.assertRaises(ValueError):
            _decode_upload_content(
                {"path": "uploads/a.pdf", "content_text": "hi"},
                user_id=1,
            )

    def test_decode_content_text(self) -> None:
        from tools.builtins.google.drive_files import _decode_upload_content

        content, mime, source = _decode_upload_content({"content_text": "hello"}, user_id=1)
        self.assertEqual(content, b"hello")
        self.assertEqual(mime, "text/plain")
        self.assertIsNone(source)

    def test_decode_workspace_path(self) -> None:
        import tempfile
        from unittest.mock import patch

        from tools.builtins.google.drive_files import _decode_upload_content
        from tools.workspace.store import save_bytes

        with tempfile.TemporaryDirectory() as tmp:
            with patch("tools.workspace.store.get_settings") as settings, patch(
                "tools.workspace.paths.get_settings"
            ) as paths_settings:
                mock = MagicMock()
                mock.workspace_root = tmp
                mock.workspace_upload_max_bytes = 10 * 1024 * 1024
                mock.workspace_max_bytes_per_user = 500 * 1024 * 1024
                mock.workspace_max_files_per_user = 1000
                settings.return_value = mock
                paths_settings.return_value = mock
                save_bytes(
                    1,
                    relative="uploads/report.pdf",
                    data=b"%PDF-1.4",
                    mime_type="application/pdf",
                )
                content, mime, source = _decode_upload_content(
                    {"path": "uploads/report.pdf"},
                    user_id=1,
                )
        self.assertEqual(content, b"%PDF-1.4")
        self.assertEqual(mime, "application/pdf")
        self.assertEqual(source, "uploads/report.pdf")


class DriveWriteHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_file_from_workspace_path(self) -> None:
        import tempfile
        from unittest.mock import patch

        from tools.builtins.google.drive_files import upload_file_handler
        from tools.workspace.store import save_bytes

        created = {
            "id": "file1",
            "name": "report.pdf",
            "mimeType": "application/pdf",
            "webViewLink": "https://drive.google.com/file/d/file1/view",
        }

        async def _fake_run_drive_call(user_id, callback):
            return callback(MagicMock())

        with tempfile.TemporaryDirectory() as tmp:
            with patch("tools.workspace.store.get_settings") as settings, patch(
                "tools.workspace.paths.get_settings"
            ) as paths_settings, patch(
                "tools.builtins.google.drive_files.get_settings"
            ) as drive_settings, patch(
                "tools.builtins.google.drive_files.run_drive_call",
                new=_fake_run_drive_call,
            ), patch(
                "tools.builtins.google.drive_files.create_file_with_content",
                return_value=created,
            ) as create_mock:
                mock = MagicMock()
                mock.workspace_root = tmp
                mock.workspace_upload_max_bytes = 10 * 1024 * 1024
                mock.workspace_max_bytes_per_user = 500 * 1024 * 1024
                mock.workspace_max_files_per_user = 1000
                mock.drive_max_upload_bytes = 10 * 1024 * 1024
                settings.return_value = mock
                paths_settings.return_value = mock
                drive_settings.return_value = mock
                save_bytes(
                    1,
                    relative="uploads/report.pdf",
                    data=b"%PDF-1.4 hello",
                    mime_type="application/pdf",
                )
                token = set_run_context(RunContext(user_id=1))
                try:
                    result = await upload_file_handler({"path": "uploads/report.pdf"})
                finally:
                    reset_run_context(token)

        self.assertTrue(result["created"])
        self.assertTrue(result["uploaded"])
        self.assertEqual(result["source_path"], "uploads/report.pdf")
        self.assertEqual(result["file"]["name"], "report.pdf")
        create_mock.assert_called_once()
        kwargs = create_mock.call_args.kwargs
        self.assertEqual(kwargs["content"], b"%PDF-1.4 hello")
        self.assertEqual(kwargs["mime_type"], "application/pdf")
        self.assertEqual(kwargs["metadata"]["name"], "report.pdf")

    async def test_upload_file_path_missing_raises(self) -> None:
        import tempfile
        from unittest.mock import patch

        from tools.builtins.google.drive_files import upload_file_handler

        with tempfile.TemporaryDirectory() as tmp:
            with patch("tools.workspace.store.get_settings") as settings, patch(
                "tools.workspace.paths.get_settings"
            ) as paths_settings:
                mock = MagicMock()
                mock.workspace_root = tmp
                mock.workspace_upload_max_bytes = 10 * 1024 * 1024
                mock.workspace_max_bytes_per_user = 500 * 1024 * 1024
                mock.workspace_max_files_per_user = 1000
                settings.return_value = mock
                paths_settings.return_value = mock
                token = set_run_context(RunContext(user_id=1))
                try:
                    with self.assertRaises(ValueError) as ctx:
                        await upload_file_handler({"path": "uploads/missing.pdf"})
                finally:
                    reset_run_context(token)
        self.assertIn("workspace path error", str(ctx.exception))

    async def test_delete_file_requires_confirm(self) -> None:
        from tools.builtins.google.drive_files import delete_file_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await delete_file_handler({"file_id": "abc"})
        finally:
            reset_run_context(token)

    async def test_empty_trash_requires_confirm(self) -> None:
        from tools.builtins.google.drive_files import empty_trash_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await empty_trash_handler({})
        finally:
            reset_run_context(token)


class DrivePermissionHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_share_file_requires_email_for_user(self) -> None:
        from tools.builtins.google.drive_permissions import share_file_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await share_file_handler({"file_id": "abc", "type": "user", "role": "reader"})
        finally:
            reset_run_context(token)


class DriveCommentHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_comment_requires_content(self) -> None:
        from tools.builtins.google.drive_comments import create_comment_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await create_comment_handler({"file_id": "abc"})
        finally:
            reset_run_context(token)

    async def test_create_reply_requires_comment_id(self) -> None:
        from tools.builtins.google.drive_comments import create_reply_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await create_reply_handler({"file_id": "abc", "content": "hi"})
        finally:
            reset_run_context(token)


class DriveRevisionHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_revision_requires_confirm(self) -> None:
        from tools.builtins.google.drive_revisions import delete_revision_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await delete_revision_handler({"file_id": "f1", "revision_id": "r1"})
        finally:
            reset_run_context(token)

    async def test_list_changes_requires_page_token(self) -> None:
        from tools.builtins.google.drive_changes import list_changes_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await list_changes_handler({})
        finally:
            reset_run_context(token)


class DriveSharedDriveHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_shared_drive_requires_confirm(self) -> None:
        from tools.builtins.google.drive_shared import delete_shared_drive_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await delete_shared_drive_handler({"drive_id": "team1"})
        finally:
            reset_run_context(token)

    async def test_create_shared_drive_requires_name(self) -> None:
        from tools.builtins.google.drive_shared import create_shared_drive_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await create_shared_drive_handler({})
        finally:
            reset_run_context(token)


class DriveLabelHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_modify_file_labels_requires_changes(self) -> None:
        from tools.builtins.google.drive_labels import modify_file_labels_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await modify_file_labels_handler({"file_id": "f1"})
        finally:
            reset_run_context(token)


class DriveWorkspaceHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_access_proposal_requires_action(self) -> None:
        from tools.builtins.google.drive_workspace import resolve_access_proposal_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await resolve_access_proposal_handler(
                    {"file_id": "f1", "proposal_id": "p1"},
                )
        finally:
            reset_run_context(token)

    async def test_start_approval_requires_reviewers(self) -> None:
        from tools.builtins.google.drive_workspace import start_approval_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await start_approval_handler({"file_id": "f1"})
        finally:
            reset_run_context(token)

    async def test_comment_approval_requires_message(self) -> None:
        from tools.builtins.google.drive_workspace import comment_approval_handler

        token = set_run_context(RunContext(user_id=1))
        try:
            with self.assertRaises(ValueError):
                await comment_approval_handler(
                    {"file_id": "f1", "approval_id": "a1"},
                )
        finally:
            reset_run_context(token)


class DriveRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            self.runtime = await create_tool_runtime()

    async def test_drive_tools_registered(self) -> None:
        names = {
            tool.name
            for tool in self.runtime._registry.all()
            if tool.name.startswith("google.drive.")
        }
        self.assertEqual(names, set(DRIVE_TOOL_NAMES))
        self.assertEqual(len(names), 70)

    async def test_drive_write_tools_have_write_tag(self) -> None:
        for tool in self.runtime._registry.all():
            if tool.name not in DRIVE2_TOOL_NAMES:
                continue
            self.assertIn("write", tool.tags)

    async def test_drive_permission_read_tools_have_tags(self) -> None:
        read_names = {
            "google.drive.list_permissions",
            "google.drive.get_permission",
        }
        for tool in self.runtime._registry.all():
            if tool.name not in read_names:
                continue
            self.assertIn("permissions", tool.tags)
            self.assertIn("read", tool.tags)

    async def test_drive_permission_write_tools_have_tags(self) -> None:
        write_names = DRIVE3_TOOL_NAMES - {
            "google.drive.list_permissions",
            "google.drive.get_permission",
        }
        for tool in self.runtime._registry.all():
            if tool.name not in write_names:
                continue
            self.assertIn("permissions", tool.tags)
            self.assertIn("write", tool.tags)

    async def test_drive_comment_read_tools_have_tags(self) -> None:
        read_names = {
            name for name in DRIVE4_TOOL_NAMES if name.endswith((".list_comments", ".get_comment", ".list_replies", ".get_reply"))
        }
        for tool in self.runtime._registry.all():
            if tool.name not in read_names:
                continue
            self.assertIn("comments", tool.tags)
            self.assertIn("read", tool.tags)

    async def test_drive_comment_write_tools_have_tags(self) -> None:
        write_names = DRIVE4_TOOL_NAMES - {
            name for name in DRIVE4_TOOL_NAMES if name.endswith((".list_comments", ".get_comment", ".list_replies", ".get_reply"))
        }
        for tool in self.runtime._registry.all():
            if tool.name not in write_names:
                continue
            self.assertIn("comments", tool.tags)
            self.assertIn("write", tool.tags)

    async def test_drive_revision_read_tools_have_tags(self) -> None:
        read_names = {
            "google.drive.list_revisions",
            "google.drive.get_revision",
        }
        for tool in self.runtime._registry.all():
            if tool.name not in read_names:
                continue
            self.assertIn("revisions", tool.tags)
            self.assertIn("read", tool.tags)

    async def test_drive_revision_write_tools_have_tags(self) -> None:
        write_names = {
            "google.drive.update_revision",
            "google.drive.delete_revision",
        }
        for tool in self.runtime._registry.all():
            if tool.name not in write_names:
                continue
            self.assertIn("revisions", tool.tags)
            self.assertIn("write", tool.tags)

    async def test_drive_changes_tools_have_tags(self) -> None:
        for tool in self.runtime._registry.all():
            if tool.name not in DRIVE5_TOOL_NAMES - {
                "google.drive.list_revisions",
                "google.drive.get_revision",
                "google.drive.update_revision",
                "google.drive.delete_revision",
            }:
                continue
            self.assertIn("changes", tool.tags)
            self.assertIn("read", tool.tags)

    async def test_drive_shared_drive_read_tools_have_tags(self) -> None:
        read_names = {
            "google.drive.list_shared_drives",
            "google.drive.get_shared_drive",
        }
        for tool in self.runtime._registry.all():
            if tool.name not in read_names:
                continue
            self.assertIn("shared_drives", tool.tags)
            self.assertIn("read", tool.tags)

    async def test_drive_shared_drive_write_tools_have_tags(self) -> None:
        write_names = DRIVE6_TOOL_NAMES - {
            "google.drive.list_shared_drives",
            "google.drive.get_shared_drive",
        }
        for tool in self.runtime._registry.all():
            if tool.name not in write_names:
                continue
            self.assertIn("shared_drives", tool.tags)
            self.assertIn("write", tool.tags)

    async def test_drive_label_read_tools_have_tags(self) -> None:
        for tool in self.runtime._registry.all():
            if tool.name != "google.drive.list_file_labels":
                continue
            self.assertIn("labels", tool.tags)
            self.assertIn("read", tool.tags)

    async def test_drive_label_write_tools_have_tags(self) -> None:
        for tool in self.runtime._registry.all():
            if tool.name != "google.drive.modify_file_labels":
                continue
            self.assertIn("labels", tool.tags)
            self.assertIn("write", tool.tags)

    async def test_drive_app_tools_have_tags(self) -> None:
        for tool in self.runtime._registry.all():
            if tool.name not in {"google.drive.list_apps", "google.drive.get_app"}:
                continue
            self.assertIn("settings", tool.tags)
            self.assertIn("read", tool.tags)

    async def test_drive_workspace_read_tools_have_tags(self) -> None:
        read_names = {
            "google.drive.list_access_proposals",
            "google.drive.get_access_proposal",
            "google.drive.list_approvals",
            "google.drive.get_approval",
        }
        for tool in self.runtime._registry.all():
            if tool.name not in read_names:
                continue
            self.assertIn("workspace", tool.tags)
            self.assertIn("read", tool.tags)

    async def test_drive_workspace_write_tools_have_tags(self) -> None:
        write_names = DRIVE8_TOOL_NAMES - {
            "google.drive.list_access_proposals",
            "google.drive.get_access_proposal",
            "google.drive.list_approvals",
            "google.drive.get_approval",
        }
        for tool in self.runtime._registry.all():
            if tool.name not in write_names:
                continue
            self.assertIn("workspace", tool.tags)
            self.assertIn("write", tool.tags)

    async def test_drive_read_tools_have_read_tag(self) -> None:
        from tools.builtins.google.drive_tools import DRIVE1_TOOL_NAMES

        for tool in self.runtime._registry.all():
            if tool.name not in DRIVE1_TOOL_NAMES:
                continue
            self.assertIn("google", tool.tags)
            self.assertIn("drive", tool.tags)
            if tool.name != "google.drive.get_about":
                self.assertIn("read", tool.tags)


if __name__ == "__main__":
    unittest.main()
