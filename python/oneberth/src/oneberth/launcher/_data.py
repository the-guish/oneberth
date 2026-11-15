# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""What the launcher keeps in the data directory: its lock, the port of the
front listener, and the window's profile.

One launcher runs per data directory. It holds a lock on ``launcher.lock``
and writes its process id there. The front listener keeps one port across
starts, kept in ``launcher.json``. A browser keeps the theme and the open
application per origin.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import socket
from collections.abc import Callable
from pathlib import Path
from typing import IO

from oneberth.launcher._describe import LauncherError
from oneberth.launcher._environment import LOOPBACK

LOCK_FILE = "launcher.lock"
STATE_FILE = "launcher.json"
PROFILE_DIRECTORY = "window"


class AlreadyRunning(LauncherError):
    """Another launcher holds the data directory."""

    def __init__(self, data_dir: Path, pid: int | None) -> None:
        super().__init__(f"a launcher runs on {data_dir} already (pid {pid})")
        self.pid = pid


def lock_path(data_dir: Path) -> Path:
    return data_dir / LOCK_FILE


def state_path(data_dir: Path) -> Path:
    return data_dir / STATE_FILE


def profile_path(data_dir: Path) -> Path:
    """The window's profile directory."""
    return data_dir / PROFILE_DIRECTORY


class DataLock:
    """The lock of one launcher on its data directory."""

    def __init__(self, data_dir: Path, file: IO[str]) -> None:
        self.data_dir = data_dir
        self._file = file

    @classmethod
    def claim(cls, data_dir: Path) -> DataLock:
        """Take the lock, or raise ``AlreadyRunning`` with the holder's pid."""
        data_dir.mkdir(parents=True, exist_ok=True)
        file = lock_path(data_dir).open("a+")
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            file.seek(0)
            text = file.read().strip()
            file.close()
            raise AlreadyRunning(
                data_dir, int(text) if text.isdigit() else None
            ) from None
        file.seek(0)
        file.truncate()
        file.write(f"{os.getpid()}\n")
        file.flush()
        return cls(data_dir, file)

    def release(self) -> None:
        """Let another launcher run on the data directory."""
        if self._file.closed:
            return
        self._file.seek(0)
        self._file.truncate()
        fcntl.flock(self._file, fcntl.LOCK_UN)
        self._file.close()

    def __enter__(self) -> DataLock:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


def is_free(port: int) -> bool:
    """Whether a listener can bind ``port`` on the loopback address now.

    It binds as uvicorn does, so a port that a stopped backend left in
    ``TIME_WAIT`` counts as free.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((LOOPBACK, port))
        except OSError:
            return False
    return True


def any_free_port() -> int:
    """A port the system has free on the loopback address now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK, 0))
        port: int = probe.getsockname()[1]
        return port


def choose_front_port(
    kept: int | None,
    preferred: int | None,
    free: Callable[[int], bool],
    any_free: Callable[[], int],
) -> int:
    """The front listener's port: the one an earlier start kept, else the
    application's, when free, else any free one.

    Raises ``LauncherError`` when the kept port is taken: a part of an earlier
    start may still run on the data directory.
    """
    if kept is not None:
        if free(kept):
            return kept
        raise LauncherError(
            f"port {kept}, where this data directory's window opens, is taken;"
            " a part of an earlier start may still run. Stop it, or remove"
            f" {STATE_FILE} from the data directory to take another port"
        )
    if preferred is not None and free(preferred):
        return preferred
    return any_free()


def kept_front_port(data_dir: Path) -> int | None:
    """The port an earlier start kept, if any."""
    with contextlib.suppress(FileNotFoundError, ValueError, KeyError, TypeError):
        port = json.loads(state_path(data_dir).read_text())["front_port"]
        if isinstance(port, int):
            return port
    return None


def keep_front_port(data_dir: Path, port: int) -> None:
    """Keep ``port`` for the next starts."""
    path = state_path(data_dir)
    written = path.with_suffix(".tmp")
    written.write_text(json.dumps({"front_port": port}) + "\n")
    written.replace(path)
