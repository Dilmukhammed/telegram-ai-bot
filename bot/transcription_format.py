import html
from typing import Literal

AudioSource = Literal["voice", "audio"]

_SUMMARY_LABELS: dict[AudioSource, str] = {
    "voice": "Транскрипция",
    "audio": "Транскрипция · аудио",
}


def format_transcription_chat(text: str, source: AudioSource) -> str:
    summary = _SUMMARY_LABELS[source]
    body = text.strip() or "—"
    escaped = html.escape(body, quote=False)
    return (
        f"<details>\n"
        f"<summary>{summary}</summary>\n\n"
        f"<blockquote>{escaped}</blockquote>\n"
        f"</details>"
    )


def format_transcription_agent(text: str, source: AudioSource) -> str:
    body = text.strip()
    tag = "voice" if source == "voice" else "audio"
    if not body:
        return f"[transcription:{tag}]\n(empty)"
    return f"[transcription:{tag}]\n{body}"


def wrap_transcription(text: str, source: AudioSource) -> str:
    """Agent-facing wrapper (kept for compatibility)."""
    return format_transcription_agent(text, source)
