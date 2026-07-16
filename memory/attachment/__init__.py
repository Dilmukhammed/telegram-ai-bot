"""Graph memory PR14 attachment engine (shadow-only, default off)."""

from memory.attachment.pipeline import analyze_attachment
from memory.attachment.schemas import ATTACHMENT_VERSION, AttachmentConfig

__all__ = [
    "ATTACHMENT_VERSION",
    "AttachmentConfig",
    "analyze_attachment",
]
