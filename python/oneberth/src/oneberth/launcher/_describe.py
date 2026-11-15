# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""What an application gives the launcher: its backend, its workers, its data
directory and its window (shapes.md, "The launcher").

A component says how it runs with a ``Run``. ``Process`` is the one kind of
this version. The desktop with Docker adds a container to ``Run``, and the
runtime that starts it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from oneberth.identity import is_service_name

BACKEND = "backend"
"""The name the launcher gives the backend in its log and its messages."""

WINDOW = "window"
"""The name the launcher gives the window in its log and its messages."""

RESERVED = frozenset({BACKEND, WINDOW})
"""Names a worker may not take."""

BACKEND_START_SECONDS = 60.0
"""How long the launcher waits for the backend's ``ready`` by default."""

BACKEND_STOP_SECONDS = 30.0
"""How long the launcher waits for the backend after its SIGTERM by default: more
than the server waits for the answers in progress."""

WORKER_START_SECONDS = 60.0
"""How long the launcher waits for a worker's ``ready`` by default."""

WORKER_STOP_SECONDS = 15.0
"""How long the launcher waits for a worker after its SIGTERM by default: more
than a worker waits for its tasks."""

WINDOW_STOP_SECONDS = 5.0
"""How long the launcher waits for the window after its SIGTERM."""


class LauncherError(RuntimeError):
    """A description the launcher refuses, or a start that failed."""


class Trust(StrEnum):
    """The trust level of a worker (shapes.md, "Trust")."""

    TRUSTED = "trusted"
    """It runs the project's own code."""
    UNTRUSTED = "untrusted"
    """It runs code nobody reviewed. It runs in a container or in a VM."""


@dataclass(frozen=True, slots=True)
class Process:
    """A component that runs as a process of the host.

    The process inherits the launcher's environment, then gets
    ``environment``, then the variables the launcher sets.
    """

    command: Sequence[str]
    environment: Mapping[str, str] = field(default_factory=dict)
    directory: str | os.PathLike[str] | None = None
    """Where it runs: the launcher's working directory by default."""
    quiet: bool = False
    """Whether its standard error is discarded, as the window's is."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", tuple(self.command))
        object.__setattr__(self, "environment", dict(self.environment))
        if not self.command:
            raise LauncherError("a process needs a command")


Run = Process
"""How a component runs. The desktop with Docker adds a container."""


@dataclass(frozen=True, slots=True)
class Backend:
    """The backend: one process that serves both listeners and says ``ready``."""

    run: Run
    start_seconds: float = BACKEND_START_SECONDS
    stop_seconds: float = BACKEND_STOP_SECONDS


@dataclass(frozen=True, slots=True)
class Worker:
    """A worker: it gets a service token of ``role`` and says ``ready``.

    ``resource`` is the queue or the worker name the role is bound to, when the
    role needs one. ``name`` also names the token.
    """

    name: str
    role: str
    run: Run
    resource: str | None = None
    trust: Trust = Trust.TRUSTED
    start_seconds: float = WORKER_START_SECONDS
    stop_seconds: float = WORKER_STOP_SECONDS


@dataclass(frozen=True, slots=True)
class Window:
    """The window: Chrome or Chromium in application mode.

    ``browser`` is the browser's executable. Without one, the launcher looks for
    Chrome, Chromium, Edge and Brave, and opens the default browser when it
    finds none. ``arguments`` go to the browser after the launcher's own.
    """

    browser: str | os.PathLike[str] | None = None
    arguments: Sequence[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", tuple(self.arguments))


@dataclass(frozen=True, slots=True)
class Application:
    """What the launcher starts, and where its data lives.

    ``front_port`` is the port the front listener takes at the first start in
    ``data_dir``, when it is free. Every later start keeps the port of the
    first. ``window`` is ``None`` for a start with no window, such as a server.
    """

    name: str
    data_dir: str | os.PathLike[str]
    backend: Backend
    workers: Sequence[Worker] = ()
    front_port: int | None = None
    window: Window | None = field(default_factory=Window)

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir).absolute())
        object.__setattr__(self, "workers", tuple(self.workers))
        problems = problems_of(self)
        if problems:
            raise LauncherError("; ".join(problems))

    @property
    def data(self) -> Path:
        """The data directory, as an absolute path."""
        return Path(self.data_dir)


def problems_of(application: Application) -> list[str]:
    """What is wrong with a description, one sentence each."""
    problems = []
    seen: set[str] = set()
    for worker in application.workers:
        if not is_service_name(worker.name):
            problems.append(
                f"a worker's name has letters, digits and _ . - alone: {worker.name!r}"
            )
        elif worker.name in RESERVED:
            problems.append(f"a worker may not be named {worker.name!r}")
        elif worker.name in seen:
            problems.append(f"two workers are named {worker.name!r}")
        seen.add(worker.name)
        if worker.trust is Trust.UNTRUSTED and isinstance(worker.run, Process):
            problems.append(
                f"the worker {worker.name!r} is untrusted: it runs in a container"
            )
    port = application.front_port
    if port is not None and not 0 < port < 65536:
        problems.append(f"no port is numbered {port}")
    return problems
