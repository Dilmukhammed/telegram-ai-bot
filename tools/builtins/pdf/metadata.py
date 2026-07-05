from __future__ import annotations

import asyncio
import io
from typing import Any

from pypdf import PdfReader
from pypdf.generic import Destination

from tools.builtins.pdf.io import parse_pages_spec, resolve_input


def _get_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _read_metadata_sync(data: bytes) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    meta = reader.metadata
    info: dict[str, Any] = {
        "page_count": len(reader.pages),
        "encrypted": reader.is_encrypted,
        "pdf_version": getattr(reader, "pdf_header", ""),
    }
    if meta:
        info["title"] = str(meta.title or "")
        info["author"] = str(meta.author or "")
        info["subject"] = str(meta.subject or "")
        info["keywords"] = str(meta.keywords or "")
        info["creator"] = str(meta.creator or "")
        info["producer"] = str(meta.producer or "")
        info["creation_date"] = str(meta.creation_date or "")
        info["mod_date"] = str(meta.modification_date or "")
    return {"ok": True, **info}


async def _read_metadata_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return await asyncio.to_thread(_read_metadata_sync, data)


def _build_outline_tree(
    reader: PdfReader,
) -> list[dict[str, Any]]:
    def _process(outlines: list, level: int = 0) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in outlines:
            if isinstance(item, list):
                result.extend(_process(item, level + 1))
            elif isinstance(item, Destination):
                title = str(item.title or "")
                try:
                    page_num = reader.get_destination_page_number(item) + 1
                except Exception:
                    page_num = 0
                result.append({"title": title, "page": page_num, "level": level})
        return result

    try:
        outlines = reader.outline
        return _process(outlines)
    except Exception:
        return []


async def _get_outline_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _sync() -> dict[str, Any]:
        reader = PdfReader(io.BytesIO(data))
        total = len(reader.pages)
        outline = _build_outline_tree(reader)
        return {"ok": True, "page_count": total, "outline": outline}

    return await asyncio.to_thread(_sync)


def _get_page_info_sync(data: bytes, pages: list[int] | None) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    target_pages = pages if pages is not None else list(range(1, total + 1))
    page_infos: list[dict[str, Any]] = []
    for page_num in target_pages:
        idx = page_num - 1
        if idx < 0 or idx >= total:
            continue
        page = reader.pages[idx]
        mediabox = page.mediabox
        width = float(mediabox.width) if mediabox.width else 0
        height = float(mediabox.height) if mediabox.height else 0
        rotation = int(getattr(page, "rotation", 0) or 0)
        num_chars = 0
        has_text = False
        try:
            text = page.extract_text() or ""
            num_chars = len(text)
            has_text = num_chars > 0
        except Exception:
            pass
        has_images = False
        try:
            has_images = len(page.images) > 0
        except Exception:
            pass
        page_infos.append(
            {
                "page": page_num,
                "width_pt": round(width, 1),
                "height_pt": round(height, 1),
                "rotation": rotation,
                "num_chars": num_chars,
                "has_text": has_text,
                "has_images": has_images,
            }
        )
    return {"ok": True, "page_count": total, "pages": page_infos}


async def _get_page_info_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    return await asyncio.to_thread(_get_page_info_sync, data, pages)


def _extract_links_sync(data: bytes, pages: list[int] | None) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    target_pages = pages if pages is not None else list(range(1, total + 1))
    links: list[dict[str, Any]] = []
    for page_num in target_pages:
        idx = page_num - 1
        if idx < 0 or idx >= total:
            continue
        page = reader.pages[idx]
        try:
            annotations = page.get("/Annots") or []
        except Exception:
            annotations = []
        for ann in annotations:
            try:
                ann_obj = ann.get_object()
                subtype = str(ann_obj.get("/Subtype", ""))
                if subtype != "/Link":
                    continue
                action = ann_obj.get("/A")
                dest = ann_obj.get("/Dest")
                rect = ann_obj.get("/Rect")
                bbox = None
                if rect:
                    bbox = [float(x) for x in rect]
                entry: dict[str, Any] = {
                    "page": page_num,
                    "type": "internal",
                    "bbox": bbox,
                }
                if action:
                    action_obj = action.get_object()
                    uri = action_obj.get("/URI")
                    if uri:
                        entry["type"] = "uri"
                        entry["uri"] = str(uri)
                    else:
                        entry["type"] = "action"
                        entry["action"] = str(action_obj.get("/S", ""))
                elif dest:
                    entry["type"] = "internal"
                    try:
                        dest_obj = dest.get_object() if hasattr(dest, "get_object") else dest
                        if hasattr(dest_obj, "__getitem__"):
                            target_page = dest_obj[0]
                            if hasattr(target_page, "get_object"):
                                target_page = target_page.get_object()
                            page_idx = reader.pages.index(target_page) if target_page in reader.pages else -1
                            entry["target_page"] = page_idx + 1 if page_idx >= 0 else 0
                    except Exception:
                        entry["target_page"] = 0
                links.append(entry)
            except Exception:
                continue
    return {"ok": True, "page_count": total, "links_found": len(links), "links": links}


async def _extract_links_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    total = _get_page_count(data)
    pages = parse_pages_spec(pages_spec, total) if pages_spec else None
    return await asyncio.to_thread(_extract_links_sync, data, pages)
