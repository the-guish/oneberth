# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The launcher's logic: the order of the starts and the stops, and what
happens when a part ends (shapes.md, "The launcher" and "The window").

It runs against the ports alone. A start goes in the spec's order: what the
runtime prepares, such as the networks of the Docker shape, the launch
secret, the backend with the secret on its standard input, its ``ready``, one
service token per worker, each worker with its token on its standard input and
its ``ready``, the ticket, the window. A stop goes the other way: the window,
the workers, the backend last, then what the runtime prepared.

The application stops when the window closes, when a signal asks it to, or
when a part ends that should not have. The spec does not say to start a part
again, so a part that ends stops the whole application.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from oneberth.identity import CredentialKind, new_secret
from oneberth.launcher._describe import (
    BACKEND,
    WINDOW,
    WINDOW_STOP_SECONDS,
    Application,
    LauncherError,
    Run,
)
from oneberth.launcher._environment import DATA_DIR, LAUNCHER_PID, LOOPBACK, READY
from oneberth.launcher._ports import ApiFactory, BackendApi, Running, Runtime, Timer
from oneberth.launcher._ports import Windows as WindowsPort
from oneberth.launcher._shape import (
    backend_environment,
    backend_run,
    worker_environment,
    worker_network,
)

_log = logging.getLogger("oneberth.launcher")

AGAIN = "window, again"
"""The name of the browser process that brings the window forward."""


class Ending(StrEnum):
    """Why an application stopped."""

    WINDOW_CLOSED = "window closed"
    SIGNAL = "signal"
    PART_ENDED = "part ended"
    START_FAILED = "start failed"


@dataclass(frozen=True, slots=True)
class Outcome:
    """How a run of the launcher ended."""

    ending: Ending
    detail: str

    @property
    def code(self) -> int:
        """The exit code of the application's command."""
        return 0 if self.ending in (Ending.WINDOW_CLOSED, Ending.SIGNAL) else 1


@dataclass(eq=False)
class _Part:
    name: str
    label: str
    running: Running
    ready: asyncio.Future[None]
    ended: asyncio.Future[int]
    stopping: bool = False
    reader: asyncio.Task[None] | None = field(default=None, repr=False)


def _label(name: str) -> str:
    return name if name in (BACKEND, WINDOW) else f"worker {name!r}"


class Launcher:
    """Starts an application, waits for its end, and stops it.

    ``front_port`` and ``worker_port`` are the ports of the two listeners,
    chosen by whoever calls. ``api`` makes the client of the backend's routes.
    """

    def __init__(
        self,
        application: Application,
        *,
        runtime: Runtime,
        api: ApiFactory,
        windows: WindowsPort,
        timer: Timer,
        front_port: int,
        worker_port: int,
        launcher_pid: int | None = None,
        secret: Callable[[], str] | None = None,
    ) -> None:
        self.application = application
        self._runtime = runtime
        self._make_api = api
        self._windows = windows
        self._timer = timer
        self.front_port = front_port
        self.worker_port = worker_port
        self._pid = os.getpid() if launcher_pid is None else launcher_pid
        self._secret = secret or (lambda: new_secret(CredentialKind.LAUNCH))
        self._parts: dict[str, _Part] = {}
        self._api: BackendApi | None = None
        self._end: asyncio.Future[Outcome] | None = None
        self._asked: Outcome | None = None
        self._prepared = False
        self._stopping = False
        self._showing: set[asyncio.Task[None]] = set()

    @property
    def front_url(self) -> str:
        """The front listener's address, as the launcher reaches it."""
        return f"http://{LOOPBACK}:{self.front_port}"

    @property
    def pids(self) -> dict[str, int]:
        """The process id of each part that runs, by name."""
        return {
            name: part.running.pid
            for name, part in self._parts.items()
            if part.running.pid is not None and not part.ended.done()
        }

    def stop(self) -> None:
        """Stop the application, as a signal asks."""
        self._end_with(Outcome(Ending.SIGNAL, "a signal asked the application to stop"))

    def show(self) -> None:
        """Bring the window forward, as a second start asks."""
        if self._api is None or self._stopping:
            return
        task = asyncio.create_task(self._show(self._api))
        self._showing.add(task)
        task.add_done_callback(self._showing.discard)

    async def run(self) -> Outcome:
        """Start the application, wait for its end, and stop it. Every part
        has stopped when this returns, or when it is cancelled."""
        self._end = asyncio.get_running_loop().create_future()
        if self._asked is not None:
            self._end.set_result(self._asked)
        starting = asyncio.create_task(self._start())
        try:
            either: set[asyncio.Future[Any]] = {starting, self._end}
            await asyncio.wait(either, return_when=asyncio.FIRST_COMPLETED)
            if not starting.done():
                starting.cancel()
                await asyncio.gather(starting, return_exceptions=True)
                outcome = self._end.result()
            else:
                try:
                    starting.result()
                except LauncherError as error:
                    outcome = Outcome(Ending.START_FAILED, str(error))
                    self._end_with(outcome)
                else:
                    _log.info("%s runs", self.application.name)
                    outcome = await self._end
        finally:
            if not starting.done():
                starting.cancel()
                await asyncio.gather(starting, return_exceptions=True)
            await self._stop_all()
        _log.info("%s stopped: %s", self.application.name, outcome.detail)
        return outcome

    def _end_with(self, outcome: Outcome) -> None:
        if self._end is None:
            self._asked = self._asked or outcome
        elif not self._end.done():
            self._end.set_result(outcome)

    async def _start(self) -> None:
        application = self.application
        await self._runtime.prepare(application)
        self._prepared = True
        secret = self._secret()
        backend = await self._spawn(
            BACKEND,
            backend_run(application),
            backend_environment(
                application, self.front_port, self.worker_port, self._pid
            ),
            stdin=secret,
        )
        await self._until_ready(backend, application.backend.start_seconds)
        api = self._make_api(self.front_url, secret)
        tokens = {
            worker.name: await api.service_token(
                worker.name, worker.role, worker.resource
            )
            for worker in application.workers
        }
        workers = []
        for worker in application.workers:
            network = worker_network(application, worker)
            address = (
                LOOPBACK
                if network is None
                else await self._runtime.address(BACKEND, network)
            )
            environment = worker_environment(
                application,
                worker,
                address,
                self.front_port,
                self.worker_port,
                self._pid,
            )
            part = await self._spawn(
                worker.name, worker.run, environment, stdin=tokens[worker.name]
            )
            workers.append((part, worker.start_seconds))
        waits = [
            asyncio.create_task(self._until_ready(part, seconds))
            for part, seconds in workers
        ]
        try:
            await asyncio.gather(*waits)
        finally:
            for waiting in waits:
                waiting.cancel()
            await asyncio.gather(*waits, return_exceptions=True)
        if application.window is not None:
            url = await api.ticket_url()
            self._api = api
            await self._open(url)

    async def _spawn(
        self, name: str, run: Run, environment: dict[str, str], stdin: str | None
    ) -> _Part:
        running = await self._runtime.start(name, run, environment, stdin)
        loop = asyncio.get_running_loop()
        part = _Part(
            name, _label(name), running, loop.create_future(), loop.create_future()
        )
        self._parts[name] = part
        part.reader = asyncio.create_task(self._read(part), name=f"reads {name}")
        _log.info("%s started (pid %s)", part.label, running.pid)
        return part

    async def _read(self, part: _Part) -> None:
        """What a part prints, logged line by line until its ``ready``, which it
        notes, and its end, which stops the application unless it was asked."""
        while (line := await part.running.line()) is not None:
            text = line.rstrip("\r\n")
            if text.strip() == READY and not part.ready.done():
                part.ready.set_result(None)
                _log.info("%s is ready", part.label)
                continue
            _log.info("%s says: %s", part.label, text)
        code = await part.running.wait()
        part.ended.set_result(code)
        if part.stopping:
            return
        if part.name == WINDOW:
            self._end_with(Outcome(Ending.WINDOW_CLOSED, "the window was closed"))
        elif part.ready.done():
            self._end_with(
                Outcome(Ending.PART_ENDED, f"the {part.label} ended with code {code}")
            )

    async def _within(self, seconds: float, *futures: asyncio.Future[Any]) -> bool:
        """Whether one of ``futures`` is done before ``seconds`` pass on the timer."""
        sleeper = asyncio.ensure_future(self._timer.sleep(seconds))
        try:
            await asyncio.wait({*futures, sleeper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
        return any(future.done() for future in futures)

    async def _until_ready(self, part: _Part, seconds: float) -> None:
        await self._within(seconds, part.ready, part.ended)
        if part.ready.done():
            return
        if part.ended.done():
            raise LauncherError(
                f"the {part.label} ended with code {part.ended.result()}"
                " before it said ready"
            )
        raise LauncherError(f"the {part.label} did not say ready within {seconds:g} s")

    async def _open(self, url: str) -> None:
        run = self._windows.window(url)
        if run is None:
            _log.warning(
                "no Chrome, Chromium, Edge or Brave: the default browser opens %s,"
                " and the application stops on a signal alone",
                self.front_url,
            )
            await self._windows.open_elsewhere(url)
            return
        part = await self._spawn(WINDOW, run, self._window_environment(), stdin=None)
        part.ready.set_result(None)

    def _window_environment(self) -> dict[str, str]:
        return {
            DATA_DIR: os.fspath(self.application.data),
            LAUNCHER_PID: str(self._pid),
        }

    async def _show(self, api: BackendApi) -> None:
        try:
            url = await api.ticket_url()
            run = self._windows.window(url)
            if run is None or WINDOW not in self._parts:
                await self._windows.open_elsewhere(url)
                return
            # The browser hands the address to the window's process and ends.
            running = await self._runtime.start(
                AGAIN, run, self._window_environment(), None
            )
            drained = asyncio.create_task(_drained(running))
            try:
                await self._within(WINDOW_STOP_SECONDS, drained)
            finally:
                if not drained.done():
                    running.kill()
                    await drained
        except LauncherError as error:
            _log.warning("the window could not be brought forward: %s", error)

    async def _stop_all(self) -> None:
        self._stopping = True
        for task in list(self._showing):
            task.cancel()
        await asyncio.gather(*self._showing, return_exceptions=True)
        window = self._parts.get(WINDOW)
        if window is not None:
            await self._stop(window, WINDOW_STOP_SECONDS)
        await asyncio.gather(
            *(
                self._stop(self._parts[worker.name], worker.stop_seconds)
                for worker in self.application.workers
                if worker.name in self._parts
            )
        )
        backend = self._parts.get(BACKEND)
        if backend is not None:
            await self._stop(backend, self.application.backend.stop_seconds)
        if self._prepared:
            self._prepared = False
            await self._runtime.release()

    async def _stop(self, part: _Part, patience: float) -> None:
        part.stopping = True
        if not part.ended.done():
            _log.info("stopping the %s", part.label)
            part.running.terminate()
            if not await self._within(patience, part.ended):
                _log.warning(
                    "the %s did not stop within %g s: killed", part.label, patience
                )
                part.running.kill()
                await part.ended
        if part.reader is not None:
            await part.reader


async def _drained(running: Running) -> int:
    while await running.line() is not None:
        pass
    return await running.wait()
