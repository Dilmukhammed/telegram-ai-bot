import base64
from unittest.mock import AsyncMock, patch

import pytest

from config import get_settings
from tools.context import RunContext, reset_run_context, set_run_context
from tools.outbound_files import OutboundQueue, reset_outbound_queue, set_outbound_queue
from tools.run_files import RunFileStore, reset_run_file_store, set_run_file_store
from tools.builtins.telegram_send import _send_file_handler
from tools.telegram_limits import format_byte_size, resolve_send_kind, telegram_limit_error


@pytest.fixture
def run_context():
    store = RunFileStore(run_id="abc12345", user_id=42)
    queue = OutboundQueue()
    store_token = set_run_file_store(store)
    queue_token = set_outbound_queue(queue)
    ctx_token = set_run_context(RunContext(user_id=42))
    try:
        yield store, queue
    finally:
        reset_run_context(ctx_token)
        reset_outbound_queue(queue_token)
        reset_run_file_store(store_token)
        store.cleanup()


def test_format_byte_size():
    assert format_byte_size(50 * 1024 * 1024) == "50 MB"
    assert format_byte_size(10 * 1024 * 1024) == "10 MB"


def test_resolve_send_kind_auto():
    assert resolve_send_kind("auto", "image/png") == "photo"
    assert resolve_send_kind("auto", "application/pdf") == "document"


def test_run_file_store_save_and_resolve(run_context):
    store, _ = run_context
    payload = store.save(b"hello", filename="note.txt", mime_type="text/plain")
    assert payload["file_ref"].startswith("abc12345:")
    stored = store.resolve(str(payload["file_ref"]))
    assert stored.path.read_bytes() == b"hello"


@pytest.mark.asyncio
async def test_send_file_from_workspace_path(run_context, tmp_path):
    store, queue = run_context
    with patch("tools.builtins.telegram_send.read_workspace_bytes") as read_bytes:
        read_bytes.return_value = (
            tmp_path / "note.txt",
            b"hello workspace",
            "text/plain",
        )
        result = await _send_file_handler({"path": "agent/note.txt"})
    assert result["ok"] is True
    assert result["path"] == "agent/note.txt"
    items = queue.snapshot()
    assert len(items) == 1
    assert items[0].data.startswith(b"\xef\xbb\xbf") or items[0].data == b"hello workspace"


@pytest.mark.asyncio
async def test_send_file_requires_xor_source(run_context):
    with pytest.raises(ValueError, match="exactly one"):
        await _send_file_handler({})
    store, _ = run_context
    saved = store.save(b"x", filename="a.txt", mime_type="text/plain")
    with pytest.raises(ValueError, match="exactly one"):
        await _send_file_handler({"file_ref": saved["file_ref"], "path": "agent/a.txt"})


@pytest.mark.asyncio
async def test_send_file_queues_document(run_context):
    store, queue = run_context
    saved = store.save(b"%PDF-1.4", filename="doc.pdf", mime_type="application/pdf")
    result = await _send_file_handler({"file_ref": saved["file_ref"]})
    assert result["ok"] is True
    assert result["queued"] is True
    items = queue.snapshot()
    assert len(items) == 1
    assert items[0].filename == "doc.pdf"
    assert items[0].data == b"%PDF-1.4"


@pytest.mark.asyncio
async def test_send_file_rejects_over_telegram_photo_limit(run_context):
    store, queue = run_context
    settings = get_settings()
    too_large = settings.telegram_max_photo_bytes + 1
    saved = store.save(b"x" * too_large, filename="big.png", mime_type="image/png")
    result = await _send_file_handler({"file_ref": saved["file_ref"], "as": "photo"})
    assert result["ok"] is False
    assert "too large" in result["error"].lower()
    assert result["telegram_limit_bytes"] == settings.telegram_max_photo_bytes
    assert "10 MB" in result["telegram_limit"]
    assert not queue.snapshot()


@pytest.mark.asyncio
async def test_download_file_returns_file_ref(run_context):
    from tools.builtins.google.drive_files import download_file_handler

    pdf_bytes = b"%PDF-test"

    with patch(
        "tools.builtins.google.drive_files.run_drive_call",
        new=AsyncMock(
            side_effect=[
                {"id": "f1", "name": "report.pdf", "mimeType": "application/pdf", "size": len(pdf_bytes)},
                pdf_bytes,
            ]
        ),
    ):
        result = await download_file_handler({"file_id": "f1"})

    assert result["ok"] is True
    assert "file_ref" in result
    assert "content_base64" not in result


@pytest.mark.asyncio
async def test_get_attachment_returns_file_ref(run_context):
    from tools.builtins.google.gmail_tools import _get_attachment_handler

    encoded = base64.urlsafe_b64encode(b"invoice").decode("ascii").rstrip("=")
    with patch(
        "tools.builtins.google.gmail_tools._run_gmail_call",
        new=AsyncMock(
            side_effect=[
                {
                    "payload": {
                        "parts": [
                            {
                                "filename": "invoice.pdf",
                                "mimeType": "application/pdf",
                                "body": {"attachmentId": "att1", "size": 7},
                            }
                        ]
                    }
                },
                {"size": 7, "data": encoded},
            ]
        ),
    ):
        result = await _get_attachment_handler(
            {"message_id": "m1", "attachment_id": "att1"}
        )

    assert result["ok"] is True
    assert result["file_ref"]
    assert "data_base64" not in result


def test_telegram_limit_error_message():
    msg = telegram_limit_error(size_bytes=52_000_000, kind="document", limit_bytes=50 * 1024 * 1024)
    assert "50 MB" in msg
    assert "document" in msg


def test_utf8_bom_for_cyrillic_text_file():
    from tools.text_file_encoding import UTF8_BOM, ensure_utf8_bom_for_mobile

    text = "Идеи по развитию AI-агента".encode("utf-8")
    fixed = ensure_utf8_bom_for_mobile(
        text,
        filename="plan.md",
        mime_type="text/plain",
    )
    assert fixed.startswith(UTF8_BOM)
    assert fixed.decode("utf-8-sig") == "Идеи по развитию AI-агента"


def test_ensure_filename_extension_for_pdf():
    from tools.filename_utils import ensure_filename_extension

    assert (
        ensure_filename_extension("Elden Ring Quest Guide", "application/pdf")
        == "Elden Ring Quest Guide.pdf"
    )
    assert ensure_filename_extension("report.pdf", "application/pdf") == "report.pdf"
    assert ensure_filename_extension("data.csv", "text/csv") == "data.csv"
