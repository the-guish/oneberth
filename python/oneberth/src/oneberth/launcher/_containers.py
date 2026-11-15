# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The runtime of the Docker shape: the backend and some workers in
containers, the other workers as processes (shapes.md, "The desktop, with
Docker").

It runs against the ``Docker`` port. Before a start it refuses while Docker is
not running, and removes what a crashed start left on the same data
directory. It creates the two networks before the backend starts, and removes
every container and network of the data directory after the last part stops.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from oneberth.launcher._describe import Application, Container, LauncherError, Run
from oneberth.launcher._ports import Docker, Running, Runtime
from oneberth.launcher._shape import (
    container_name,
    container_plan,
    docker_workers,
    labels_of,
    network_name,
    network_plans,
)


def launcher_user() -> str | None:
    """The launcher's user and group, which a container runs as by default."""
    if not hasattr(os, "getuid"):
        return None
    return f"{os.getuid()}:{os.getgid()}"


async def clean(docker: Docker, application: Application) -> list[str]:
    """Refuse while Docker is not running, then remove the containers and
    the networks of an earlier start on the same data directory.

    Returns the names of what was removed. One launcher runs per data
    directory, so what is left comes from a start that crashed.
    """
    if not await docker.running():
        needing = ", ".join(repr(n) for n in docker_workers(application))
        raise LauncherError(
            f"Docker is not running; it runs the workers {needing}."
            " Start Docker, then start again"
        )
    return await _remove_all(docker, application)


async def _remove_all(docker: Docker, application: Application) -> list[str]:
    """Remove every container of the data directory, then every network."""
    labels = labels_of(application.data)
    containers = await docker.find_containers(labels)
    if containers:
        await docker.remove_containers(containers)
    networks = await docker.find_networks(labels)
    if networks:
        await docker.remove_networks(networks)
    return [*containers, *networks]


class DockerRuntime:
    """Starts a ``Container`` with Docker and a ``Process`` with ``processes``."""

    def __init__(
        self,
        docker: Docker,
        processes: Runtime,
        *,
        front_port: int,
        worker_port: int,
        user: str | None = None,
    ) -> None:
        self._docker = docker
        self._processes = processes
        self._front_port = front_port
        self._worker_port = worker_port
        self._user = user
        self._application: Application | None = None

    async def prepare(self, application: Application) -> None:
        await clean(self._docker, application)
        self._application = application
        try:
            for plan in network_plans(application):
                await self._docker.create_network(plan)
        except BaseException:
            await self.release()
            raise

    async def release(self) -> None:
        application, self._application = self._application, None
        if application is None:
            return
        await _remove_all(self._docker, application)

    async def address(self, name: str, network: str) -> str:
        data = self._prepared().data
        return await self._docker.address(
            container_name(data, name), network_name(data, network)
        )

    async def start(
        self,
        name: str,
        run: Run,
        environment: Mapping[str, str],
        stdin: str | None,
    ) -> Running:
        if not isinstance(run, Container):
            return await self._processes.start(name, run, environment, stdin)
        plan = container_plan(
            self._prepared(),
            name,
            run,
            environment,
            front_port=self._front_port,
            worker_port=self._worker_port,
            user=self._user,
        )
        data = self._prepared().data
        for mount in plan.mounts:
            # A directory of the data directory is the component's own storage.
            if mount.source.is_relative_to(data):
                mount.source.mkdir(parents=True, exist_ok=True)
        return await self._docker.start(plan, stdin)

    def _prepared(self) -> Application:
        if self._application is None:
            raise LauncherError("the Docker runtime starts nothing before prepare")
        return self._application
