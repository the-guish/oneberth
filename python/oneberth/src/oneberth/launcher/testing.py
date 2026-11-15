# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""Stand-ins for the launcher's ports, which a test drives by hand.

``StandIns`` holds one of each and a journal of what the launcher asked of
them, in order. Its processes say ``ready`` as they start, unless a test makes
them ``silent``, and stop on SIGTERM, unless a test makes them ``stubborn``.
``MemoryDocker`` keeps networks and containers as Docker does, and its
containers are stand-in processes too. ``ManualTimer`` lets time pass only
when a test advances it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

from oneberth.launcher._containers import DockerRuntime
from oneberth.launcher._core import AGAIN, Launcher
from oneberth.launcher._describe import (
    BACKEND,
    WINDOW,
    Application,
    LauncherError,
    Process,
)
from oneberth.launcher._environment import READY
from oneberth.launcher._ports import Runtime
from oneberth.launcher._shape import (
    PART_LABEL,
    ContainerPlan,
    NetworkPlan,
    Shape,
    shape_of,
)

_SETTLE_TURNS = 20
"""How many turns of the event loop a sleeper must last to count as sleeping."""


class ManualTimer:
    """A timer whose time passes when a test calls ``advance``."""

    def __init__(self) -> None:
        self.now = 0.0
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []
        self._slept = asyncio.Event()

    async def sleep(self, seconds: float) -> None:
        entry = (self.now + seconds, asyncio.get_running_loop().create_future())
        self._sleepers.append(entry)
        self._slept.set()
        try:
            await entry[1]
        finally:
            self._sleepers.remove(entry)

    async def sleeping(self, seconds: float) -> None:
        """Wait until something sleeps until ``seconds`` from now, and still
        sleeps once the other tasks have had their turns."""
        while True:
            for _ in range(_SETTLE_TURNS):
                await asyncio.sleep(0)
            if any(
                deadline - self.now == seconds and not done.done()
                for deadline, done in self._sleepers
            ):
                return
            self._slept.clear()
            await self._slept.wait()

    def advance(self, seconds: float) -> None:
        """Let ``seconds`` pass, and wake what sleeps until then."""
        self.now += seconds
        for deadline, done in self._sleepers:
            if deadline <= self.now and not done.done():
                done.set_result(None)


class StandInProcess:
    """A part the launcher started, which a test makes speak and end."""

    def __init__(
        self,
        name: str,
        run: object,
        environment: Mapping[str, str],
        stdin: str | None,
        pid: int,
        journal: list[str],
        obeys: bool,
    ) -> None:
        self.name = name
        self.run = run
        self.environment = dict(environment)
        self.stdin = stdin
        self.code: int | None = None
        self._pid = pid
        self._journal = journal
        self._obeys = obeys
        self._lines: asyncio.Queue[str | None] = asyncio.Queue()
        self._ended = asyncio.Event()
        self.when_ended: list[Callable[[], None]] = []
        """What runs once it has ended."""

    @property
    def pid(self) -> int | None:
        return self._pid

    async def line(self) -> str | None:
        line = await self._lines.get()
        if line is None:
            self._lines.put_nowait(None)
        return line

    async def wait(self) -> int:
        await self._ended.wait()
        assert self.code is not None
        return self.code

    def terminate(self) -> None:
        self._journal.append(f"stop {self.name}")
        if self._obeys:
            self.exit(0)

    def kill(self) -> None:
        self._journal.append(f"kill {self.name}")
        self.exit(-9)

    def say(self, line: str) -> None:
        """Print ``line`` on standard output."""
        self._lines.put_nowait(line + "\n")

    def exit(self, code: int) -> None:
        """End with ``code``, unless it has ended already."""
        if self.code is None:
            self.code = code
            self._lines.put_nowait(None)
            self._ended.set()
            for then in self.when_ended:
                then()

    @property
    def ended(self) -> bool:
        return self.code is not None


class StandInRuntime:
    """Starts stand-in processes, and notes each start in the journal."""

    def __init__(self, journal: list[str]) -> None:
        self.processes: dict[str, StandInProcess] = {}
        self.silent: set[str] = set()
        """Names whose process never says ``ready``."""
        self.stubborn: set[str] = set()
        """Names whose process ignores SIGTERM."""
        self.refused: set[str] = set()
        """Names whose process cannot be started."""
        self._journal = journal
        self._started = asyncio.Event()

    async def prepare(self, application: Application) -> None:
        self._journal.append("prepare")

    async def release(self) -> None:
        self._journal.append("release")

    async def address(self, name: str, network: str) -> str:
        raise LauncherError(f"no network joins the processes: {network}")

    async def start(
        self,
        name: str,
        run: object,
        environment: Mapping[str, str],
        stdin: str | None,
    ) -> StandInProcess:
        if name in self.refused:
            raise LauncherError(f"{name} could not be started")
        process = StandInProcess(
            name,
            run,
            environment,
            stdin,
            1000 + len(self.processes),
            self._journal,
            obeys=name not in self.stubborn,
        )
        self._journal.append(f"start {name}")
        self.processes[name] = process
        self._started.set()
        if name == AGAIN:
            process.exit(0)
        elif name != WINDOW and name not in self.silent:
            process.say(READY)
        return process

    async def process(self, name: str) -> StandInProcess:
        """The process of ``name``, once the launcher has started it."""
        while name not in self.processes:
            self._started.clear()
            await self._started.wait()
        return self.processes[name]


class MemoryDocker:
    """Docker in memory: networks and containers with their labels.

    A container is a stand-in process of ``runtime``, which notes its start in
    the journal. Docker removes a container once it ends. ``up`` says whether
    the daemon answers. ``leave`` puts what a crashed start left.
    """

    def __init__(self, runtime: StandInRuntime, journal: list[str]) -> None:
        self.up = True
        self.networks: dict[str, NetworkPlan] = {}
        self.containers: dict[str, Mapping[str, str]] = {}
        """The labels of each container, by its name."""
        self.plans: dict[str, ContainerPlan] = {}
        """The plan of each container the launcher started, by its component."""
        self.attached: dict[str, set[str]] = {}
        """The containers on each network."""
        self._runtime = runtime
        self._journal = journal
        self._addresses: dict[tuple[str, str], str] = {}

    def leave(
        self,
        container: str | None,
        networks: list[str],
        labels: Mapping[str, str],
    ) -> None:
        """What a start that crashed left: a container on ``networks``."""
        for network in networks:
            self.networks.setdefault(network, NetworkPlan(network, False, labels))
            self.attached.setdefault(network, set())
            if container is not None:
                self.attached[network].add(container)
        if container is not None:
            self.containers[container] = {**labels, PART_LABEL: "left"}

    async def running(self) -> bool:
        return self.up

    async def find_containers(self, labels: Mapping[str, str]) -> list[str]:
        return [
            name
            for name, found in self.containers.items()
            if labels.items() <= found.items()
        ]

    async def find_networks(self, labels: Mapping[str, str]) -> list[str]:
        return [
            name
            for name, plan in self.networks.items()
            if labels.items() <= plan.labels.items()
        ]

    async def remove_containers(self, names: list[str]) -> None:
        self._journal.append(f"remove containers {', '.join(names)}")
        for name in names:
            self._gone(name)
            process = self._runtime.processes.get(self._part(name))
            if process is not None:
                process.exit(-9)

    async def remove_networks(self, names: list[str]) -> None:
        for name in names:
            if self.attached.get(name):
                raise LauncherError(f"the network {name} has active endpoints")
        self._journal.append(f"remove networks {', '.join(names)}")
        for name in names:
            self.networks.pop(name, None)
            self.attached.pop(name, None)

    async def create_network(self, plan: NetworkPlan) -> None:
        if plan.name in self.networks:
            raise LauncherError(f"the network {plan.name} exists already")
        self._journal.append(f"network {plan.name}")
        self.networks[plan.name] = plan
        self.attached[plan.name] = set()

    async def start(self, plan: ContainerPlan, stdin: str | None) -> StandInProcess:
        part = plan.labels[PART_LABEL]
        if plan.name in self.containers:
            raise LauncherError(f"the container {plan.name} exists already")
        for joined in plan.networks:
            if joined.network not in self.networks:
                raise LauncherError(f"no network is named {joined.network}")
        process = await self._runtime.start(part, plan, plan.environment, stdin)
        self.plans[part] = plan
        self.containers[plan.name] = plan.labels
        for joined in plan.networks:
            self.attached[joined.network].add(plan.name)
            number = list(self.networks).index(joined.network) + 1
            address = f"10.0.{number}.{len(self.attached[joined.network]) + 1}"
            self._addresses[plan.name, joined.network] = address
        process.when_ended.append(lambda: self._gone(plan.name))
        return process

    async def address(self, container: str, network: str) -> str:
        if container not in self.containers or (container, network) not in (
            self._addresses
        ):
            raise LauncherError(f"{container} has no address on {network}")
        return self._addresses[container, network]

    def _part(self, name: str) -> str:
        return self.containers.get(name, {}).get(PART_LABEL, name)

    def _gone(self, name: str) -> None:
        self.containers.pop(name, None)
        for attached in self.attached.values():
            attached.discard(name)


class StandInApi:
    """The backend's routes, noting each call in the journal."""

    def __init__(self, journal: list[str]) -> None:
        self.refused = False
        """Whether the backend refuses every token."""
        self.secrets: list[str] = []
        """The launch secret of each start, in order."""
        self.front_url = ""
        self._journal = journal
        self._tickets = 0

    def __call__(self, front_url: str, secret: str) -> StandInApi:
        self.front_url = front_url
        self.secrets.append(secret)
        return self

    async def service_token(self, name: str, role: str, resource: str | None) -> str:
        if self.refused:
            raise LauncherError("the backend answered 403 to /auth/services")
        self._journal.append(f"token {name} {role} {resource}")
        return f"token-{name}"

    async def ticket_url(self) -> str:
        self._tickets += 1
        self._journal.append("ticket")
        return f"{self.front_url}/auth/local?ticket=t{self._tickets}"


class StandInWindows:
    """Opens the window in a stand-in browser, or nowhere."""

    def __init__(self, journal: list[str]) -> None:
        self.browser = True
        """Whether this machine has a browser for the window."""
        self._journal = journal

    def window(self, url: str) -> Process | None:
        return Process(("browser", f"--app={url}")) if self.browser else None

    async def open_elsewhere(self, url: str) -> None:
        self._journal.append(f"default browser {url}")


class StandIns:
    """One stand-in of each port, sharing one journal."""

    def __init__(self) -> None:
        self.journal: list[str] = []
        self.runtime = StandInRuntime(self.journal)
        self.api = StandInApi(self.journal)
        self.windows = StandInWindows(self.journal)
        self.timer = ManualTimer()
        self.docker = MemoryDocker(self.runtime, self.journal)

    def launcher(
        self,
        application: Application,
        *,
        front_port: int = 8420,
        worker_port: int = 8421,
    ) -> Launcher:
        runtime: Runtime = self.runtime
        if shape_of(application) is Shape.DOCKER:
            runtime = DockerRuntime(
                self.docker,
                self.runtime,
                front_port=front_port,
                worker_port=worker_port,
                user="1000:1000",
            )
        return Launcher(
            application,
            runtime=runtime,
            api=self.api,
            windows=self.windows,
            timer=self.timer,
            front_port=front_port,
            worker_port=worker_port,
            launcher_pid=1,
        )

    async def process(self, name: str = BACKEND) -> StandInProcess:
        return await self.runtime.process(name)


__all__ = [
    "ManualTimer",
    "MemoryDocker",
    "StandInApi",
    "StandInProcess",
    "StandInRuntime",
    "StandInWindows",
    "StandIns",
]
