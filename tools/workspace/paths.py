from __future__ import annotations

import re
from pathlib import Path

from config import get_settings
from tools.workspace.errors import WorkspacePathError

_ZONES = frozenset({"uploads", "agent", "exports"})
_UNSAFE_PATH = re.compile(r"[\x00-\x1f]")
_FILENAME_UNSAFE = re.compile(r'[<>:"|?*\x00-\x1f\\]')


def workspace_root_for_user(user_id: int) -> Path:
    settings = get_settings()
    return Path(settings.workspace_root) / str(user_id)


def ensure_workspace_layout(user_id: int) -> Path:
    root = workspace_root_for_user(user_id)
    root.mkdir(parents=True, exist_ok=True)
    for zone in _ZONES:
        (root / zone).mkdir(parents=True, exist_ok=True)
    return root


def sanitize_relative_path(relative: str) -> str:
    raw = str(relative or ".").strip().replace("\\", "/")
    if not raw:
        raw = "."
    if raw.startswith("/"):
        raise WorkspacePathError("absolute paths are not allowed")
    if "\x00" in raw or _UNSAFE_PATH.search(raw):
        raise WorkspacePathError("invalid characters in path")
    parts: list[str] = []
    for part in raw.split("/"):
        part = part.strip()
        if not part or part == ".":
            continue
        if part == "..":
            raise WorkspacePathError("path traversal is not allowed")
        parts.append(part)
    return "/".join(parts) if parts else "."


def resolve_workspace_path(user_id: int, relative: str) -> Path:
    root = ensure_workspace_layout(user_id)
    clean = sanitize_relative_path(relative)
    target = (root / clean).resolve()
    root_resolved = root.resolve()
    if not target.is_relative_to(root_resolved):
        raise WorkspacePathError("path escapes workspace")
    if target.is_symlink():
        raise WorkspacePathError("symlinks are not allowed")
    return target


def workspace_zone(relative: str) -> str | None:
    clean = sanitize_relative_path(relative)
    if clean == ".":
        return None
    first = clean.split("/", 1)[0]
    return first if first in _ZONES else None


def sanitize_filename(filename: str) -> str:
    name = Path(str(filename or "file").strip()).name or "file"
    cleaned = _FILENAME_UNSAFE.sub("_", name).strip(" .")
    return cleaned or "file"


def unique_relative_path(user_id: int, relative: str) -> str:
    """Return relative path, adding _2, _3 suffix before extension if taken."""
    target = resolve_workspace_path(user_id, relative)
    if not target.exists():
        return sanitize_relative_path(relative)
    stem = target.stem
    suffix = target.suffix
    parent = sanitize_relative_path(str(Path(sanitize_relative_path(relative)).parent))
    for index in range(2, 1000):
        candidate_name = f"{stem}_{index}{suffix}"
        candidate = f"{parent}/{candidate_name}" if parent != "." else candidate_name
        if not resolve_workspace_path(user_id, candidate).exists():
            return candidate
    raise WorkspacePathError("could not allocate unique filename")
