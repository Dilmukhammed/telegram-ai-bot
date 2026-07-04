from dataclasses import dataclass
from datetime import datetime

from aiogram.types import Message

from config import get_settings


@dataclass(frozen=True)
class ChatRequest:
    message: Message
    user_text: str
    image_data_urls: list[str] | None = None


def _looks_like_telegram_split(texts: list[str]) -> bool:
    if len(texts) < 2:
        return False
    min_chars = get_settings().telegram_split_min_chars
    return any(len(text) >= min_chars for text in texts[:-1])

def merge_chat_requests(
    requests: list[ChatRequest],
) -> tuple[Message, str, list[str] | None, datetime]:
    if not requests:
        raise ValueError("Cannot merge empty request list")

    if len(requests) == 1:
        request = requests[0]
        return request.message, request.user_text, request.image_data_urls, request.message.date

    texts: list[str] = []
    images: list[str] = []
    for request in requests:
        text = request.user_text.strip()
        if text:
            texts.append(text)
        if request.image_data_urls:
            images.extend(request.image_data_urls)

    if _looks_like_telegram_split(texts):
        merged_text = "".join(texts)
    else:
        merged_text = "\n\n".join(texts)
    last = requests[-1]
    return last.message, merged_text, images or None, last.message.date
