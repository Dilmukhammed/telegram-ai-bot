from typing import Any

from config import get_settings

_client: Any | None = None


def get_exa_client() -> Any:
    global _client
    if _client is None:
        try:
            from exa_py import AsyncExa
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The optional exa-py package is required only for exa web tools"
            ) from exc
        api_key = get_settings().exa_api_key
        if not api_key:
            raise RuntimeError("EXA_API_KEY is not set")
        _client = AsyncExa(api_key=api_key)
    return _client
