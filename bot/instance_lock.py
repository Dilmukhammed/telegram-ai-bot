from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class BotInstanceLockError(RuntimeError):
    pass


class BotInstanceLock:
    """Exclusive lock so only one bot process polls Telegram at a time."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "a+b")

    def acquire(self) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BotInstanceLockError(
                f"Another bot instance is already running (lock: {self._path}). "
                "Stop the other process to avoid TelegramConflictError."
            ) from exc

        self._file.seek(0)
        self._file.truncate()
        self._file.write(str(os.getpid()).encode("ascii"))
        self._file.flush()
        logger.info("bot_instance_lock acquired path=%s pid=%s", self._path, os.getpid())

    def release(self) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            logger.info("bot_instance_lock released path=%s", self._path)


def acquire_instance_lock(path: str | Path) -> BotInstanceLock:
    lock = BotInstanceLock(path)
    lock.acquire()
    return lock
