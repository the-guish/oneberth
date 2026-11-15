# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The server: a composition on uvicorn, its front listener and its worker listener.

``serve`` starts the backend through the front listener, opens the worker
listener when one is asked for, and then prints ``ready`` on standard output,
the line a supervisor waits for (shapes.md, "Starting a worker"). SIGINT and
SIGTERM stop it: the worker listener first, then the front listener, whose
lifespan stops the components in reverse.

A backend in the local mode starts with a launch secret. ``run`` reads it from
standard input, where the launcher writes it. A start by hand has none there:
``run`` then makes one, and prints the address that signs the person in.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import socket
import sys
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import TextIO

import uvicorn

from oneberth.identity import CredentialKind, is_launch_secret, new_secret
from oneberth.web._compose import Composition

READY = "ready"
"""The line ``serve`` prints once both listeners accept connections."""

GRACE_SECONDS = 10.0
"""How long a stop waits for answers in progress, such as long polls."""


@dataclass(frozen=True, slots=True)
class Listen:
    """Where a listener accepts connections."""

    host: str
    port: int


Where = Listen | socket.socket
"""An address to bind, or a socket bound already, as a test or a supervisor has."""


class ServerError(RuntimeError):
    """The backend did not start, or a listener could not be opened."""


def say_ready() -> None:
    print(READY, flush=True)


def say_where(url: str) -> None:
    """Print the address that signs the person in, for a start by hand."""
    print(f"open {url}", flush=True)


def read_launch_secret(stream: TextIO | None) -> str | None:
    """The launch secret the launcher wrote on ``stream``: its first line.

    ``None`` for a start by hand: no stream, a terminal, or an empty first
    line. Raises ``ServerError`` for a line that is not a launch secret.
    """
    if stream is None or stream.closed or stream.isatty():
        return None
    line = stream.readline().strip()
    if not line:
        return None
    if not is_launch_secret(line):
        raise ServerError("standard input holds no launch secret")
    return line


class _Server(uvicorn.Server):
    """uvicorn's server, which says when it accepts connections and leaves the
    signals to ``serve``."""

    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        self.accepting = asyncio.Event()

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            self.accepting.set()

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        yield


async def serve(
    app: Composition,
    front: Where,
    worker: Where | None = None,
    *,
    ready: Callable[[], None] = say_ready,
    log_level: str = "info",
    grace_seconds: float = GRACE_SECONDS,
    stop: asyncio.Event | None = None,
    launch_secret: str | None = None,
    welcome: Callable[[str], None] | None = None,
) -> None:
    """Serve ``app`` until SIGINT, SIGTERM or ``stop``.

    ``front`` and ``worker`` are where its two listeners accept connections;
    without ``worker``, the worker listener stays closed. ``ready`` runs once
    both accept connections: it prints ``ready`` by default. Raises
    ``ServerError`` when the backend does not start.

    In the local mode, ``launch_secret`` is the secret of this start, unless
    ``app.launch_secret`` holds it already. ``welcome``, when given, gets the
    address of a ticket after ``ready``, as a start by hand prints it.
    """
    if launch_secret is not None:
        if not app.local:
            raise ServerError("a launch secret is for the local mode alone")
        app.launch_secret = launch_secret
    if app.local and app.launch_secret is None:
        raise ServerError("the local mode starts with a launch secret")
    stop = asyncio.Event() if stop is None else stop
    servers: list[tuple[_Server, asyncio.Task[None]]] = []
    loop = asyncio.get_running_loop()
    handled: list[signal.Signals] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(sig, stop.set)
            handled.append(sig)
    try:
        for listener, where in (("front", front), ("worker", worker)):
            if where is None:
                continue
            target = app.front if listener == "front" else app.worker
            config = uvicorn.Config(
                target,
                host=where.host if isinstance(where, Listen) else "127.0.0.1",
                port=where.port if isinstance(where, Listen) else 0,
                lifespan="on" if listener == "front" else "off",
                log_level=log_level,
                timeout_graceful_shutdown=int(grace_seconds),
                proxy_headers=False,
            )
            server = _Server(config)
            sockets = None if isinstance(where, Listen) else [where]
            task = asyncio.create_task(_serving(server, sockets), name=listener)
            servers.append((server, task))
            accepting = asyncio.create_task(server.accepting.wait())
            await asyncio.wait({task, accepting}, return_when=asyncio.FIRST_COMPLETED)
            if not server.accepting.is_set():
                accepting.cancel()
                await task
                raise ServerError(f"the {listener} listener did not start")
        ready()
        if welcome is not None and app.launch_secret is not None:
            welcome(await _ticket_url(app, app.launch_secret))
        stopping = asyncio.create_task(stop.wait())
        await asyncio.wait(
            {stopping, *(task for _, task in servers)},
            return_when=asyncio.FIRST_COMPLETED,
        )
        stopping.cancel()
    finally:
        for server, task in reversed(servers):
            server.should_exit = True
            await asyncio.gather(task, return_exceptions=True)
        for sig in handled:
            loop.remove_signal_handler(sig)


async def _ticket_url(app: Composition, launch_secret: str) -> str:
    launcher = await app.access.authenticate(launch_secret, bearer=True)
    ticket, _ = await app.access.create_ticket(launcher)
    return app.ticket_url(ticket)


async def _serving(server: _Server, sockets: list[socket.socket] | None) -> None:
    try:
        await server.serve(sockets=sockets)
    except SystemExit:
        # uvicorn exits when the lifespan's startup fails; it has logged why.
        return


def run(
    app: Composition,
    front: Where,
    worker: Where | None = None,
    *,
    stdin: TextIO | None = None,
) -> None:
    """Serve ``app`` until SIGINT or SIGTERM. Blocks. Exits 1 if it did not start.

    In the local mode, it reads the launch secret from ``stdin``, standard
    input by default. A start by hand has none there: it makes one, and prints
    ``open <url>`` after ``ready``, the address that signs the person in.
    """
    try:
        launch_secret, welcome = None, None
        if app.local:
            launch_secret = read_launch_secret(sys.stdin if stdin is None else stdin)
            if launch_secret is None:
                launch_secret = new_secret(CredentialKind.LAUNCH)
                welcome = say_where
        asyncio.run(
            serve(app, front, worker, launch_secret=launch_secret, welcome=welcome)
        )
    except ServerError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from None
