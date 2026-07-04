import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InputRichMessage

from config import get_settings
from rich_format import prepare_telegram_rich_markdown

logger = logging.getLogger(__name__)

_DEFAULT_TYPING_INTERVAL = 5.0
_MIN_DRAFT_SEND_INTERVAL = 2.0


class TelegramDraftStreamer:
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        draft_id: int,
        message_thread_id: int | None = None,
    ) -> None:
        settings = get_settings()
        self._rich_limit = settings.telegram_rich_limit
        self._plain_limit = settings.telegram_plain_limit
        self._update_interval = settings.draft_update_interval
        self._keepalive_interval = settings.draft_keepalive_interval
        self._typing_interval = settings.draft_typing_interval

        self._bot = bot
        self._chat_id = chat_id
        self._draft_id = draft_id
        self._message_thread_id = message_thread_id
        self._last_update_at = 0.0
        self._last_draft_sent_at = 0.0
        self._last_typing_sent_at = 0.0
        self._activity_started_at = 0.0
        self._use_rich_draft = True
        self._use_rich_finalize = True
        self._activity_log: list[str] = []
        self._current_markdown = ""
        self._closed = False
        self._keepalive_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Show initial draft immediately, before the first LLM response."""
        await self.stream_status("Думаю…")

    async def __aenter__(self) -> "TelegramDraftStreamer":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if not self._closed:
            await self.aclose()
        return False

    def _rich_message(self, markdown: str) -> InputRichMessage:
        return InputRichMessage(
            markdown=prepare_telegram_rich_markdown(markdown)[: self._rich_limit]
        )

    def _activity_markdown(self) -> str:
        if not self._activity_log:
            return "**Сейчас:**\n- Думаю…"
        lines = "\n".join(f"- {item}" for item in self._activity_log)
        return f"**Сейчас:**\n{lines}"

    def _draft_with_pulse(self) -> str:
        if not self._current_markdown:
            return ""
        if not self._activity_started_at:
            return self._current_markdown
        elapsed = int(time.monotonic() - self._activity_started_at)
        if elapsed < 2:
            return self._current_markdown
        dots = "." * ((elapsed // 2) % 3 + 1)
        return f"{self._current_markdown}\n\n_⏳ {elapsed}с{dots}_"

    async def _send_draft_once(self, markdown: str) -> None:
        if self._use_rich_draft:
            try:
                await self._bot.send_rich_message_draft(
                    chat_id=self._chat_id,
                    draft_id=self._draft_id,
                    message_thread_id=self._message_thread_id,
                    rich_message=self._rich_message(markdown),
                )
                return
            except TelegramBadRequest as exc:
                logger.warning("Rich draft failed, using plain draft: %s", exc.message)
                self._use_rich_draft = False

        await self._bot.send_message_draft(
            chat_id=self._chat_id,
            draft_id=self._draft_id,
            message_thread_id=self._message_thread_id,
            text=markdown[: self._plain_limit],
        )

    async def _send_draft_resilient(self, markdown: str) -> bool:
        for attempt in range(2):
            try:
                await self._send_draft_once(markdown)
                return True
            except TelegramRetryAfter as exc:
                wait = max(float(exc.retry_after), 1.0)
                logger.warning(
                    "Draft flood control chat=%s draft=%s retry_after=%ss attempt=%s",
                    self._chat_id,
                    self._draft_id,
                    wait,
                    attempt + 1,
                )
                if attempt == 0:
                    await asyncio.sleep(wait)
                    continue
                return False
            except Exception:
                logger.warning(
                    "Draft send failed for chat=%s draft=%s",
                    self._chat_id,
                    self._draft_id,
                    exc_info=True,
                )
                return False
        return False

    async def _send_typing_resilient(self) -> None:
        now = time.monotonic()
        if now - self._last_typing_sent_at < self._typing_interval:
            return
        try:
            await self._bot.send_chat_action(self._chat_id, "typing")
            self._last_typing_sent_at = now
        except TelegramRetryAfter as exc:
            logger.warning(
                "Typing flood control chat=%s retry_after=%ss",
                self._chat_id,
                exc.retry_after,
            )
        except Exception:
            logger.warning("Typing action failed for chat=%s", self._chat_id, exc_info=True)

    def _start_keepalive(self) -> None:
        if self._closed or self._keepalive_task is not None:
            return
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(),
            name=f"draft-keepalive:{self._chat_id}:{self._draft_id}",
        )

    async def _stop_keepalive(self) -> None:
        task = self._keepalive_task
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        self._keepalive_task = None

    async def _keepalive_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(self._keepalive_interval)
                if self._closed:
                    break
                if self._current_markdown:
                    await self._send_draft_resilient(self._draft_with_pulse())
                    self._last_draft_sent_at = time.monotonic()
                await self._send_typing_resilient()
        except asyncio.CancelledError:
            pass

    async def push_draft(self, markdown: str | None = None, *, force: bool = False) -> None:
        if self._closed:
            return
        text = markdown or ""
        now = time.monotonic()
        if (
            not force
            and text == self._current_markdown
            and now - self._last_draft_sent_at < _MIN_DRAFT_SEND_INTERVAL
        ):
            return

        if text and not self._activity_started_at:
            self._activity_started_at = time.monotonic()

        self._current_markdown = text
        if await self._send_draft_resilient(text):
            self._last_draft_sent_at = time.monotonic()
        self._start_keepalive()

    async def stream_status(self, status: str) -> None:
        if not self._activity_log or self._activity_log[-1] != status:
            self._activity_log.append(status)
        self._activity_started_at = time.monotonic()
        await self.push_draft(self._activity_markdown(), force=True)
        await self._send_typing_resilient()

    async def stream_tokens(self, tokens: AsyncIterator[str]) -> str:
        await self.stream_status("Думаю…")

        parts: list[str] = []
        async for token in tokens:
            parts.append(token)
            now = time.monotonic()
            if now - self._last_update_at >= self._update_interval:
                preview = "".join(parts)
                await self.push_draft(f"{self._activity_markdown()}\n\n{preview}")
                self._last_update_at = now
            await asyncio.sleep(0)

        reply = "".join(parts).strip()
        if reply:
            await self.push_draft(f"{self._activity_markdown()}\n\n{reply}", force=True)
        return reply

    async def stream_prefilled(self, text: str) -> str:
        await self.stream_status("Формирую ответ…")

        words = text.split()
        if not words:
            return text

        built: list[str] = []
        for index, word in enumerate(words):
            built.append(word)
            now = time.monotonic()
            if index == len(words) - 1 or now - self._last_update_at >= self._update_interval:
                preview = " ".join(built)
                await self.push_draft(f"{self._activity_markdown()}\n\n{preview}")
                self._last_update_at = now
            await asyncio.sleep(0)

        return text

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._stop_keepalive()

    async def finalize(
        self,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        await self.aclose()
        if self._use_rich_finalize:
            try:
                chunks = split_message(text, self._rich_limit)
                for index, chunk in enumerate(chunks):
                    await self._bot.send_rich_message(
                        chat_id=self._chat_id,
                        message_thread_id=self._message_thread_id,
                        rich_message=self._rich_message(chunk),
                        reply_markup=reply_markup if index == len(chunks) - 1 else None,
                    )
                return
            except TelegramBadRequest as exc:
                logger.warning("Rich message failed, using plain text: %s", exc.message)
                self._use_rich_finalize = False

        chunks = split_message(text, self._plain_limit)
        for index, chunk in enumerate(chunks):
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=self._message_thread_id,
                text=chunk,
                parse_mode=None,
                reply_markup=reply_markup if index == len(chunks) - 1 else None,
            )


def split_message(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n\n", 0, limit)
        if split_at <= 0:
            split_at = text.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(text[:split_at].rstrip())
        text = text[split_at:].lstrip("\n")
    return chunks
