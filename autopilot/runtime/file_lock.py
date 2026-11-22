"""File descriptor locking for processes running on the same host."""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from typing import BinaryIO


def ensure_lockable_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def lock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive_file_lock(path: str, *, timeout: float):
    """Wait for the OS lock. Keep the lock file in place across acquisitions."""
    deadline = time.monotonic() + timeout
    with open(path, "a+b") as handle:
        while True:
            try:
                ensure_lockable_byte(handle)
                lock_file(handle)
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EDEADLK):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for the file lock") from exc
                time.sleep(min(0.025, remaining))
            else:
                break
        # Closing the descriptor releases the OS lock on all supported platforms.
        yield
