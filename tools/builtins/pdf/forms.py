from __future__ import annotations

import asyncio
import io
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    RectangleObject,
    TextStringObject,
)

from tools.builtins.pdf.io import parse_pages_spec, resolve_input
from tools.builtins.pdf.pages import save_output_sync


def _get_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _fill_form_sync(
    data: bytes, fields: dict[str, Any], flatten: bool
) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    writer = PdfWriter(clone_from=reader)

    filled: list[dict[str, Any]] = []
    not_found: list[str] = []

    writer_fields = writer.get_fields()
    if not writer_fields:
        return {
            "ok": False,
            "error": "PDF has no AcroForm fields",
            "page_count": total,
        }

    for name, value in fields.items():
        if name not in writer_fields:
            not_found.append(name)
            continue
        field = writer_fields[name]
        field_obj = field.get_object() if hasattr(field, "get_object") else field

        field_type = str(field_obj.get("/FT", ""))
        if field_type == "/Btn":
            if isinstance(value, bool):
                field_obj[NameObject("/V")] = BooleanObject(value)
            elif isinstance(value, str):
                field_obj[NameObject("/V")] = TextStringObject(value)
            else:
                field_obj[NameObject("/V")] = BooleanObject(bool(value))
        elif field_type == "/Ch":
            field_obj[NameObject("/V")] = TextStringObject(str(value))
            opts = field_obj.get("/Opt")
            if opts is not None:
                for opt in opts:
                    opt_obj = opt.get_object() if hasattr(opt, "get_object") else opt
                    if str(opt_obj) == str(value):
                        if isinstance(opt, DictionaryObject):
                            field_obj[NameObject("/I")] = NumberObject(0)
                        break
        else:
            field_obj[NameObject("/V")] = TextStringObject(str(value))

        try:
            field_obj[NameObject("/AP")] = field_obj.get("/AP", DictionaryObject())
        except Exception:
            pass

        filled.append({"name": name, "value": str(value)})

    if flatten:
        for page in writer.pages:
            try:
                writer.flatten_page(page)
            except Exception:
                pass

    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "filled_form.pdf")
    return {
        "ok": True,
        "page_count": total,
        "fields_filled": len(filled),
        "fields_not_found": not_found,
        "flattened": flatten,
        "filled": filled,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _fill_form_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    fields = arguments.get("fields") or {}
    if not isinstance(fields, dict) or not fields:
        return {"ok": False, "error": "fields (object) is required"}
    flatten = bool(arguments.get("flatten", False))
    return await asyncio.to_thread(_fill_form_sync, data, fields, flatten)


def _flatten_form_sync(data: bytes) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    writer = PdfWriter(clone_from=reader)

    if not writer.get_fields():
        return {
            "ok": False,
            "error": "PDF has no AcroForm fields",
            "page_count": total,
        }

    for page in writer.pages:
        try:
            writer.flatten_page(page)
        except Exception:
            pass

    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "flattened_form.pdf")
    return {
        "ok": True,
        "page_count": total,
        "flattened": True,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _flatten_form_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return await asyncio.to_thread(_flatten_form_sync, data)


def _create_form_sync(
    data: bytes, fields: list[dict[str, Any]]
) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    writer = PdfWriter(clone_from=reader)

    created: list[dict[str, Any]] = []

    if writer._root_object.get("/AcroForm") is None:
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject()
    acroform = writer._root_object[NameObject("/AcroForm")]
    if acroform.get("/Fields") is None:
        acroform[NameObject("/Fields")] = ArrayObject()

    for field_spec in fields:
        name = str(field_spec.get("name", "")).strip()
        if not name:
            continue
        field_type = str(field_spec.get("type", "text")).lower()
        page_num = int(field_spec.get("page", 1))
        idx = page_num - 1
        if idx < 0 or idx >= total:
            created.append({"name": name, "error": f"page {page_num} does not exist"})
            continue

        position = field_spec.get("position", {})
        x = float(position.get("x", 50))
        y = float(position.get("y", 50))
        w = float(position.get("width", 200))
        h = float(position.get("height", 20))
        default_value = str(field_spec.get("default_value", ""))
        options = field_spec.get("options") or []

        page = writer.pages[idx]
        page_w = float(page.mediabox.width)
        page_h = float(page.mediabox.height)

        rect = RectangleObject([
            FloatObject(x), FloatObject(y),
            FloatObject(x + w), FloatObject(y + h),
        ])

        form_field = DictionaryObject()
        form_field[NameObject("/Type")] = NameObject("/Annot")
        form_field[NameObject("/T")] = TextStringObject(name)
        form_field[NameObject("/Rect")] = rect

        if field_type == "checkbox":
            form_field[NameObject("/FT")] = NameObject("/Btn")
            form_field[NameObject("/V")] = BooleanObject(
                default_value.lower() in ("true", "1", "yes", "on")
            )
        elif field_type in ("radio", "dropdown", "choice"):
            form_field[NameObject("/FT")] = NameObject("/Ch")
            form_field[NameObject("/V")] = TextStringObject(default_value)
            if options:
                form_field[NameObject("/Opt")] = ArrayObject(
                    [TextStringObject(str(o)) for o in options]
                )
            if field_type == "dropdown":
                form_field[NameObject("/Ff")] = NumberObject(2)
        else:
            form_field[NameObject("/FT")] = NameObject("/Tx")
            form_field[NameObject("/V")] = TextStringObject(default_value)

        field_ref = writer._add_object(form_field)

        annotations = page.get("/Annots")
        if annotations is None:
            annotations = ArrayObject()
        annotations.append(field_ref)
        page[NameObject("/Annots")] = annotations

        acroform[NameObject("/Fields")].append(field_ref)

        created.append({
            "name": name,
            "type": field_type,
            "page": page_num,
            "default_value": default_value,
        })

    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "created_form.pdf")
    return {
        "ok": True,
        "page_count": total,
        "fields_created": len(created),
        "fields": created,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _create_form_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    fields = arguments.get("fields") or []
    if not isinstance(fields, list) or not fields:
        return {"ok": False, "error": "fields (array) is required"}
    return await asyncio.to_thread(_create_form_sync, data, fields)


def _reset_form_sync(data: bytes, field_names: list[str] | None) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    writer = PdfWriter(clone_from=reader)

    writer_fields = writer.get_fields()
    if not writer_fields:
        return {
            "ok": False,
            "error": "PDF has no AcroForm fields",
            "page_count": total,
        }

    reset: list[str] = []
    for name, field in writer_fields.items():
        if field_names and name not in field_names:
            continue
        field_obj = field.get_object() if hasattr(field, "get_object") else field
        field_type = str(field_obj.get("/FT", ""))
        if field_type == "/Btn":
            field_obj[NameObject("/V")] = BooleanObject(False)
        else:
            field_obj[NameObject("/V")] = TextStringObject("")
        try:
            field_obj.pop(NameObject("/AP"), None)
        except Exception:
            pass
        reset.append(name)

    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "reset_form.pdf")
    return {
        "ok": True,
        "page_count": total,
        "fields_reset": len(reset),
        "reset": reset,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _reset_form_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    fields = arguments.get("fields")
    field_names = None
    if isinstance(fields, list) and fields:
        field_names = [str(f) for f in fields]
    return await asyncio.to_thread(_reset_form_sync, data, field_names)
