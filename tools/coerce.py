from typing import Any


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _pick_query(arguments: dict[str, Any]) -> str | None:
    for key in ("query", "q", "search", "search_query", "text"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    nested = arguments.get("url_or_query_arguments")
    if isinstance(nested, dict):
        value = nested.get("query")
        if isinstance(value, str) and value.strip():
            return value.strip()

    reason = arguments.get("reason")
    if isinstance(reason, str) and reason.strip() and "query" not in arguments:
        return reason.strip()

    return None


def normalize_use_tool_call(raw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tool_name = _coerce_str(raw.get("tool_name"))
    inner = dict(raw.get("arguments") or {})

    if not tool_name and inner.get("tool_name") is not None:
        tool_name = _coerce_str(inner.pop("tool_name"))

    if isinstance(inner.get("arguments"), dict):
        inner = dict(inner.pop("arguments"))

    if tool_name == "exa.web_search":
        query = _pick_query(inner)
        if query:
            normalized = {"query": query}
            if "num_results" in inner:
                normalized["num_results"] = inner["num_results"]
            if "type" in inner:
                normalized["type"] = inner["type"]
            inner = normalized

    if tool_name == "google.maps.places_text_search":
        if not str(inner.get("text_query", "")).strip():
            text_query = _pick_query(inner)
            if text_query:
                inner["text_query"] = text_query
        for alias in ("query", "q", "search", "search_query", "text"):
            inner.pop(alias, None)

    if tool_name == "google.maps.places_autocomplete":
        if not str(inner.get("input", "")).strip():
            picked = _pick_query(inner)
            if picked:
                inner["input"] = picked
        for alias in ("query", "q", "search", "search_query", "text"):
            inner.pop(alias, None)

    for noise_key in ("reason", "explanation", "why", "url_or_query_arguments"):
        inner.pop(noise_key, None)

    if tool_name == "exa.web_fetch":
        urls = inner.get("urls")
        if isinstance(urls, str):
            inner = {"urls": [urls]}
        elif isinstance(urls, list):
            inner = {"urls": [str(url) for url in urls if str(url).strip()]}

    if tool_name == "echo.test":
        message = inner.get("message")
        if isinstance(message, str) and message.strip():
            inner = {"message": message.strip()}

    return tool_name, inner


def filter_known_arguments(spec_properties: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if key in spec_properties}
