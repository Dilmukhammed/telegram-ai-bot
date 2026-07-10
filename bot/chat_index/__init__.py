from bot.chat_index.sync import (
    delete_tool_result_chunks_for_user,
    enqueue_index_session,
    enqueue_index_tool_result,
    index_session_summary,
    rebuild_user_index,
)

__all__ = [
    "delete_tool_result_chunks_for_user",
    "enqueue_index_session",
    "enqueue_index_tool_result",
    "index_session_summary",
    "rebuild_user_index",
]


async def search_chat_chunks(*args, **kwargs):
    from bot.chat_index.search import search_chat_chunks as _search

    return await _search(*args, **kwargs)
