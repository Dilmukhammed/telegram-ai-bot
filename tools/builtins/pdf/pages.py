from __future__ import annotations

import asyncio
import io
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

from tools.builtins.pdf.io import parse_pages_spec, resolve_input, save_output

_MAX_OUTPUT_PDFS = 10


def _get_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _parse_page_groups(pages_spec: str, total: int) -> list[list[int]]:
    groups: list[list[int]] = []
    for part in pages_spec.split(","):
        part = part.strip().lower()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start = int(left.strip()) if left.strip() else 1
            end = int(right.strip()) if right.strip() else total
            start = max(1, start)
            end = min(total, end)
            groups.append(list(range(start, end + 1)))
        else:
            p = int(part)
            if 1 <= p <= total:
                groups.append([p])
    return groups


def _split_sync(data: bytes, pages_spec: str | None, every_n: int | None) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)

    if every_n and every_n > 0:
        groups = []
        for start in range(0, total, every_n):
            end = min(start + every_n, total)
            groups.append(list(range(start + 1, end + 1)))
    elif pages_spec:
        groups = _parse_page_groups(pages_spec, total)
    else:
        return {"ok": False, "error": "Either 'pages' or 'every_n_pages' is required"}

    if not groups:
        return {"ok": False, "error": "No valid page groups parsed"}

    outputs: list[dict[str, Any]] = []
    for group in groups[:_MAX_OUTPUT_PDFS]:
        writer = PdfWriter()
        for page_num in group:
            idx = page_num - 1
            if 0 <= idx < total:
                writer.add_page(reader.pages[idx])
        buf = io.BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()
        saved = save_output_sync(pdf_bytes, f"split_{group[0]}-{group[-1]}.pdf")
        outputs.append(
            {
                "pages": group,
                "page_count": len(group),
                "file_ref": saved["file_ref"],
                "filename": saved["filename"],
            }
        )
    return {
        "ok": True,
        "page_count": total,
        "parts": len(outputs),
        "outputs": outputs,
    }


def save_output_sync(data: bytes, filename: str) -> dict[str, Any]:
    from tools.builtins.pdf.io import _save_output_sync
    return _save_output_sync(data, filename)


async def _split_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    every_n = arguments.get("every_n_pages")
    if isinstance(every_n, str) and every_n.strip():
        every_n = int(every_n)
    return await asyncio.to_thread(_split_sync, data, pages_spec, every_n)


def _extract_pages_sync(data: bytes, pages_spec: str) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    page_nums = parse_pages_spec(pages_spec, total)
    if not page_nums:
        return {"ok": False, "error": "No valid pages parsed"}

    writer = PdfWriter()
    for page_num in page_nums:
        idx = page_num - 1
        if 0 <= idx < total:
            writer.add_page(reader.pages[idx])
    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "extracted.pdf")
    return {
        "ok": True,
        "page_count": total,
        "extracted_pages": len(page_nums),
        "pages": page_nums,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _extract_pages_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    if not pages_spec:
        return {"ok": False, "error": "pages is required"}
    return await asyncio.to_thread(_extract_pages_sync, data, pages_spec)


def _merge_sync(file_refs_data: list[tuple[bytes, str]]) -> dict[str, Any]:
    writer = PdfWriter()
    page_counts: list[dict[str, Any]] = []
    for pdf_data, name in file_refs_data:
        reader = PdfReader(io.BytesIO(pdf_data))
        count = len(reader.pages)
        for page in reader.pages:
            writer.add_page(page)
        page_counts.append({"filename": name, "pages": count})
    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "merged.pdf")
    return {
        "ok": True,
        "inputs": len(file_refs_data),
        "total_pages": sum(p["pages"] for p in page_counts),
        "parts": page_counts,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _merge_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    from tools.builtins.pdf.io import _require_user_id
    from tools.run_files import require_run_file_store

    file_refs = arguments.get("file_refs") or []
    if not file_refs or not isinstance(file_refs, list):
        return {"ok": False, "error": "file_refs (list) is required"}
    if len(file_refs) > _MAX_OUTPUT_PDFS:
        return {"ok": False, "error": f"Max {_MAX_OUTPUT_PDFS} PDFs per merge"}

    store = require_run_file_store()
    parts: list[tuple[bytes, str]] = []
    for ref in file_refs:
        try:
            stored = store.resolve(str(ref))
            parts.append((stored.path.read_bytes(), stored.filename))
        except Exception as exc:
            return {"ok": False, "error": f"Cannot resolve file_ref {ref}: {exc}"}

    return await asyncio.to_thread(_merge_sync, parts)


def _rotate_pages_sync(data: bytes, rotations: dict[str, int]) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    writer = PdfWriter()
    rotated: list[dict[str, Any]] = []
    for page_idx in range(total):
        page = reader.pages[page_idx]
        page_num = page_idx + 1
        angle = None
        for key, val in rotations.items():
            key_pages = parse_pages_spec(key, total)
            if key_pages and page_num in key_pages:
                angle = val
                break
        if angle is not None:
            page.rotate(angle)
            rotated.append({"page": page_num, "angle": angle})
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "rotated.pdf")
    return {
        "ok": True,
        "page_count": total,
        "rotated_pages": len(rotated),
        "rotations": rotated,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _rotate_pages_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    rotations_raw = arguments.get("pages") or {}
    if not isinstance(rotations_raw, dict) or not rotations_raw:
        return {"ok": False, "error": "pages must be an object like {\"1-3\": 90, \"5\": 180}"}
    rotations = {str(k): int(v) for k, v in rotations_raw.items()}
    return await asyncio.to_thread(_rotate_pages_sync, data, rotations)


def _delete_pages_sync(data: bytes, pages_spec: str) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    pages_to_delete = parse_pages_spec(pages_spec, total) or []
    delete_set = set(pages_to_delete)
    writer = PdfWriter()
    kept = 0
    for page_idx in range(total):
        page_num = page_idx + 1
        if page_num in delete_set:
            continue
        writer.add_page(reader.pages[page_idx])
        kept += 1
    if kept == 0:
        return {"ok": False, "error": "Cannot delete all pages"}
    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "deleted.pdf")
    return {
        "ok": True,
        "page_count": total,
        "deleted_pages": len(pages_to_delete),
        "remaining_pages": kept,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _delete_pages_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    pages_spec = arguments.get("pages")
    if not pages_spec:
        return {"ok": False, "error": "pages is required"}
    return await asyncio.to_thread(_delete_pages_sync, data, pages_spec)


def _reorder_pages_sync(
    data: bytes, order: list[int] | None, swap: list[int] | None
) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    writer = PdfWriter()

    if order is not None:
        if len(order) != total:
            return {
                "ok": False,
                "error": f"order must contain all {total} pages exactly once, got {len(order)}",
            }
        if set(order) != set(range(1, total + 1)):
            return {"ok": False, "error": "order must contain each page exactly once"}
        for page_num in order:
            writer.add_page(reader.pages[page_num - 1])
        return _finalize_reorder(writer, total, "order", order)
    elif swap is not None:
        if len(swap) != 2:
            return {"ok": False, "error": "swap must contain exactly 2 page numbers"}
        a, b = swap[0], swap[1]
        if not (1 <= a <= total) or not (1 <= b <= total):
            return {"ok": False, "error": f"swap pages must be 1-{total}"}
        page_map = list(range(1, total + 1))
        page_map[a - 1], page_map[b - 1] = page_map[b - 1], page_map[a - 1]
        for page_num in page_map:
            writer.add_page(reader.pages[page_num - 1])
        return _finalize_reorder(writer, total, "swap", [a, b])
    else:
        return {"ok": False, "error": "Either 'order' or 'swap' is required"}


def _finalize_reorder(
    writer: PdfWriter, total: int, mode: str, detail: list[int]
) -> dict[str, Any]:
    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "reordered.pdf")
    return {
        "ok": True,
        "page_count": total,
        "mode": mode,
        "detail": detail,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _reorder_pages_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    order = arguments.get("order")
    if isinstance(order, str) and order.strip():
        order = [int(x.strip()) for x in order.split(",") if x.strip()]
    swap = arguments.get("swap")
    if isinstance(swap, str) and swap.strip():
        swap = [int(x.strip()) for x in swap.split(",") if x.strip()]
    return await asyncio.to_thread(_reorder_pages_sync, data, order, swap)
