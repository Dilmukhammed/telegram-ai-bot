from exa_py import AsyncExa

from config import get_settings

_client: AsyncExa | None = None


def get_exa_client() -> AsyncExa:
    global _client
    if _client is None:
        api_key = get_settings().exa_api_key
        if not api_key:
            raise RuntimeError("EXA_API_KEY is not set")
        _client = AsyncExa(api_key=api_key)
    return _client
