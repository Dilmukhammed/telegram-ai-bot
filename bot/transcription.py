import logging
import tempfile
from pathlib import Path

from aiogram import Bot
from aiogram.types import Audio, Message, Voice
from openai import AsyncOpenAI

from config import get_settings

logger = logging.getLogger(__name__)


class TranscriptionError(RuntimeError):
    pass


class GroqTranscriber:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise TranscriptionError("GROQ_API_KEY is not set")

        self._model = settings.groq_transcription_model
        self._language = settings.groq_transcription_language
        self._client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)

    async def transcribe_telegram_audio(self, bot: Bot, audio: Voice | Audio) -> str:
        telegram_file = await bot.get_file(audio.file_id)
        suffix = _suffix_for_mime(getattr(audio, "mime_type", None))
        temp_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                temp_path = Path(tmp.name)
            await bot.download(telegram_file, destination=temp_path)
            return await self.transcribe_file(temp_path)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    async def transcribe_file(self, path: Path) -> str:
        with path.open("rb") as audio_file:
            kwargs: dict = {
                "model": self._model,
                "file": audio_file,
            }
            if self._language:
                kwargs["language"] = self._language

            response = await self._client.audio.transcriptions.create(**kwargs)

        text = (response.text or "").strip()
        if not text:
            raise TranscriptionError("Groq returned empty transcription")
        logger.info("Transcribed audio (%s chars) with model %s", len(text), self._model)
        return text


def _suffix_for_mime(mime_type: str | None) -> str:
    mapping = {
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/wav": ".wav",
        "audio/webm": ".webm",
    }
    if mime_type and mime_type in mapping:
        return mapping[mime_type]
    return ".ogg"


def get_transcriber() -> GroqTranscriber:
    return GroqTranscriber()
