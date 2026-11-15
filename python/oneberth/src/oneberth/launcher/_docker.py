# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The ``Docker`` port on the ``docker`` command.

Each method translates into ``docker`` commands. A container is created with
its networks, then started attached to its standard output, with its standard
input open when it gets a secret. The secret travels on that standard input
alone: it never appears in a command line, in an environment variable or in
``docker inspect``. The container's variables reach ``docker create`` in a
file that is removed once the container exists, and appear in no command line.

A container runs with Docker's init, which passes SIGTERM on to the
component. The launcher's SIGTERM reaches the container through
``docker kill``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from oneberth.launcher._describe import LauncherError
from oneberth.launcher._shape import GATEWAY_NAME, ContainerPlan, NetworkPlan

DOCKER = "docker"
"""The command the launcher runs."""

ANSWER_SECONDS = 60.0
"""How long one ``docker`` command may take, a pull aside."""

GONE_SECONDS = 20.0
"""How long the launcher waits for removed containers to leave their networks."""

_POLL_SECONDS = 0.25


async def _docker(
    *arguments: str, seconds: float | None = ANSWER_SECONDS
) -> tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            DOCKER,
            *arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        return 127, "", f"{DOCKER}: {error}"
    try:
        async with asyncio.timeout(seconds):
            out, err = await process.communicate()
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        return 124, "", f"{DOCKER} {arguments[0]} did not answer within {seconds:g} s"
    assert process.returncode is not None
    code = process.returncode
    return code, out.decode(errors="replace"), err.decode(errors="replace")


def _filters(labels: Mapping[str, str]) -> list[str]:
    return [part for k, v in labels.items() for part in ("--filter", f"label={k}={v}")]


def _label_options(labels: Mapping[str, str]) -> list[str]:
    return [part for k, v in labels.items() for part in ("--label", f"{k}={v}")]


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def create_arguments(plan: ContainerPlan, env_file: str, stdin: bool) -> list[str]:
    """The arguments of ``docker create`` for a plan: the first network alone,
    since ``docker network connect`` adds the others."""
    arguments = ["create", "--name", plan.name, "--init", "--rm"]
    arguments += _label_options(plan.labels)
    if stdin:
        arguments.append("--interactive")
    if plan.user is not None:
        arguments += ["--user", plan.user]
    arguments += ["--env-file", env_file]
    for mount in plan.mounts:
        option = f"type=bind,source={os.fspath(mount.source)},target={mount.target}"
        arguments += ["--mount", option + (",readonly" if mount.read_only else "")]
    if plan.gateway:
        arguments += ["--add-host", f"{GATEWAY_NAME}:host-gateway"]
    for published in plan.published:
        port = published.port
        arguments += ["--publish", f"{published.address}:{port}:{port}"]
    if plan.networks:
        first = plan.networks[0]
        arguments += ["--network", first.network]
        for alias in first.aliases:
            arguments += ["--network-alias", alias]
    else:
        arguments += ["--network", "none"]
    return [*arguments, plan.image, *plan.command]


def env_file_text(environment: Mapping[str, str]) -> str:
    """The container's variables, as ``docker create --env-file`` reads them."""
    return "".join(f"{name}={value}\n" for name, value in environment.items())


class ContainerRunning:
    """A container, through the ``docker start`` process attached to it.

    A stop goes to the container through ``docker kill``. The ``docker
    start`` process stays attached until the container ends, so the last
    lines the component prints still arrive.
    """

    def __init__(self, process: asyncio.subprocess.Process, name: str) -> None:
        self._process = process
        self._name = name
        self._signals: list[asyncio.Task[tuple[int, str, str]]] = []

    @property
    def pid(self) -> int | None:
        return None

    async def line(self) -> str | None:
        output = self._process.stdout
        if output is None:
            return None
        line = await output.readline()
        return line.decode(errors="replace") if line else None

    async def wait(self) -> int:
        code = await self._process.wait()
        await asyncio.gather(*self._signals)
        return code

    def terminate(self) -> None:
        if self._process.returncode is None:
            self._send("TERM")

    def kill(self) -> None:
        self._send("KILL")
        if self._process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._process.kill()

    def _send(self, name: str) -> None:
        self._signals.append(
            asyncio.ensure_future(_docker("kill", "--signal", name, self._name))
        )


class DockerCli:
    """The Docker daemon, through the ``docker`` command."""

    async def running(self) -> bool:
        code, _, _ = await _docker(
            "info", "--format", "{{.ServerVersion}}", seconds=15.0
        )
        return code == 0

    async def find_containers(self, labels: Mapping[str, str]) -> list[str]:
        return _lines(
            await self._ok("ps", "--all", "--format", "{{.Names}}", *_filters(labels))
        )

    async def find_networks(self, labels: Mapping[str, str]) -> list[str]:
        return _lines(
            await self._ok("network", "ls", "--format", "{{.Name}}", *_filters(labels))
        )

    async def remove_containers(self, names: list[str]) -> None:
        # One that Docker removes already, as it ended, answers an error here.
        await _docker("rm", "--force", "--volumes", *names)
        await self._until_gone(names)

    async def remove_networks(self, names: list[str]) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + GONE_SECONDS
        left = list(names)
        while left:
            code, _, err = await _docker("network", "rm", *left)
            if code == 0:
                return
            existing = set(
                _lines((await _docker("network", "ls", "--format", "{{.Name}}"))[1])
            )
            left = [name for name in left if name in existing]
            if not left:
                return
            if loop.time() > deadline:
                raise LauncherError(f"the networks {left} stay: {err.strip()}")
            await asyncio.sleep(_POLL_SECONDS)

    async def create_network(self, plan: NetworkPlan) -> None:
        options = ["network", "create", *_label_options(plan.labels)]
        if plan.isolated:
            # An internal network has no route out. Without an address of the
            # host on its bridge, its containers do not reach the host either.
            options += [
                "--internal",
                "--opt",
                "com.docker.network.bridge.inhibit_ipv4=true",
            ]
        await self._ok(*options, plan.name)

    async def start(self, plan: ContainerPlan, stdin: str | None) -> ContainerRunning:
        with tempfile.TemporaryDirectory(prefix="oneberth-") as private:
            env_file = Path(private) / "environment"
            env_file.touch(0o600)
            env_file.write_text(env_file_text(plan.environment))
            await self._ok(
                *create_arguments(plan, os.fspath(env_file), stdin is not None),
                seconds=None,
            )
        try:
            for joined in plan.networks[1:]:
                aliases = [p for a in joined.aliases for p in ("--alias", a)]
                await self._ok(
                    "network", "connect", *aliases, joined.network, plan.name
                )
            process = await self._attach(plan.name, stdin is not None)
        except BaseException:
            await _docker("rm", "--force", plan.name)
            raise
        if process.stdin is not None and stdin is not None:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                process.stdin.write(stdin.encode())
                await process.stdin.drain()
            process.stdin.close()
        return ContainerRunning(process, plan.name)

    async def address(self, container: str, network: str) -> str:
        found = await self._ok(
            "inspect", "--format", "{{json .NetworkSettings.Networks}}", container
        )
        try:
            address = json.loads(found)[network]["IPAddress"]
        except (ValueError, KeyError, TypeError):
            address = None
        if not isinstance(address, str) or not address:
            raise LauncherError(f"{container} has no address on {network}")
        return address

    async def _attach(self, name: str, stdin: bool) -> asyncio.subprocess.Process:
        arguments: Sequence[str] = ("start", "--attach")
        if stdin:
            arguments = (*arguments, "--interactive")
        try:
            return await asyncio.create_subprocess_exec(
                DOCKER,
                *arguments,
                name,
                stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            raise LauncherError(f"{name} could not be started: {error}") from error

    async def _until_gone(self, names: list[str]) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + GONE_SECONDS
        wanted = set(names)
        while loop.time() < deadline:
            code, out, _ = await _docker("ps", "--all", "--format", "{{.Names}}")
            if code != 0 or not wanted & set(_lines(out)):
                return
            await asyncio.sleep(_POLL_SECONDS)

    async def _ok(self, *arguments: str, seconds: float | None = ANSWER_SECONDS) -> str:
        code, out, err = await _docker(*arguments, seconds=seconds)
        if code != 0:
            what = " ".join(arguments[:2])
            raise LauncherError(f"{DOCKER} {what} failed: {err.strip() or code}")
        return out
