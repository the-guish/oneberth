# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""``launch``: what an application's command calls to start the desktop.

It takes the data directory's lock, keeps the front listener's port, starts
the application, and stops it on SIGINT, SIGTERM or SIGHUP, or when the window
closes. In the Docker shape it first refuses while Docker is not running, and
removes what a crashed start left: a backend's container left running holds
the front listener's port. A second start on the same data
directory sends SIGUSR1 to the first launcher, which brings its window forward.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys

from oneberth.launcher._containers import DockerRuntime, clean, launcher_user
from oneberth.launcher._core import Launcher, Outcome
from oneberth.launcher._data import (
    AlreadyRunning,
    DataLock,
    any_free_port,
    choose_front_port,
    is_free,
    keep_front_port,
    kept_front_port,
    profile_path,
)
from oneberth.launcher._describe import Application, LauncherError, Window
from oneberth.launcher._docker import DockerCli
from oneberth.launcher._http import HttpBackendApi
from oneberth.launcher._ports import Docker, Runtime
from oneberth.launcher._processes import ProcessRuntime
from oneberth.launcher._shape import Shape, shape_of
from oneberth.launcher._window import BrowserWindows

STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
"""The signals that stop the application."""

SHOW_SIGNAL = signal.SIGUSR1
"""The signal a second start sends to bring the window forward."""


class AsyncioTimer:
    """The event loop's time."""

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def desktop_launcher(
    application: Application,
    *,
    front_port: int,
    worker_port: int,
    docker: Docker | None = None,
) -> Launcher:
    """A launcher for the application's shape: every part as a process of
    this host, or the containers through ``docker``, the ``docker`` command
    by default."""
    runtime: Runtime = ProcessRuntime()
    if shape_of(application) is Shape.DOCKER:
        runtime = DockerRuntime(
            docker or DockerCli(),
            runtime,
            front_port=front_port,
            worker_port=worker_port,
            user=launcher_user(),
        )
    return Launcher(
        application,
        runtime=runtime,
        api=HttpBackendApi,
        windows=BrowserWindows(
            application.window or Window(), profile_path(application.data)
        ),
        timer=AsyncioTimer(),
        front_port=front_port,
        worker_port=worker_port,
    )


def launch(application: Application) -> int:
    """Start the desktop and block until it stops. Returns the exit code.

    An application's command ends with ``raise SystemExit(launch(...))``.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    try:
        lock = DataLock.claim(application.data)
    except AlreadyRunning as running:
        return _bring_forward(running)
    with lock:
        try:
            if shape_of(application) is Shape.DOCKER:
                left = asyncio.run(clean(DockerCli(), application))
                if left:
                    print(
                        f"removed what an earlier start left: {', '.join(left)}",
                        file=sys.stderr,
                    )
            front_port = choose_front_port(
                kept_front_port(application.data),
                application.front_port,
                is_free,
                any_free_port,
            )
        except LauncherError as error:
            print(error, file=sys.stderr)
            return 1
        keep_front_port(application.data, front_port)
        worker_port = any_free_port()
        while worker_port == front_port:
            worker_port = any_free_port()
        launcher = desktop_launcher(
            application, front_port=front_port, worker_port=worker_port
        )
        outcome = asyncio.run(_run(launcher))
    if outcome.code:
        print(f"{application.name} stopped: {outcome.detail}", file=sys.stderr)
    return outcome.code


async def _run(launcher: Launcher) -> Outcome:
    loop = asyncio.get_running_loop()
    for signum in STOP_SIGNALS:
        loop.add_signal_handler(signum, launcher.stop)
    loop.add_signal_handler(SHOW_SIGNAL, launcher.show)
    try:
        return await launcher.run()
    finally:
        for signum in (*STOP_SIGNALS, SHOW_SIGNAL):
            loop.remove_signal_handler(signum)


def _bring_forward(running: AlreadyRunning) -> int:
    if running.pid is None or running.pid == os.getpid():
        print(running, file=sys.stderr)
        return 1
    with contextlib.suppress(ProcessLookupError):
        os.kill(running.pid, SHOW_SIGNAL)
        print(f"{running}: its window comes forward", file=sys.stderr)
        return 0
    print(running, file=sys.stderr)
    return 1
