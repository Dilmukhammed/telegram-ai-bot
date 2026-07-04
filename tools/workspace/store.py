from __future__ import annotations

import base64
import fnmatch
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from config import format_byte_size, get_settings
from tools.context import get_run_context
from tools.run_files import require_run_file_store
from tools.text_file_encoding import is_probably_text_file
from tools.workspace.errors import (
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    WorkspacePathError,
    WorkspaceQuotaError,
)
from tools.workspace.mime import file_kind, guess_mime_type, is_image_file
from tools.workspace.paths import (
    ensure_workspace_layout,
    resolve_workspace_path,
    sanitize_relative_path,
    unique_relative_path,
    workspace_root_for_user,
    workspace_zone,
)
from tools.workspace.vision import build_image_data_url
from tools.workspace.vision_pending import push_pending_vision

_TEXT_DECODE_ORDER = ("utf-8", "latin-1", "cp1252")


def _require_user_id() -> int:
    user_id = get_run_context().user_id
    if user_id is None:
        raise RuntimeError("Telegram user_id is missing in tool context")
    return user_id


def _iso_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _created_timestamp(st) -> float:
    if hasattr(st, "st_birthtime"):
        return float(st.st_birthtime)
    return float(st.st_ctime)


def _relative_path(user_id: int, path: Path) -> str:
    root = workspace_root_for_user(user_id).resolve()
    rel = path.resolve().relative_to(root)
    return rel.as_posix()


def _decode_text_bytes(data: bytes) -> str:
    for encoding in _TEXT_DECODE_ORDER:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _count_lines(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for _ in handle:
            count += 1
    return count


def _maybe_file_ref(user_id: int, path: Path, mime_type: str | None) -> str | None:
    if not path.is_file():
        return None
    try:
        store = require_run_file_store()
    except RuntimeError:
        return None
    data = path.read_bytes()
    stored = store.save(data, filename=path.name, mime_type=mime_type)
    return str(stored["file_ref"])


def _usage_stats(user_id: int) -> dict[str, object]:
    root = workspace_root_for_user(user_id)
    settings = get_settings()
    bytes_used = 0
    file_count = 0
    zone_paths: dict[str, str] = {}
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                file_count += 1
                bytes_used += path.stat().st_size
        for zone in ("uploads", "agent", "exports"):
            zone_paths[zone] = (root / zone).as_posix()
    return {
        "bytes_used": bytes_used,
        "bytes_limit": settings.workspace_max_bytes_per_user,
        "bytes_used_human": format_byte_size(bytes_used),
        "bytes_limit_human": format_byte_size(settings.workspace_max_bytes_per_user),
        "file_count": file_count,
        "file_limit": settings.workspace_max_files_per_user,
        "paths": zone_paths,
    }


def _check_write_quota(user_id: int, *, extra_bytes: int, extra_files: int = 0) -> None:
    settings = get_settings()
    stats = _usage_stats(user_id)
    if int(stats["file_count"]) + extra_files > settings.workspace_max_files_per_user:
        raise WorkspaceQuotaError(
            f"file count limit exceeded ({stats['file_count']}/{settings.workspace_max_files_per_user})"
        )
    if int(stats["bytes_used"]) + extra_bytes > settings.workspace_max_bytes_per_user:
        raise WorkspaceQuotaError(
            f"storage quota exceeded ({stats['bytes_used_human']}/{stats['bytes_limit_human']})"
        )


def stat_path(user_id: int, relative: str) -> dict[str, object]:
    settings = get_settings()
    clean = sanitize_relative_path(relative)
    try:
        target = resolve_workspace_path(user_id, clean)
    except WorkspacePathError as exc:
        return {"ok": False, "path": clean, "exists": False, "error": str(exc)}

    if not target.exists():
        return {"ok": False, "path": clean, "exists": False, "error": "not_found"}

    st = target.stat()
    rel = _relative_path(user_id, target)
    zone = workspace_zone(rel)
    created_at = _iso_timestamp(_created_timestamp(st))
    modified_at = _iso_timestamp(st.st_mtime)
    accessed_at = _iso_timestamp(st.st_atime)

    if target.is_dir():
        entries = [
            child
            for child in target.iterdir()
            if not child.is_symlink()
        ]
        return {
            "ok": True,
            "path": rel,
            "exists": True,
            "type": "directory",
            "zone": zone,
            "entry_count": len(entries),
            "size_bytes": None,
            "created_at": created_at,
            "modified_at": modified_at,
            "accessed_at": accessed_at,
            "readable": True,
            "writable": True,
        }

    mime_type = guess_mime_type(target)
    kind = file_kind(target, mime_type)
    payload: dict[str, object] = {
        "ok": True,
        "path": rel,
        "exists": True,
        "type": "file",
        "zone": zone,
        "size_bytes": st.st_size,
        "size_human": format_byte_size(st.st_size),
        "mime_type": mime_type,
        "extension": target.suffix.lower() or None,
        "created_at": created_at,
        "modified_at": modified_at,
        "accessed_at": accessed_at,
        "readable": True,
        "writable": True,
        "kind": kind,
    }
    if kind == "text":
        payload["total_lines"] = _count_lines(target)
        payload["preview_available"] = True
    elif kind in {"binary", "image"}:
        file_ref = _maybe_file_ref(user_id, target, mime_type)
        if file_ref:
            payload["file_ref"] = file_ref
    if kind == "image" and st.st_size > settings.image_max_bytes:
        payload["vision_available"] = False
        payload["vision_error"] = f"image exceeds vision limit ({settings.image_max_bytes} bytes)"
    elif kind == "image":
        payload["vision_available"] = True
    return payload


def list_dir(
    user_id: int,
    *,
    relative: str = ".",
    recursive: bool = False,
    max_entries: int = 100,
) -> dict[str, object]:
    clean = sanitize_relative_path(relative)
    target = resolve_workspace_path(user_id, clean)
    if not target.exists():
        raise WorkspaceNotFoundError(f"not found: {clean}")
    if not target.is_dir():
        raise WorkspacePathError(f"not a directory: {clean}")

    entries: list[dict[str, object]] = []
    truncated = False
    if recursive:
        iterator = sorted(
            (path for path in target.rglob("*") if not path.is_symlink()),
            key=lambda path: path.as_posix(),
        )
    else:
        iterator = sorted(
            (path for path in target.iterdir() if not path.is_symlink()),
            key=lambda path: (not path.is_dir(), path.name.lower()),
        )

    for path in iterator:
        if len(entries) >= max_entries:
            truncated = True
            break
        rel = _relative_path(user_id, path)
        st = path.stat()
        entry_type = "directory" if path.is_dir() else "file"
        entry: dict[str, object] = {
            "name": path.name,
            "type": entry_type,
            "path": rel,
            "modified_at": _iso_timestamp(st.st_mtime),
            "created_at": _iso_timestamp(_created_timestamp(st)),
        }
        if path.is_file():
            mime_type = guess_mime_type(path)
            entry["size_bytes"] = st.st_size
            entry["mime_type"] = mime_type
            entry["kind"] = file_kind(path, mime_type)
        entries.append(entry)

    rel = _relative_path(user_id, target)
    return {
        "ok": True,
        "path": rel,
        "type": "directory",
        "entry_count": len(entries),
        "entries": entries,
        "truncated": truncated,
    }


def read_file_preview(
    user_id: int,
    *,
    relative: str,
    preview_lines: int | None = None,
) -> dict[str, object]:
    settings = get_settings()
    clean = sanitize_relative_path(relative)
    target = resolve_workspace_path(user_id, clean)
    if not target.exists():
        return {"ok": False, "path": clean, "exists": False, "error": "not_found"}
    if not target.is_file():
        raise WorkspacePathError(f"not a file: {clean}")

    mime_type = guess_mime_type(target)
    kind = file_kind(target, mime_type)
    st = target.stat()
    rel = _relative_path(user_id, target)

    if kind == "image":
        if st.st_size > settings.image_max_bytes:
            return {
                "ok": False,
                "path": rel,
                "kind": "image",
                "error": f"image too large for vision ({st.st_size} bytes)",
            }
        data_url = build_image_data_url(target)
        push_pending_vision(rel, data_url)
        return {
            "ok": True,
            "path": rel,
            "kind": "image",
            "mime_type": mime_type,
            "size_bytes": st.st_size,
            "size_human": format_byte_size(st.st_size),
            "vision_injected": True,
            "hint": "Image loaded into context for vision (same as Telegram photo).",
        }

    if kind == "binary":
        file_ref = _maybe_file_ref(user_id, target, mime_type)
        return {
            "ok": True,
            "path": rel,
            "kind": "binary",
            "mime_type": mime_type,
            "size_bytes": st.st_size,
            "size_human": format_byte_size(st.st_size),
            "file_ref": file_ref,
            "hint": "Binary file — use telegram.send_file with file_ref or stat for metadata.",
        }

    max_preview = min(
        preview_lines or settings.workspace_read_preview_lines,
        settings.workspace_read_preview_lines_max,
    )
    text = _decode_text_bytes(target.read_bytes())
    lines = text.splitlines()
    total_lines = len(lines) if text else 0
    if text and not lines:
        total_lines = 1
        lines = [""]
    preview = lines[:max_preview]
    numbered = [{"n": index + 1, "text": line} for index, line in enumerate(preview)]
    hint = "Use workspace.read_lines for a specific range (e.g. start_line=20, end_line=145)."
    if total_lines > len(preview):
        hint = (
            f"Showing first {len(preview)} of {total_lines} lines. "
            + hint
        )
    return {
        "ok": True,
        "path": rel,
        "kind": "text",
        "mime_type": mime_type,
        "size_bytes": st.st_size,
        "size_human": format_byte_size(st.st_size),
        "total_lines": total_lines,
        "preview_lines": len(preview),
        "lines": numbered,
        "hint": hint,
    }


def read_lines(
    user_id: int,
    *,
    relative: str,
    start_line: int,
    end_line: int | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    settings = get_settings()
    clean = sanitize_relative_path(relative)
    target = resolve_workspace_path(user_id, clean)
    if not target.exists() or not target.is_file():
        raise WorkspaceNotFoundError(f"not found: {clean}")

    mime_type = guess_mime_type(target)
    if file_kind(target, mime_type) != "text":
        raise WorkspacePathError("read_lines only supports text files")

    if start_line < 1:
        raise ValueError("start_line must be >= 1")

    if end_line is not None:
        if end_line < start_line:
            raise ValueError("end_line must be >= start_line")
        span = end_line - start_line + 1
    else:
        span = limit or 200
        end_line = start_line + span - 1

    if span > settings.workspace_read_lines_max:
        raise ValueError(
            f"line span exceeds max ({span} > {settings.workspace_read_lines_max})"
        )

    text = _decode_text_bytes(target.read_bytes())
    all_lines = text.splitlines()
    total_lines = len(all_lines) if text else 0
    if text and not all_lines:
        total_lines = 1
        all_lines = [""]

    slice_start = start_line - 1
    slice_end = min(end_line, total_lines if total_lines else end_line)
    selected = all_lines[slice_start:slice_end]
    numbered = [
        {"n": start_line + offset, "text": line}
        for offset, line in enumerate(selected)
    ]
    rel = _relative_path(user_id, target)
    return {
        "ok": True,
        "path": rel,
        "start_line": start_line,
        "end_line": slice_end if selected else start_line - 1,
        "lines": numbered,
        "total_lines": total_lines,
    }


def usage(user_id: int) -> dict[str, object]:
    stats = _usage_stats(user_id)
    return {"ok": True, **stats}


def save_bytes(
    user_id: int,
    *,
    relative: str,
    data: bytes,
    mime_type: str | None = None,
    max_bytes: int | None = None,
) -> dict[str, object]:
    """Save bytes to workspace (inbound uploads — no agent run context)."""
    settings = get_settings()
    limit = max_bytes if max_bytes is not None else settings.workspace_upload_max_bytes
    if len(data) > limit:
        raise WorkspaceQuotaError(f"file too large ({len(data)} bytes; max {limit})")

    clean = unique_relative_path(user_id, relative)
    target = resolve_workspace_path(user_id, clean)
    created = not target.exists()
    old_size = target.stat().st_size if target.exists() and target.is_file() else 0
    _check_write_quota(user_id, extra_bytes=len(data) - old_size, extra_files=1 if created else 0)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    resolved_mime = mime_type or guess_mime_type(target)
    rel = _relative_path(user_id, target)
    return {
        "ok": True,
        "path": rel,
        "size_bytes": len(data),
        "size_human": format_byte_size(len(data)),
        "mime_type": resolved_mime,
        "created": created,
    }


def write_file(
    user_id: int,
    *,
    relative: str,
    content_text: str | None = None,
    content_base64: str | None = None,
    mime_type: str | None = None,
    overwrite: bool = True,
) -> dict[str, object]:
    settings = get_settings()
    has_text = content_text is not None
    has_b64 = content_base64 is not None
    if has_text == has_b64:
        raise ValueError("provide exactly one of content_text or content_base64")

    clean = sanitize_relative_path(relative)
    target = resolve_workspace_path(user_id, clean)
    created = not target.exists()

    if target.exists() and not overwrite:
        raise WorkspaceConflictError(f"file already exists: {clean}")
    if target.exists() and target.is_dir():
        raise WorkspacePathError(f"not a file path: {clean}")

    if has_text:
        data = str(content_text).encode("utf-8")
    else:
        data = base64.b64decode(str(content_base64), validate=True)

    if len(data) > settings.workspace_max_file_bytes:
        raise WorkspaceQuotaError(
            f"file too large ({len(data)} bytes; max {settings.workspace_max_file_bytes})"
        )

    extra_files = 1 if created else 0
    old_size = target.stat().st_size if target.exists() and target.is_file() else 0
    _check_write_quota(user_id, extra_bytes=len(data) - old_size, extra_files=extra_files)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    resolved_mime = mime_type or guess_mime_type(target)
    rel = _relative_path(user_id, target)
    file_ref = _maybe_file_ref(user_id, target, resolved_mime)
    return {
        "ok": True,
        "path": rel,
        "size_bytes": len(data),
        "size_human": format_byte_size(len(data)),
        "mime_type": resolved_mime,
        "file_ref": file_ref,
        "created": created,
    }


def append_file(user_id: int, *, relative: str, content_text: str) -> dict[str, object]:
    clean = sanitize_relative_path(relative)
    target = resolve_workspace_path(user_id, clean)
    data = str(content_text).encode("utf-8")
    settings = get_settings()

    if target.exists() and target.is_dir():
        raise WorkspacePathError(f"not a file path: {clean}")

    old_size = target.stat().st_size if target.exists() else 0
    _check_write_quota(user_id, extra_bytes=len(data), extra_files=0 if target.exists() else 1)

    if len(data) + old_size > settings.workspace_max_file_bytes:
        raise WorkspaceQuotaError("append would exceed max file size")

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("ab") as handle:
        handle.write(data)

    new_size = target.stat().st_size
    rel = _relative_path(user_id, target)
    return {"ok": True, "path": rel, "size_bytes": new_size, "size_human": format_byte_size(new_size)}


def mkdir(user_id: int, *, relative: str, parents: bool = True) -> dict[str, object]:
    clean = sanitize_relative_path(relative)
    target = resolve_workspace_path(user_id, clean)
    created = not target.exists()
    if created:
        _check_write_quota(user_id, extra_bytes=0, extra_files=0)
    target.mkdir(parents=parents, exist_ok=True)
    rel = _relative_path(user_id, target)
    return {"ok": True, "path": rel, "created": created}


def move_path(
    user_id: int,
    *,
    from_relative: str,
    to_relative: str,
    overwrite: bool = False,
) -> dict[str, object]:
    src_clean = sanitize_relative_path(from_relative)
    dst_clean = sanitize_relative_path(to_relative)
    src = resolve_workspace_path(user_id, src_clean)
    dst = resolve_workspace_path(user_id, dst_clean)

    if not src.exists():
        raise WorkspaceNotFoundError(f"not found: {src_clean}")

    final_dst = dst
    if dst.exists() and dst.is_dir() and src.is_file():
        final_dst = dst / src.name
    if final_dst.exists() and not overwrite:
        raise WorkspaceConflictError(f"destination exists: {dst_clean}")

    from_rel = _relative_path(user_id, src)
    final_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(final_dst))
    return {
        "ok": True,
        "from_path": from_rel,
        "to_path": _relative_path(user_id, final_dst),
    }


def find_files(
    user_id: int,
    *,
    pattern: str,
    max_results: int = 50,
) -> dict[str, object]:
    root = ensure_workspace_layout(user_id)
    clean = str(pattern or "").strip().replace("\\", "/")
    if not clean:
        raise ValueError("pattern is required")
    if ".." in clean.split("/"):
        raise WorkspacePathError("pattern must not contain ..")

    matches: list[dict[str, object]] = []
    truncated = False
    for path in sorted(root.glob(clean), key=lambda item: item.as_posix()):
        if path.is_symlink():
            continue
        if len(matches) >= max_results:
            truncated = True
            break
        st = path.stat()
        rel = _relative_path(user_id, path)
        entry: dict[str, object] = {
            "path": rel,
            "type": "directory" if path.is_dir() else "file",
            "modified_at": _iso_timestamp(st.st_mtime),
        }
        if path.is_file():
            entry["size_bytes"] = st.st_size
        matches.append(entry)

    return {
        "ok": True,
        "pattern": clean,
        "matches": matches,
        "truncated": truncated,
    }


def grep_files(
    user_id: int,
    *,
    pattern: str,
    relative: str = ".",
    glob_pattern: str | None = None,
    ignore_case: bool = False,
    max_matches: int | None = None,
    context_lines: int = 0,
) -> dict[str, object]:
    settings = get_settings()
    regex_flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(str(pattern), regex_flags)
    except re.error as exc:
        raise ValueError(f"invalid regex pattern: {exc}") from exc

    cap_matches = max_matches or settings.workspace_grep_max_matches
    cap_files = settings.workspace_grep_max_files
    context_lines = max(0, min(int(context_lines), 3))

    base = resolve_workspace_path(user_id, relative)
    if not base.exists():
        raise WorkspaceNotFoundError(f"not found: {relative}")

    if base.is_file():
        candidates = [base]
    else:
        candidates = [
            path
            for path in base.rglob("*")
            if path.is_file() and not path.is_symlink()
            and (glob_pattern is None or fnmatch.fnmatch(path.name, glob_pattern))
        ]

    matches: list[dict[str, object]] = []
    files_scanned = 0
    truncated = False
    base_rel = _relative_path(user_id, base) if base.is_dir() else None

    for path in sorted(candidates, key=lambda item: item.as_posix()):
        if files_scanned >= cap_files:
            truncated = True
            break
        mime_type = guess_mime_type(path)
        if file_kind(path, mime_type) != "text":
            continue
        files_scanned += 1
        lines = _decode_text_bytes(path.read_bytes()).splitlines()
        for line_number, line in enumerate(lines, start=1):
            if not regex.search(line):
                continue
            rel = _relative_path(user_id, path)
            hit: dict[str, object] = {
                "path": rel,
                "line": line_number,
                "text": line,
            }
            if context_lines:
                start = max(0, line_number - 1 - context_lines)
                end = min(len(lines), line_number + context_lines)
                hit["context_before"] = lines[start : line_number - 1]
                hit["context_after"] = lines[line_number:end]
            matches.append(hit)
            if len(matches) >= cap_matches:
                truncated = True
                break
        if truncated:
            break

    return {
        "ok": True,
        "pattern": pattern,
        "path": base_rel or _relative_path(user_id, base),
        "matches": matches,
        "files_scanned": files_scanned,
        "truncated": truncated,
    }


def copy_path(
    user_id: int,
    *,
    from_relative: str,
    to_relative: str,
    overwrite: bool = False,
) -> dict[str, object]:
    src = resolve_workspace_path(user_id, sanitize_relative_path(from_relative))
    dst = resolve_workspace_path(user_id, sanitize_relative_path(to_relative))
    if not src.exists():
        raise WorkspaceNotFoundError(f"not found: {from_relative}")

    final_dst = dst
    if dst.exists() and dst.is_dir():
        final_dst = dst / src.name
    if final_dst.exists() and not overwrite:
        raise WorkspaceConflictError(f"destination exists: {to_relative}")

    final_dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if final_dst.exists():
            if not overwrite:
                raise WorkspaceConflictError(f"destination exists: {to_relative}")
            shutil.rmtree(final_dst)
        shutil.copytree(src, final_dst)
    else:
        extra = src.stat().st_size if not final_dst.exists() else 0
        _check_write_quota(user_id, extra_bytes=extra, extra_files=0 if final_dst.exists() else 1)
        shutil.copy2(src, final_dst)

    return {
        "ok": True,
        "from_path": _relative_path(user_id, src),
        "to_path": _relative_path(user_id, final_dst),
    }


def delete_path(
    user_id: int,
    *,
    relative: str,
    recursive: bool = False,
    confirm: bool = False,
) -> dict[str, object]:
    if not confirm:
        raise ValueError("confirm=true is required")

    target = resolve_workspace_path(user_id, sanitize_relative_path(relative))
    if not target.exists():
        raise WorkspaceNotFoundError(f"not found: {relative}")

    rel = _relative_path(user_id, target)
    if target.is_dir():
        if not recursive and any(target.iterdir()):
            raise WorkspaceConflictError(
                f"directory not empty: {rel} (use recursive=true or clear zone)"
            )
        shutil.rmtree(target)
    else:
        target.unlink()

    return {"ok": True, "path": rel, "deleted": True}


def clear_zone(user_id: int, *, zone: str, confirm: bool = False) -> dict[str, object]:
    if not confirm:
        raise ValueError("confirm=true is required")

    value = str(zone or "").strip().lower()
    if value not in {"agent", "exports", "uploads", "all"}:
        raise ValueError("zone must be agent, exports, uploads, or all")

    root = ensure_workspace_layout(user_id)
    zones = ["uploads", "agent", "exports"] if value == "all" else [value]
    bytes_freed = 0
    files_removed = 0

    for zone_name in zones:
        zone_path = root / zone_name
        if not zone_path.exists():
            continue
        for path in zone_path.rglob("*"):
            if path.is_file() and not path.is_symlink():
                bytes_freed += path.stat().st_size
                files_removed += 1
        shutil.rmtree(zone_path, ignore_errors=True)
        zone_path.mkdir(parents=True, exist_ok=True)

    return {
        "ok": True,
        "zone": value,
        "bytes_freed": bytes_freed,
        "files_removed": files_removed,
    }


def import_from_file_ref(
    user_id: int,
    *,
    file_ref: str,
    relative: str,
    overwrite: bool = True,
) -> dict[str, object]:
    ctx_user = _require_user_id()
    if ctx_user != user_id:
        raise RuntimeError("user_id mismatch")

    store = require_run_file_store()
    stored = store.resolve(str(file_ref).strip())
    if stored.user_id != user_id:
        raise WorkspacePathError("file_ref is not available for this user")

    data = stored.path.read_bytes()
    return write_file(
        user_id,
        relative=relative,
        content_base64=base64.b64encode(data).decode("ascii"),
        mime_type=stored.mime_type,
        overwrite=overwrite,
    )


def unzip_file(
    user_id: int,
    *,
    relative: str,
    dest_relative: str | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    settings = get_settings()
    zip_path = resolve_workspace_path(user_id, sanitize_relative_path(relative))
    if not zip_path.exists() or not zip_path.is_file():
        raise WorkspaceNotFoundError(f"not found: {relative}")

    if dest_relative:
        dest_path = resolve_workspace_path(user_id, sanitize_relative_path(dest_relative))
    else:
        dest_path = zip_path.parent / zip_path.stem

    dest_resolved = dest_path.resolve()
    if dest_path.exists():
        if not overwrite:
            raise WorkspaceConflictError(f"destination exists: {dest_path.name}")
        if dest_path.is_dir():
            shutil.rmtree(dest_path)
        else:
            dest_path.unlink()

    dest_path.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    total_uncompressed = 0
    file_count = 0

    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.flag_bits & 0x1:
                raise WorkspacePathError("encrypted zip files are not supported")

            member = (dest_path / info.filename).resolve()
            if not member.is_relative_to(dest_resolved):
                raise WorkspacePathError("zip slip detected")

            total_uncompressed += info.file_size
            if info.filename.endswith("/"):
                continue
            file_count += 1
            if file_count > settings.workspace_unzip_max_files:
                raise WorkspaceQuotaError("unzip exceeds max file count")
            if total_uncompressed > settings.workspace_unzip_max_bytes:
                raise WorkspaceQuotaError("unzip exceeds max uncompressed bytes")

        _check_write_quota(user_id, extra_bytes=total_uncompressed, extra_files=file_count)

        for info in archive.infolist():
            member = (dest_path / info.filename).resolve()
            if not member.is_relative_to(dest_resolved):
                raise WorkspacePathError("zip slip detected")
            if info.filename.endswith("/"):
                member.mkdir(parents=True, exist_ok=True)
                continue
            member.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, member.open("wb") as target:
                shutil.copyfileobj(source, target)
            entries.append(
                {
                    "path": _relative_path(user_id, member),
                    "size_bytes": info.file_size,
                }
            )

    return {
        "ok": True,
        "path": _relative_path(user_id, zip_path),
        "dest": _relative_path(user_id, dest_path),
        "files_extracted": len(entries),
        "bytes_extracted": total_uncompressed,
        "entries": entries,
    }


def read_workspace_bytes(user_id: int, relative: str) -> tuple[Path, bytes, str | None]:
    """Load file bytes from workspace (for telegram.send_file path=)."""
    target = resolve_workspace_path(user_id, sanitize_relative_path(relative))
    if not target.exists() or not target.is_file():
        raise WorkspaceNotFoundError(f"not found: {relative}")
    return target, target.read_bytes(), guess_mime_type(target)
