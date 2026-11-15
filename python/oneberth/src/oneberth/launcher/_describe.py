# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""What an application gives the launcher: its backend, its workers, its data
directory and its window (shapes.md, "The launcher").

A component says how it runs with a ``Run``: a ``Process`` of the host, or a
``Container`` of Docker. One worker in a container puts the whole application
in the Docker shape, and the backend then runs in its container too
(shapes.md, "The desktop, with Docker").
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

from oneberth.identity import is_service_name

BACKEND = "backend"
"""The name the launcher gives the backend in its log and its messages."""

WINDOW = "window"
"""The name the launcher gives the window in its log and its messages."""

RESERVED = frozenset({BACKEND, WINDOW})
"""Names a worker may not take."""

WORKERS_DIRECTORY = "workers"
"""The directory of the data directory that holds each worker's own directory."""

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
    """It runs code nobody reviewed. It runs in a container or in a VM, and
    sees one directory of the host: its own (``worker_directory``)."""


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


@dataclass(frozen=True, slots=True)
class Mount:
    """A directory of the host that a container sees at ``target``.

    A relative ``source`` is inside the data directory, such as
    ``workers/w1`` for the own directory of the worker ``w1``. An untrusted
    worker mounts its own directory, or a directory inside it, and nothing
    else.
    """

    source: str | os.PathLike[str]
    target: str
    read_only: bool = False


@dataclass(frozen=True, slots=True)
class Container:
    """A component that runs in a Docker container, from ``image``.

    ``command`` replaces the image's command when given. The container gets
    ``environment``, then the variables the launcher sets, and nothing of the
    launcher's own environment. It sees the directories ``mounts`` names, and
    no other directory of the host. It runs as ``user``, the launcher's user
    and group by default, so that the files it writes stay the person's.
    """

    image: str
    command: Sequence[str] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    mounts: Sequence[Mount] = ()
    user: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", tuple(self.command))
        object.__setattr__(self, "environment", dict(self.environment))
        object.__setattr__(self, "mounts", tuple(self.mounts))
        problems = _container_problems(self)
        if problems:
            raise LauncherError("; ".join(problems))


def _container_problems(container: Container) -> list[str]:
    problems = []
    if not container.image or container.image.startswith("-"):
        problems.append(f"a container needs an image: {container.image!r}")
    for name, value in container.environment.items():
        if not _VARIABLE.fullmatch(name):
            problems.append(f"no variable is named {name!r}")
        if "\n" in value or "\r" in value or "\0" in value:
            problems.append(f"the variable {name} holds a line break")
    targets: set[str] = set()
    for mount in container.mounts:
        target = PurePosixPath(mount.target)
        if not target.is_absolute() or ".." in target.parts or "," in mount.target:
            problems.append(f"a mount's target is an absolute path: {mount.target!r}")
        elif os.fspath(target) in targets:
            problems.append(f"two mounts have the target {mount.target!r}")
        targets.add(os.fspath(target))
        if "," in os.fspath(mount.source):
            problems.append(f"a mount's source has no comma: {mount.source!r}")
    return problems


_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

Run = Process | Container
"""How a component runs: a process of the host, or a Docker container."""


@dataclass(frozen=True, slots=True)
class Backend:
    """The backend: it serves both listeners and says ``ready``.

    ``container`` is how it runs in the Docker shape, when ``run`` is a
    process. The launcher picks the shape from the workers.
    """

    run: Run
    container: Container | None = None
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
        if worker.trust is Trust.UNTRUSTED:
            problems.extend(_untrusted_problems(application.data, worker))
    if any(isinstance(w.run, Container) for w in application.workers):
        backend = application.backend
        if not isinstance(backend.run, Container) and backend.container is None:
            problems.append(
                "a worker runs in a container: the backend needs a container too"
            )
    port = application.front_port
    if port is not None and not 0 < port < 65536:
        problems.append(f"no port is numbered {port}")
    return problems


def _untrusted_problems(data: Path, worker: Worker) -> list[str]:
    """An untrusted worker runs in a container, and mounts its own directory
    or a directory inside it. Everything else of the host is refused: the data
    directory with its databases and the window's profile, another worker's
    directory, a path outside the data directory, the Docker socket."""
    if not isinstance(worker.run, Container):
        return [f"the worker {worker.name!r} is untrusted: it runs in a container"]
    own = worker_directory(data, worker.name)
    problems = []
    for mount in worker.run.mounts:
        source = mount_source(data, mount)
        if not source.is_relative_to(own):
            problems.append(
                f"the worker {worker.name!r} is untrusted: it mounts its own"
                f" directory, {own}, or a directory inside it, not {source}"
            )
    return problems


def mount_source(data: Path, mount: Mount) -> Path:
    """The host directory of ``mount``, as an absolute path without ``..``."""
    return Path(os.path.normpath(data / mount.source))


def worker_directory(data: Path, name: str) -> Path:
    """The own directory of the worker ``name``: ``workers/<name>`` in the
    data directory, as an absolute path without ``..``. It is the one
    directory of the host an untrusted worker sees."""
    return Path(os.path.normpath(data / WORKERS_DIRECTORY / name))
