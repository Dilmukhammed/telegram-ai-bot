from bot.chat_store.models import ChatMessage, ChatPeriodSummary, ChatSession, ChatSessionTrace
from bot.chat_store.period_boundary import enqueue_period_boundary_loop
from bot.chat_store.period_summary import enqueue_period_refresh_for_session
from bot.chat_store.store import ChatStore
from bot.chat_store.summary import enqueue_session_summary

_store: ChatStore | None = None


def get_chat_store() -> ChatStore:
    global _store
    if _store is None:
        _store = ChatStore()
    return _store


def reset_chat_store(store: ChatStore | None = None) -> None:
    global _store
    _store = store


__all__ = [
    "ChatMessage",
    "ChatPeriodSummary",
    "ChatSession",
    "ChatSessionTrace",
    "ChatStore",
    "enqueue_period_boundary_loop",
    "enqueue_period_refresh_for_session",
    "enqueue_session_summary",
    "get_chat_store",
    "reset_chat_store",
]
