from __future__ import annotations

import asyncio
import io
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions

from tools.builtins.pdf.io import resolve_input
from tools.builtins.pdf.pages import save_output_sync


def _get_page_count(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def _encrypt_sync(
    data: bytes,
    user_password: str,
    owner_password: str | None,
    allow_print: bool,
    allow_copy: bool,
    allow_modify: bool,
    allow_annotate: bool,
) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    writer = PdfWriter(clone_from=reader)

    permissions = UserAccessPermissions(0)
    if allow_print:
        permissions |= UserAccessPermissions.PRINT
    if allow_modify:
        permissions |= UserAccessPermissions.MODIFY
    if allow_copy:
        permissions |= UserAccessPermissions.EXTRACT
    if allow_annotate:
        permissions |= UserAccessPermissions.ADD_OR_MODIFY

    owner_pwd = owner_password if owner_password else user_password

    writer.encrypt(
        user_password=user_password,
        owner_password=owner_pwd,
        permissions_flag=permissions,
    )

    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "encrypted.pdf")
    return {
        "ok": True,
        "page_count": total,
        "encrypted": True,
        "permissions": {
            "print": allow_print,
            "copy": allow_copy,
            "modify": allow_modify,
            "annotate": allow_annotate,
        },
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _encrypt_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    password = str(arguments.get("password", "")).strip()
    if not password:
        return {"ok": False, "error": "password is required"}
    owner_password = arguments.get("owner_password")
    owner_password = str(owner_password).strip() if owner_password else None
    allow_print = bool(arguments.get("allow_print", True))
    allow_copy = bool(arguments.get("allow_copy", True))
    allow_modify = bool(arguments.get("allow_modify", True))
    allow_annotate = bool(arguments.get("allow_annotate", True))
    return await asyncio.to_thread(
        _encrypt_sync, data, password, owner_password,
        allow_print, allow_copy, allow_modify, allow_annotate,
    )


def _decrypt_sync(data: bytes, password: str) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    if not reader.is_encrypted:
        return {"ok": False, "error": "PDF is not encrypted"}

    try:
        result = reader.decrypt(password)
    except Exception:
        return {"ok": False, "error": "Invalid password"}

    if result == 0:
        return {"ok": False, "error": "Invalid password"}

    try:
        total = len(reader.pages)
    except Exception:
        return {"ok": False, "error": "Invalid password"}

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    buf = io.BytesIO()
    writer.write(buf)
    saved = save_output_sync(buf.getvalue(), "decrypted.pdf")
    return {
        "ok": True,
        "page_count": total,
        "decrypted": True,
        "file_ref": saved["file_ref"],
        "filename": saved["filename"],
    }


async def _decrypt_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    password = str(arguments.get("password", "")).strip()
    if not password:
        return {"ok": False, "error": "password is required"}
    return await asyncio.to_thread(_decrypt_sync, data, password)


def _get_permissions_sync(data: bytes, password: str | None) -> dict[str, Any]:
    reader = PdfReader(io.BytesIO(data))
    encrypted = reader.is_encrypted

    try:
        total = len(reader.pages)
    except Exception:
        total = 0

    if encrypted:
        if password:
            try:
                result = reader.decrypt(password)
            except Exception:
                result = 0
            if result == 0:
                return {
                    "ok": True,
                    "encrypted": True,
                    "needs_password": True,
                    "page_count": total,
                    "permissions": {},
                    "error": "Invalid password",
                }
            try:
                total = len(reader.pages)
            except Exception:
                pass
        else:
            return {
                "ok": True,
                "encrypted": True,
                "needs_password": True,
                "page_count": total,
                "permissions": {},
            }

    permissions = {
        "print": True,
        "copy": True,
        "modify": True,
        "annotate": True,
    }

    if encrypted and password:
        try:
            encrypt_obj = reader.trailer.get("/Encrypt")
            if encrypt_obj:
                encrypt_dict = encrypt_obj.get_object()
                p_val = encrypt_dict.get("/P")
                if p_val is not None:
                    p_int = int(p_val)
                    permissions["print"] = bool(p_int & 4)
                    permissions["copy"] = bool(p_int & 16)
                    permissions["modify"] = bool(p_int & 8)
                    permissions["annotate"] = bool(p_int & 32)
        except Exception:
            pass

    return {
        "ok": True,
        "encrypted": encrypted,
        "needs_password": encrypted and not password,
        "page_count": total,
        "permissions": permissions,
    }


async def _get_permissions_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    file_ref = arguments.get("file_ref")
    path = arguments.get("path")
    try:
        data, _name = await resolve_input(file_ref, path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    password = arguments.get("password")
    password = str(password).strip() if password else None
    return await asyncio.to_thread(_get_permissions_sync, data, password)
