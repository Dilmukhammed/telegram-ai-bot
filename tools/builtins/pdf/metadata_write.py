from __future__ import annotations

import asyncio
import io
from typing import Any

from pypdf import PdfReader, PdfWriter

from tools.builtins.pdf.io import resolve_input
from tools.builtins.pdf.pages import save_output_sync


def _set_metadata_sync(
    data: bytes,
    title: str | None,
    author: str | None,
    subject: str | None,
    keywords: str | None,
    creator: str | None,
    producer: str | None,
) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    writer = PdfWriter(clone_from=reader)

    metadata: dict[str, Any] = {}
    if title is not None:
        metadata["/Title"] = title
    if author is not None:
        metadata["/Author"] = author
    if subject is not None:
        metadata["/Subject"] = subject
    if keywords is not None:
        metadata["/Keywords"] = keywords
    if creator is not None:
        metadata["/Creator"] = creator
    if producer is not None:
        metadata["/Producer"] = producer

    if metadata:
        writer.add_metadata(metadata)

    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "metadata_updated.pdf")

    set_fields = {k.lstrip("/"): v for k, v in metadata.items()}
    return {
        "ok": True,
        "page_count": total,
        "updated_fields": set_fields,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _set_metadata_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    title = arguments.get("title")
    author = arguments.get("author")
    subject = arguments.get("subject")
    keywords = arguments.get("keywords")
    creator = arguments.get("creator")
    producer = arguments.get("producer")
    if not any(v is not None for v in (title, author, subject, keywords, creator, producer)):
        return {"ok": False, "error": "At least one metadata field is required"}
    return await asyncio.to_thread(
        _set_metadata_sync, data, title, author, subject, keywords, creator, producer
    )


def _set_outline_sync(data: bytes, outline: list[dict[str, Any]]) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    writer = PdfWriter(clone_from=reader)

    added: list[dict[str, Any]] = []

    def _build(items: list[dict[str, Any]], parent: Any = None) -> None:
        for item in items:
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            page_num = int(item.get("page", 1))
            idx = page_num - 1
            if idx < 0 or idx >= total:
                continue
            children = item.get("children") or []
            level = int(item.get("level", 0))
            bookmark = writer.add_outline_item(
                title=title,
                page_number=idx,
                parent=parent,
            )
            added.append({"title": title, "page": page_num, "level": level})
            if children:
                _build(children, parent=bookmark)

    _build(outline)

    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "outline_updated.pdf")
    return {
        "ok": True,
        "page_count": total,
        "bookmarks_added": len(added),
        "outline": added,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _set_outline_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    outline = arguments.get("outline") or []
    if not isinstance(outline, list) or not outline:
        return {"ok": False, "error": "outline (array) is required"}
    return await asyncio.to_thread(_set_outline_sync, data, outline)


def _add_bookmark_sync(
    data: bytes, title: str, page: int, level: int
) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    idx = page - 1
    if idx < 0 or idx >= total:
        return {"ok": False, "error": f"page {page} does not exist (1-{total})"}

    writer = PdfWriter(clone_from=reader)

    existing = writer.outline
    parent = None
    if level > 0 and existing:
        flat: list[Any] = []
        for item in existing:
            if isinstance(item, list):
                flat.extend(item)
        for item in flat:
            try:
                item_level = getattr(item, "level", 0) or 0
                if item_level == level - 1:
                    parent = item
                    break
            except Exception:
                pass

    writer.add_outline_item(title=title, page_number=idx, parent=parent)

    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "bookmark_added.pdf")
    return {
        "ok": True,
        "page_count": total,
        "bookmark": {"title": title, "page": page, "level": level},
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _add_bookmark_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    title = str(arguments.get("title", "")).strip()
    if not title:
        return {"ok": False, "error": "title is required"}
    page = int(arguments.get("page", 1))
    level = int(arguments.get("level", 0))
    return await asyncio.to_thread(_add_bookmark_sync, data, title, page, level)
