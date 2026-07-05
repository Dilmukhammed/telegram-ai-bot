from __future__ import annotations

import asyncio
import io
import re
from typing import Any

from pypdf import PdfReader

from tools.builtins.pdf.io import parse_pages_spec, resolve_input

_MAX_SEARCH_RESULTS = 50
_SNIPPET_CONTEXT_CHARS = 80


def _get_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _search_text_sync(
    data: bytes,
    query: str,
    pages: list[int] | None,
    case_sensitive: bool,
    whole_words: bool,
    max_results: int,
) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    target_pages = pages if pages is not None else list(range(1, total + 1))
    results: list[dict[str, Any]] = []
    if whole_words:
        pattern_str = r"\b" + re.escape(query) + r"\b"
    else:
        pattern_str = re.escape(query)
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(pattern_str, flags)
    for page_num in target_pages:
        if len(results) >= max_results:
            break
        idx = page_num - 1
        if idx < 0 or idx >= total:
            continue
        page = reader.pages[idx]
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        for match in pattern.finditer(text):
            start = max(0, match.start() - _SNIPPET_CONTEXT_CHARS)
            end = min(len(text), match.end() + _SNIPPET_CONTEXT_CHARS)
            snippet = text[start:end].strip()
            if start > 0:
                snippet = "…" + snippet
            if end < len(text):
                snippet = snippet + "…"
            results.append(
                {
                    "page": page_num,
                    "match": match.group(),
                    "position": match.start(),
                    "snippet": snippet,
                }
            )
            if len(results) >= max_results:
                break
    return {
        "ok": True,
        "page_count": total,
        "query": query,
        "results_found": len(results),
        "results": results,
    }


async def _search_text_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    query = str(arguments.get("query", "")).strip()
    if not query:
        return {"ok": False, "error": "query is required"}
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    case_sensitive = bool(arguments.get("case_sensitive", False))
    whole_words = bool(arguments.get("whole_words", False))
    max_results = int(arguments.get("max_results", _MAX_SEARCH_RESULTS))
    return await asyncio.to_thread(
        _search_text_sync, data, query, pages, case_sensitive, whole_words, max_results
    )


def _extract_forms_sync(data: bytes) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    fields: list[dict[str, Any]] = []
    if not reader.get_fields():
        return {
            "ok": True,
            "page_count": total,
            "has_forms": False,
            "fields": [],
        }
    raw_fields = reader.get_fields()
    for name, field in raw_fields.items():
        field_obj = field.get_object() if hasattr(field, "get_object") else field
        field_type = str(field_obj.get("/FT", ""))
        field_type_clean = field_type.replace("/", "").lower()
        value = field_obj.get("/V")
        value_str = ""
        if value is not None:
            try:
                if hasattr(value, "get_object"):
                    value = value.get_object()
                if isinstance(value, (str, int, float, bool)):
                    value_str = str(value)
                else:
                    value_str = str(value)
            except Exception:
                value_str = ""
        opts: list[str] = []
        try:
            opts_obj = field_obj.get("/Opt")
            if opts_obj:
                for opt in opts_obj:
                    if isinstance(opt, (str, int, float)):
                        opts.append(str(opt))
                    elif hasattr(opt, "get_object"):
                        opts.append(str(opt.get_object()))
        except Exception:
            pass
        required = bool(field_obj.get("/Ff") and int(field_obj.get("/Ff")) & 2)
        page_num = 0
        try:
            page = field_obj.get("/P")
            if page and hasattr(page, "get_object"):
                page_obj = page.get_object()
                if page_obj in reader.pages:
                    page_num = reader.pages.index(page_obj) + 1
        except Exception:
            pass
        fields.append(
            {
                "name": str(name),
                "type": field_type_clean or "text",
                "value": value_str,
                "page": page_num,
                "required": required,
                "options": opts[:50] if opts else [],
            }
        )
    return {
        "ok": True,
        "page_count": total,
        "has_forms": True,
        "fields_found": len(fields),
        "fields": fields,
    }


async def _extract_forms_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return await asyncio.to_thread(_extract_forms_sync, data)
