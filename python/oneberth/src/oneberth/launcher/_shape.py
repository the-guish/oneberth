# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The shape an application runs in, and what each component gets in it
(shapes.md, "The desktop, as processes" and "The desktop, with Docker").

An application runs as processes, or in the Docker shape when one worker runs
in a container. In the Docker shape the backend runs in its container, on the
two networks: ``app`` holds the backend and the trusted workers' containers,
and ``sandbox`` holds the backend and the untrusted workers' containers. The
``sandbox`` network has no way out. The backend binds its front listener to its
address on ``app`` alone, so that the containers on ``sandbox`` reach the
worker listener alone. Both listeners are published on the host's loopback
address, for the window and for the workers that run as processes.

Everything here is a pure function of the description. The Docker runtime
turns a ``ContainerPlan`` into ``docker`` commands and decides nothing.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from oneberth.launcher._describe import (
    BACKEND,
    Application,
    Container,
    LauncherError,
    Run,
    Trust,
    Worker,
    mount_source,
    worker_directory,
)
from oneberth.launcher._environment import (
    DATA_DIR,
    FRONT_BIND,
    FRONT_PORT,
    FRONT_URL,
    HOST,
    LAUNCHER_PID,
    LOOPBACK,
    WORKER_BIND,
    WORKER_NAME,
    WORKER_PORT,
    WORKER_URL,
)


class Shape(StrEnum):
    """How the desktop runs."""

    PROCESSES = "processes"
    """Every component is a process of the host."""
    DOCKER = "docker"
    """The backend runs in a container, and some workers too."""


APP = "app"
"""The network of the backend and the trusted workers' containers."""
SANDBOX = "sandbox"
"""The network of the backend and the untrusted workers' containers. It has no
way out."""

FRONT_ALIAS = "front"
"""The backend's name on ``app`` alone. Its front listener binds the address
this name has, which the containers on ``sandbox`` cannot reach."""

ANY_ADDRESS = "0.0.0.0"
"""Where the backend's worker listener binds in its container: every network."""

CONTAINER_DATA_DIR = "/data"
"""Where the backend's container sees the data directory."""

GATEWAY_NAME = "host.docker.internal"
"""The name of the host for the backend's and the trusted workers' containers."""

DATA_LABEL = "oneberth.data-dir"
"""The label that ties a container or a network to its data directory."""
PART_LABEL = "oneberth.part"
"""The label that names the component of a container."""


def shape_of(application: Application) -> Shape:
    """The Docker shape when the backend or a worker runs in a container."""
    runs = [application.backend.run, *(w.run for w in application.workers)]
    if any(isinstance(run, Container) for run in runs):
        return Shape.DOCKER
    return Shape.PROCESSES


def backend_run(application: Application) -> Run:
    """How the backend runs in the application's shape."""
    backend = application.backend
    if shape_of(application) is Shape.PROCESSES or isinstance(backend.run, Container):
        return backend.run
    if backend.container is None:
        raise LauncherError("the backend has no container")
    return backend.container


def docker_workers(application: Application) -> list[str]:
    """The names of the workers that run in a container."""
    return [w.name for w in application.workers if isinstance(w.run, Container)]


def networks_of(application: Application, name: str) -> tuple[str, ...]:
    """The networks the component ``name`` joins: none for a process."""
    if name == BACKEND:
        if shape_of(application) is Shape.DOCKER:
            return (APP, SANDBOX)
        return ()
    worker = _worker(application, name)
    if not isinstance(worker.run, Container):
        return ()
    return (APP,) if worker.trust is Trust.TRUSTED else (SANDBOX,)


def _worker(application: Application, name: str) -> Worker:
    for worker in application.workers:
        if worker.name == name:
            return worker
    raise LauncherError(f"no worker is named {name!r}")


def backend_environment(
    application: Application, front_port: int, worker_port: int, launcher_pid: int
) -> dict[str, str]:
    """What the launcher sets in the backend's environment.

    ``ONEBERTH_HOST`` is the loopback address where the window reaches the front
    listener, in both shapes. The two binds say where each listener accepts
    connections: the loopback address for a process, and in a container the
    backend's address on ``app`` and every address.
    """
    ports = {FRONT_PORT: str(front_port), WORKER_PORT: str(worker_port)}
    if shape_of(application) is Shape.PROCESSES:
        return {
            DATA_DIR: os.fspath(application.data),
            LAUNCHER_PID: str(launcher_pid),
            HOST: LOOPBACK,
            **ports,
            FRONT_BIND: LOOPBACK,
            WORKER_BIND: LOOPBACK,
        }
    return {
        DATA_DIR: CONTAINER_DATA_DIR,
        HOST: LOOPBACK,
        **ports,
        FRONT_BIND: FRONT_ALIAS,
        WORKER_BIND: ANY_ADDRESS,
    }


def worker_environment(
    application: Application,
    worker: Worker,
    backend_address: str,
    front_port: int,
    worker_port: int,
    launcher_pid: int,
) -> dict[str, str]:
    """What the launcher sets in a worker's environment.

    ``backend_address`` is where the worker reaches the backend: the loopback
    address for a process, and the backend's address on the worker's network
    for a container. Only a trusted worker gets the front listener's address.
    A container gets no path of the host and no process id.
    """
    environment = {
        WORKER_NAME: worker.name,
        WORKER_URL: f"http://{backend_address}:{worker_port}",
    }
    if worker.trust is Trust.TRUSTED:
        environment[FRONT_URL] = f"http://{backend_address}:{front_port}"
    if isinstance(worker.run, Container):
        return environment
    return {
        DATA_DIR: os.fspath(application.data),
        LAUNCHER_PID: str(launcher_pid),
        **environment,
    }


def worker_network(application: Application, worker: Worker) -> str | None:
    """The network where a worker reaches the backend; ``None`` for a process."""
    networks = networks_of(application, worker.name)
    return networks[0] if networks else None


@dataclass(frozen=True, slots=True)
class NetworkPlan:
    """A Docker network of one start."""

    name: str
    isolated: bool
    """Whether it has no way out: no route beyond its own containers."""
    labels: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class MountPlan:
    """A directory of the host, seen by a container."""

    source: Path
    target: str
    read_only: bool
    create: bool = False
    """Whether the source is created before the start: a directory of the data
    directory, which is the component's own storage."""
    within: Path | None = None
    """The directory the source stays inside, once every link on its way is
    followed: an untrusted worker's own directory. ``None`` for a component
    that may see any directory of the host."""


@dataclass(frozen=True, slots=True)
class Joined:
    """A network a container joins, and its names there."""

    network: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Published:
    """A port of a container that the host's loopback address serves."""

    address: str
    port: int


@dataclass(frozen=True, slots=True)
class ContainerPlan:
    """Everything the Docker runtime needs to start one container."""

    name: str
    image: str
    command: tuple[str, ...]
    environment: Mapping[str, str]
    mounts: tuple[MountPlan, ...]
    networks: tuple[Joined, ...]
    published: tuple[Published, ...]
    gateway: bool
    """Whether the container reaches the host by ``GATEWAY_NAME``."""
    user: str | None
    labels: Mapping[str, str]


def prefix_of(data_dir: Path) -> str:
    """What starts the name of every container and network of a data directory."""
    digest = hashlib.sha256(os.fsencode(data_dir)).hexdigest()
    return f"oneberth-{digest[:12]}"


def labels_of(data_dir: Path) -> dict[str, str]:
    """The labels of every container and network of a data directory."""
    return {DATA_LABEL: os.fspath(data_dir)}


def network_name(data_dir: Path, network: str) -> str:
    """The Docker name of ``network`` for a data directory."""
    return f"{prefix_of(data_dir)}-{network}"


def container_name(data_dir: Path, name: str) -> str:
    """The Docker name of the container of the component ``name``."""
    return f"{prefix_of(data_dir)}-{name}"


def network_plans(application: Application) -> tuple[NetworkPlan, ...]:
    """The networks of a start in the Docker shape, in the order of creation."""
    data = application.data
    labels = labels_of(data)
    return (
        NetworkPlan(network_name(data, APP), isolated=False, labels=labels),
        NetworkPlan(network_name(data, SANDBOX), isolated=True, labels=labels),
    )


def container_plan(
    application: Application,
    name: str,
    run: Container,
    environment: Mapping[str, str],
    *,
    front_port: int,
    worker_port: int,
    user: str | None,
) -> ContainerPlan:
    """How the container of the component ``name`` starts.

    ``environment`` holds the launcher's variables, which win over the
    description's. ``user`` is the launcher's user, for a container that names
    none.
    """
    data = application.data
    networks = networks_of(application, name)
    sources = [(mount_source(data, m), m) for m in run.mounts]
    untrusted = name != BACKEND and _worker(application, name).trust is Trust.UNTRUSTED
    own = worker_directory(data, name) if untrusted else None
    mounts = tuple(
        MountPlan(source, m.target, m.read_only, source.is_relative_to(data), own)
        for source, m in sources
    )
    published: tuple[Published, ...] = ()
    if name == BACKEND:
        mounts = (MountPlan(data, CONTAINER_DATA_DIR, False, True), *mounts)
        published = (Published(LOOPBACK, front_port), Published(LOOPBACK, worker_port))
    return ContainerPlan(
        name=container_name(data, name),
        image=run.image,
        command=tuple(run.command),
        environment={**run.environment, **environment},
        mounts=mounts,
        networks=tuple(
            Joined(network_name(data, n), (FRONT_ALIAS,) if n == APP else ())
            if name == BACKEND
            else Joined(network_name(data, n))
            for n in networks
        ),
        published=published,
        gateway=APP in networks,
        user=run.user or user,
        labels={**labels_of(data), PART_LABEL: name},
    )
