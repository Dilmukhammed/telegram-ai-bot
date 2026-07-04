import base64
import os
import unittest
from unittest.mock import patch

from tools.bootstrap import create_tool_runtime
from tools.builtins.google.auth import GMAIL_MODIFY_SCOPE, auth_status_payload, user_has_gmail_scope
from tools.builtins.google.gmail_send import (
    build_forward_body,
    build_send_payload,
    forward_subject,
    reply_subject,
)
from tools.builtins.google.gmail_serialize import (
    compact_draft,
    compact_filter,
    compact_message,
    compact_thread,
    compact_vacation,
    extract_bodies,
    plain_body_from_message,
)
from tools.builtins.google.gmail_tools import _patch_send_as_body, _require_permanent_confirm
from tools.builtins.google.token_store import GoogleTokenStore

MAIL5_TOOL_NAMES = {
    "google.gmail.get_profile",
    "google.gmail.list_labels",
    "google.gmail.get_label",
    "google.gmail.search_messages",
    "google.gmail.list_messages",
    "google.gmail.get_message",
    "google.gmail.list_inbox",
    "google.gmail.list_unread",
    "google.gmail.list_threads",
    "google.gmail.get_thread",
    "google.gmail.modify_message",
    "google.gmail.modify_thread",
    "google.gmail.mark_read",
    "google.gmail.mark_unread",
    "google.gmail.archive_message",
    "google.gmail.trash_message",
    "google.gmail.untrash_message",
    "google.gmail.trash_thread",
    "google.gmail.untrash_thread",
    "google.gmail.send_message",
    "google.gmail.reply_to_message",
    "google.gmail.create_label",
    "google.gmail.update_label",
    "google.gmail.delete_label",
    "google.gmail.get_attachment",
    "google.gmail.batch_modify_messages",
    "google.gmail.forward_message",
    "google.gmail.list_drafts",
    "google.gmail.get_draft",
    "google.gmail.create_draft",
    "google.gmail.update_draft",
    "google.gmail.delete_draft",
    "google.gmail.send_draft",
    "google.gmail.delete_message",
    "google.gmail.batch_delete_messages",
    "google.gmail.list_filters",
    "google.gmail.get_filter",
    "google.gmail.create_filter",
    "google.gmail.delete_filter",
    "google.gmail.get_vacation_settings",
    "google.gmail.update_vacation_settings",
    "google.gmail.list_send_as",
    "google.gmail.get_send_as",
    "google.gmail.patch_send_as",
    "google.gmail.import_message",
}


class GmailSerializeTests(unittest.TestCase):
    def test_extract_plain_text_body(self) -> None:
        encoded = base64.urlsafe_b64encode(b"Hello Gmail").decode("ascii").rstrip("=")
        payload = {
            "mimeType": "text/plain",
            "body": {"data": encoded},
            "headers": [],
        }
        text, html = extract_bodies(payload)
        self.assertEqual(text, "Hello Gmail")
        self.assertEqual(html, "")

    def test_compact_message_truncates_body(self) -> None:
        encoded = base64.urlsafe_b64encode(("x" * 100).encode()).decode("ascii").rstrip("=")
        message = {
            "id": "m1",
            "threadId": "t1",
            "labelIds": ["INBOX"],
            "snippet": "snippet",
            "internalDate": "1700000000000",
            "payload": {
                "headers": [
                    {"name": "From", "value": "a@example.com"},
                    {"name": "Subject", "value": "Test"},
                ],
                "mimeType": "text/plain",
                "body": {"data": encoded},
            },
        }
        compact = compact_message(message, max_body_chars=20, include_body=True)
        self.assertEqual(compact["id"], "m1")
        self.assertEqual(compact["from"], "a@example.com")
        self.assertTrue(compact["body_text"].endswith("…"))
        self.assertLessEqual(len(compact["body_text"]), 20)

    def test_compact_thread(self) -> None:
        thread = {
            "id": "t1",
            "snippet": "hello thread",
            "messages": [
                {
                    "id": "m1",
                    "threadId": "t1",
                    "labelIds": ["INBOX"],
                    "snippet": "one",
                    "payload": {
                        "headers": [{"name": "Subject", "value": "Hi"}],
                        "mimeType": "text/plain",
                        "body": {
                            "data": base64.urlsafe_b64encode(b"body").decode("ascii").rstrip("=")
                        },
                    },
                }
            ],
        }
        compact = compact_thread(thread, max_body_chars=100, include_bodies=True)
        self.assertEqual(compact["id"], "t1")
        self.assertEqual(compact["count"], 1)
        self.assertEqual(compact["messages"][0]["body_text"], "body")

    def test_compact_draft(self) -> None:
        draft = {
            "id": "d1",
            "message": {
                "id": "m-draft",
                "threadId": "t1",
                "snippet": "draft snippet",
                "payload": {
                    "headers": [
                        {"name": "To", "value": "user@example.com"},
                        {"name": "Subject", "value": "Draft"},
                    ],
                    "mimeType": "text/plain",
                    "body": {
                        "data": base64.urlsafe_b64encode(b"draft body").decode("ascii").rstrip("=")
                    },
                },
            },
        }
        compact = compact_draft(draft, max_body_chars=100, include_body=True)
        self.assertEqual(compact["id"], "d1")
        self.assertEqual(compact["subject"], "Draft")
        self.assertEqual(compact["body_text"], "draft body")

    def test_plain_body_from_message(self) -> None:
        message = {
            "snippet": "fallback",
            "payload": {
                "mimeType": "text/plain",
                "body": {
                    "data": base64.urlsafe_b64encode(b"hello").decode("ascii").rstrip("=")
                },
            },
        }
        self.assertEqual(plain_body_from_message(message), "hello")

    def test_compact_filter_and_vacation(self) -> None:
        filt = compact_filter(
            {
                "id": "f1",
                "criteria": {"from": "a@example.com"},
                "action": {"addLabelIds": ["Label_1"]},
            }
        )
        self.assertEqual(filt["id"], "f1")
        self.assertEqual(filt["criteria"]["from"], "a@example.com")

        vacation = compact_vacation(
            {
                "enableAutoReply": True,
                "responseSubject": "OOO",
                "startTime": "1700000000000",
            }
        )
        self.assertTrue(vacation["enable_auto_reply"])
        self.assertEqual(vacation["response_subject"], "OOO")


class GmailSendTests(unittest.TestCase):
    def test_build_send_payload(self) -> None:
        payload = build_send_payload(
            to=["user@example.com"],
            subject="Hello",
            body_text="Test body",
        )
        self.assertIn("raw", payload)
        self.assertTrue(payload["raw"])

    def test_build_send_payload_draft_without_recipients(self) -> None:
        payload = build_send_payload(
            to=[],
            subject="Draft",
            body_text="Later",
            require_recipients=False,
        )
        self.assertIn("raw", payload)

    def test_reply_subject(self) -> None:
        self.assertEqual(reply_subject("Hello"), "Re: Hello")
        self.assertEqual(reply_subject("Re: Hello"), "Re: Hello")

    def test_forward_subject(self) -> None:
        self.assertEqual(forward_subject("Hello"), "Fwd: Hello")
        self.assertEqual(forward_subject("Fwd: Hello"), "Fwd: Hello")

    def test_build_forward_body(self) -> None:
        body = build_forward_body(
            headers={
                "from": "a@example.com",
                "date": "Mon",
                "subject": "Hi",
                "to": "b@example.com",
            },
            body_text="Original",
            body_prefix="FYI",
        )
        self.assertIn("Forwarded message", body)
        self.assertIn("FYI", body)
        self.assertIn("Original", body)


class GmailGuardTests(unittest.TestCase):
    def test_require_permanent_confirm(self) -> None:
        _require_permanent_confirm({"confirm": True})
        with self.assertRaises(ValueError):
            _require_permanent_confirm({"confirm": False})
        with self.assertRaises(ValueError):
            _require_permanent_confirm({})

    def test_patch_send_as_body(self) -> None:
        body = _patch_send_as_body({"display_name": "Work", "is_default": True})
        self.assertEqual(body["displayName"], "Work")
        self.assertTrue(body["isDefault"])
        with self.assertRaises(ValueError):
            _patch_send_as_body({})


class GmailAuthTests(unittest.TestCase):
    def test_user_has_gmail_scope(self) -> None:
        store = GoogleTokenStore(db_path=":memory:")
        store.save(
            telegram_user_id=7,
            email="user@example.com",
            refresh_token="refresh",
            access_token="access",
            token_expiry=None,
            scopes=("https://www.googleapis.com/auth/calendar",),
        )
        stored = store.get(7)
        self.assertFalse(user_has_gmail_scope(stored))
        store.save(
            telegram_user_id=8,
            email="user2@example.com",
            refresh_token="refresh",
            access_token="access",
            token_expiry=None,
            scopes=(GMAIL_MODIFY_SCOPE,),
        )
        self.assertTrue(user_has_gmail_scope(store.get(8)))

    def test_auth_status_includes_gmail_ready(self) -> None:
        status = auth_status_payload(999999)
        self.assertIn("gmail_ready", status)
        self.assertFalse(status["gmail_ready"])


class GmailRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        with patch.dict(os.environ, {"TOOL_EMBEDDING_PROVIDER": "keyword"}, clear=False):
            self.runtime = await create_tool_runtime()

    async def test_gmail_tools_registered_with_tags(self) -> None:
        names = {
            tool.name
            for tool in self.runtime._registry.all()
            if tool.name.startswith("google.gmail.")
        }
        self.assertEqual(names, MAIL5_TOOL_NAMES)
        for tool in self.runtime._registry.all():
            if not tool.name.startswith("google.gmail."):
                continue
            self.assertIn("google", tool.tags)
            self.assertIn("gmail", tool.tags)

    async def test_write_tools_have_write_tag(self) -> None:
        write_names = {
            "google.gmail.modify_message",
            "google.gmail.send_message",
            "google.gmail.delete_message",
            "google.gmail.create_filter",
            "google.gmail.update_vacation_settings",
            "google.gmail.patch_send_as",
            "google.gmail.import_message",
        }
        for tool in self.runtime._registry.all():
            if tool.name in write_names:
                self.assertIn("write", tool.tags)

    async def test_settings_tools_have_settings_tag(self) -> None:
        settings_names = {
            "google.gmail.list_filters",
            "google.gmail.get_vacation_settings",
            "google.gmail.list_send_as",
        }
        for tool in self.runtime._registry.all():
            if tool.name in settings_names:
                self.assertIn("settings", tool.tags)

    async def test_search_tools_gmail_catalog(self) -> None:
        result = await self.runtime.search_tools("", tags=["google", "gmail"], mode="catalog")
        self.assertEqual(result["count"], 45)
        names = {tool["name"] for tool in result["tools"]}
        self.assertEqual(names, MAIL5_TOOL_NAMES)


if __name__ == "__main__":
    unittest.main()
