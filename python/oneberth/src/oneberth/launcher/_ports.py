# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The ports of the launcher: what it starts things with, how it asks the
backend, where it opens the window, and how it waits.

The launcher's logic runs against these alone. ``oneberth.launcher.testing``
holds stand-ins a test drives by hand; the launcher's adapters start real
processes and speak HTTP.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from oneberth.launcher._describe import Application, Process, Run


class Running(Protocol):
    """A component that was started."""

    @property
    def pid(self) -> int | None:
        """Its process id, when it has one on this host."""
        ...

    async def line(self) -> str | None:
        """The next line on its standard output; ``None`` once the output ends."""
        ...

    async def wait(self) -> int:
        """Its exit code, once it has ended."""
        ...

    def terminate(self) -> None:
        """Ask it to stop: SIGTERM."""
        ...

    def kill(self) -> None:
        """Stop it now: SIGKILL."""
        ...


class Runtime(Protocol):
    """What starts the components."""

    async def prepare(self, application: Application) -> None:
        """Set up what the components share before the backend starts."""
        ...

    async def release(self) -> None:
        """Undo ``prepare`` once every component has stopped."""
        ...

    def reach(self, run: Run, port: int) -> str:
        """The address a component started with ``run`` uses for a listener's port."""
        ...

    async def start(
        self,
        name: str,
        run: Run,
        environment: Mapping[str, str],
        stdin: str | None,
    ) -> Running:
        """Start ``run``. ``stdin`` is written on its standard input, which is
        then closed. Raises ``LauncherError`` when it cannot be started."""
        ...


class BackendApi(Protocol):
    """The backend's routes the launcher calls, with the launch secret."""

    async def service_token(self, name: str, role: str, resource: str | None) -> str:
        """A new service token's secret. Raises ``LauncherError`` on a refusal."""
        ...

    async def ticket_url(self) -> str:
        """The address that signs the local user in, with a new ticket."""
        ...


ApiFactory = Callable[[str, str], BackendApi]
"""Makes the ``BackendApi`` of a front listener's address and a launch secret."""


class Windows(Protocol):
    """Where the launcher opens the window."""

    def window(self, url: str) -> Process | None:
        """The window's process at ``url``, or ``None`` with no such browser."""
        ...

    async def open_elsewhere(self, url: str) -> None:
        """Open ``url`` in the default browser."""
        ...


class Timer(Protocol):
    """How the launcher waits."""

    async def sleep(self, seconds: float) -> None: ...
