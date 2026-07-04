from __future__ import annotations

import contextvars
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from config import get_settings
from tools.filename_utils import ensure_filename_extension

_REF_PATTERN = re.compile(r"^[a-z0-9]{8,16}:\d{3,}$")


@dataclass(frozen=True)
class StoredRunFile:
    file_ref: str
    path: Path
    filename: str
    mime_type: str | None
    size: int
    user_id: int


class RunFileStore:
    def __init__(self, *, run_id: str, user_id: int | None) -> None:
        self._run_id = run_id
        self._user_id = user_id
        self._root = Path(tempfile.mkdtemp(prefix=f"hermes_{run_id}_"))
        self._refs: dict[str, StoredRunFile] = {}
        self._counter = 0

    @property
    def run_id(self) -> str:
        return self._run_id

    def save(
        self,
        data: bytes,
        *,
        filename: str,
        mime_type: str | None,
    ) -> dict[str, object]:
        if self._user_id is None:
            raise RuntimeError("Telegram user_id is required to store run files")

        settings = get_settings()
        size = len(data)
        max_bytes = settings.run_file_max_bytes
        if size > max_bytes:
            raise ValueError(
                f"File too large ({size} bytes; max storable {max_bytes} bytes)"
            )

        safe_name = ensure_filename_extension(
            Path(filename or "file").name or "file",
            mime_type,
        )
        self._counter += 1
        file_ref = f"{self._run_id}:{self._counter:03d}"
        path = self._root / f"{self._counter:03d}_{safe_name}"
        path.write_bytes(data)

        stored = StoredRunFile(
            file_ref=file_ref,
            path=path,
            filename=safe_name,
            mime_type=mime_type,
            size=size,
            user_id=self._user_id,
        )
        self._refs[file_ref] = stored
        return {
            "file_ref": file_ref,
            "filename": safe_name,
            "mime_type": mime_type,
            "size": size,
        }

    def resolve(self, file_ref: str) -> StoredRunFile:
        ref = str(file_ref or "").strip()
        if not _REF_PATTERN.match(ref):
            raise KeyError(f"Invalid file_ref: {file_ref!r}")
        if not ref.startswith(f"{self._run_id}:"):
            raise KeyError(f"file_ref {file_ref!r} is not from the current agent run")
        try:
            return self._refs[ref]
        except KeyError as exc:
            raise KeyError(f"Unknown file_ref: {file_ref!r}") from exc

    def cleanup(self) -> None:
        shutil.rmtree(self._root, ignore_errors=True)


_run_file_store: contextvars.ContextVar[RunFileStore | None] = contextvars.ContextVar(
    "run_file_store",
    default=None,
)


def set_run_file_store(store: RunFileStore) -> contextvars.Token[RunFileStore | None]:
    return _run_file_store.set(store)


def reset_run_file_store(token: contextvars.Token[RunFileStore | None]) -> None:
    _run_file_store.reset(token)


def get_run_file_store() -> RunFileStore | None:
    return _run_file_store.get()


def require_run_file_store() -> RunFileStore:
    store = get_run_file_store()
    if store is None:
        raise RuntimeError(
            "Run file store is not active. Download tools only work during an agent run."
        )
    return store
