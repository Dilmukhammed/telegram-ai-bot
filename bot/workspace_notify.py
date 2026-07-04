from __future__ import annotations

from tools.workspace.inbound import SavedInboundFile
from bot.vision import history_text_for_image_turn
from config import format_byte_size


def format_document_agent_message(saved: SavedInboundFile, *, caption: str = "") -> str:
    blocks = []
    if caption.strip():
        blocks.append(caption.strip())
    blocks.append(
        "[file uploaded: "
        f"path={saved.path}, "
        f"size={format_byte_size(saved.size_bytes)}, "
        f"mime={saved.mime_type or 'unknown'}]"
    )
    return "\n".join(blocks)


def format_photo_agent_message(*, caption: str, saved: SavedInboundFile) -> str:
    image_line = history_text_for_image_turn(caption)
    return f"{image_line}\n[workspace: path={saved.path}]"
