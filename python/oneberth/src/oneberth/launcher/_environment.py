# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The variables the launcher sets in each process's environment, and what a
backend or a worker reads them with (shapes.md, "Starting a worker").

A worker reads its token from standard input, where the launcher writes it, or
from the file ``ONEBERTH_TOKEN_FILE`` names, as a platform gives it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

DATA_DIR = "ONEBERTH_DATA_DIR"
"""The data directory. Every process the launcher starts has it."""
LAUNCHER_PID = "ONEBERTH_LAUNCHER_PID"
"""The launcher's process id. Every process the launcher starts has it."""
HOST = "ONEBERTH_HOST"
"""The backend's: the address both listeners bind."""
FRONT_PORT = "ONEBERTH_FRONT_PORT"
"""The backend's: the port of the front listener."""
WORKER_PORT = "ONEBERTH_WORKER_PORT"
"""The backend's: the port of the worker listener."""
WORKER_NAME = "ONEBERTH_WORKER_NAME"
"""A worker's: its name, which also names its token."""
WORKER_URL = "ONEBERTH_WORKER_URL"
"""A worker's: the address of the worker listener."""
FRONT_URL = "ONEBERTH_FRONT_URL"
"""A trusted worker's: the address of the front listener."""
TOKEN_FILE = "ONEBERTH_TOKEN_FILE"
"""Where a worker started by a platform reads its token. The launcher sets none."""

READY = "ready"
"""The line a backend or a worker prints on standard output once it serves."""

LOOPBACK = "127.0.0.1"
"""Where the front listener and the worker listener accept connections."""


def backend_environment(
    data_dir: Path, front_port: int, worker_port: int, launcher_pid: int
) -> dict[str, str]:
    """What the launcher sets in the backend's environment."""
    return {
        DATA_DIR: os.fspath(data_dir),
        LAUNCHER_PID: str(launcher_pid),
        HOST: LOOPBACK,
        FRONT_PORT: str(front_port),
        WORKER_PORT: str(worker_port),
    }


def worker_environment(
    data_dir: Path,
    name: str,
    worker_url: str,
    front_url: str | None,
    launcher_pid: int,
) -> dict[str, str]:
    """What the launcher sets in a worker's environment. An untrusted worker
    gets no ``front_url``."""
    environment = {
        DATA_DIR: os.fspath(data_dir),
        LAUNCHER_PID: str(launcher_pid),
        WORKER_NAME: name,
        WORKER_URL: worker_url,
    }
    if front_url is not None:
        environment[FRONT_URL] = front_url
    return environment


def _environ(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


@dataclass(frozen=True, slots=True)
class LaunchedBackend:
    """What a backend the launcher started reads from its environment."""

    data_dir: Path
    host: str
    front_port: int
    worker_port: int

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> LaunchedBackend | None:
        """The launcher's variables, or ``None`` for a start without a launcher."""
        found = _environ(environ)
        if FRONT_PORT not in found:
            return None
        return cls(
            Path(found[DATA_DIR]),
            found[HOST],
            int(found[FRONT_PORT]),
            int(found[WORKER_PORT]),
        )


@dataclass(frozen=True, slots=True)
class LaunchedWorker:
    """What a worker the launcher started reads from its environment."""

    name: str
    worker_url: str
    front_url: str | None
    data_dir: Path | None

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> LaunchedWorker | None:
        """The supervisor's variables, or ``None`` when none names the listener."""
        found = _environ(environ)
        if WORKER_URL not in found:
            return None
        data_dir = found.get(DATA_DIR)
        return cls(
            found[WORKER_NAME],
            found[WORKER_URL],
            found.get(FRONT_URL),
            Path(data_dir) if data_dir else None,
        )


def read_token(
    stdin: TextIO | None = None, environ: Mapping[str, str] | None = None
) -> str:
    """A worker's token: from the file ``ONEBERTH_TOKEN_FILE`` names, or else
    standard input, read to its end."""
    named = _environ(environ).get(TOKEN_FILE)
    if named:
        return Path(named).read_text().strip()
    return (sys.stdin if stdin is None else stdin).read().strip()


def say_ready() -> None:
    """Print ``ready`` on standard output: the line the launcher waits for."""
    print(READY, flush=True)
