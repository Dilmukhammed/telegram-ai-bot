import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramRetryAfter

from streaming import TelegramDraftStreamer


@pytest.fixture
def mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_rich_message_draft = AsyncMock()
    bot.send_message_draft = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.send_rich_message = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def streamer(mock_bot: MagicMock) -> TelegramDraftStreamer:
    with patch("streaming.get_settings") as get_settings:
        settings = MagicMock()
        settings.telegram_rich_limit = 32768
        settings.telegram_plain_limit = 4096
        settings.draft_update_interval = 0.35
        settings.draft_keepalive_interval = 0.05
        settings.draft_typing_interval = 0.05
        get_settings.return_value = settings
        return TelegramDraftStreamer(
            bot=mock_bot,
            chat_id=1,
            draft_id=42,
        )


@pytest.mark.asyncio
async def test_keepalive_refreshes_draft_during_idle(streamer: TelegramDraftStreamer, mock_bot: MagicMock) -> None:
    await streamer.stream_status("Думаю…")
    initial_calls = mock_bot.send_rich_message_draft.await_count

    await asyncio.sleep(0.12)

    assert mock_bot.send_rich_message_draft.await_count > initial_calls
    last_call = mock_bot.send_rich_message_draft.await_args_list[-1]
    assert "Думаю" in last_call.kwargs["rich_message"].markdown


@pytest.mark.asyncio
async def test_keepalive_stops_on_finalize(streamer: TelegramDraftStreamer, mock_bot: MagicMock) -> None:
    await streamer.stream_status("Думаю…")
    await streamer.finalize("Готово")

    calls_after_finalize = mock_bot.send_rich_message_draft.await_count
    await asyncio.sleep(0.12)
    assert mock_bot.send_rich_message_draft.await_count == calls_after_finalize


@pytest.mark.asyncio
async def test_aclose_stops_keepalive_without_sending_message(
    streamer: TelegramDraftStreamer,
    mock_bot: MagicMock,
) -> None:
    await streamer.stream_status("Расшифровываю аудио…")
    await streamer.aclose()

    draft_calls = mock_bot.send_rich_message_draft.await_count
    await asyncio.sleep(0.12)
    assert mock_bot.send_rich_message_draft.await_count == draft_calls
    mock_bot.send_rich_message.assert_not_called()
    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_draft_with_pulse_shows_elapsed(streamer: TelegramDraftStreamer) -> None:
    streamer._current_markdown = "**Сейчас:**\n- Ищу инструмент: drive"
    streamer._activity_started_at = time.monotonic() - 5
    pulse = streamer._draft_with_pulse()
    assert "⏳ 5с" in pulse
    assert "drive" in pulse


@pytest.mark.asyncio
async def test_stream_status_survives_draft_flood_control(
    streamer: TelegramDraftStreamer,
    mock_bot: MagicMock,
) -> None:
    calls = {"count": 0}

    async def flaky_draft(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TelegramRetryAfter(
                method="sendRichMessageDraft",
                message="Too Many Requests",
                retry_after=0,
            )

    mock_bot.send_rich_message_draft = AsyncMock(side_effect=flaky_draft)

    await streamer.stream_status("Думаю…")

    assert calls["count"] == 2
    assert streamer._activity_log[-1] == "Думаю…"


@pytest.mark.asyncio
async def test_context_manager_starts_draft_on_enter(
    streamer: TelegramDraftStreamer,
    mock_bot: MagicMock,
) -> None:
    async with streamer:
        assert streamer._activity_log == ["Думаю…"]
        assert mock_bot.send_rich_message_draft.await_count >= 1
        last_call = mock_bot.send_rich_message_draft.await_args_list[-1]
        assert "Думаю" in last_call.kwargs["rich_message"].markdown


@pytest.mark.asyncio
async def test_context_manager_closes_on_exit(streamer: TelegramDraftStreamer, mock_bot: MagicMock) -> None:
    async with streamer:
        pass

    draft_calls = mock_bot.send_rich_message_draft.await_count
    await asyncio.sleep(0.12)
    assert mock_bot.send_rich_message_draft.await_count == draft_calls
