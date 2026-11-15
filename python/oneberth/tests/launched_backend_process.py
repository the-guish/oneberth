# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""A backend as the launcher starts it, for the tests of the launcher.

    python launched_backend_process.py

It reads where to listen and the data directory from the launcher's variables,
composes a sample on the SQLite store there, and serves the page of
``launcher_page/``. A person's read and a worker's claim report to the test's
probe, at the port ``PROBE_PORT`` names, or on standard output without one.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

from fastapi import APIRouter

from oneberth.config import local_config
from oneberth.identity import Role, RoleTable
from oneberth.launcher import LaunchedBackend
from oneberth.stores import opened_store
from oneberth.web import Asking, Component, Listen, compose_app, permit, run

NOTES = RoleTable(
    app="notes",
    permissions=frozenset({"notes/items:read", "notes/tasks:claim"}),
    roles=(
        Role("notes/user", frozenset({"notes/items:read"}), people=True),
        Role("notes/worker", frozenset({"notes/tasks:claim"}), resource="queue"),
    ),
    default="notes/user",
)


def report(text: str) -> None:
    """Tell the test's probe, or print it for the launcher's log in a
    container, which gets no probe."""
    if "PROBE_PORT" not in os.environ:
        print(text, flush=True)
        return
    with socket.create_connection(("127.0.0.1", int(os.environ["PROBE_PORT"]))) as to:
        to.sendall(f"{text}\n".encode())


def main() -> None:
    launched = LaunchedBackend.from_environ()
    assert launched is not None, "started without a launcher"
    router = APIRouter()

    @router.get("/items", dependencies=[permit("notes/items:read")])
    async def items(principal: Asking) -> dict[str, str]:
        report(f"items for {principal.name}")
        return {"for": principal.name}

    @router.post(
        "/queues/{queue}/claims", dependencies=[permit("notes/tasks:claim", "queue")]
    )
    async def claim(queue: str, principal: Asking) -> dict[str, str]:
        return {"queue": queue, "by": principal.name}

    app = compose_app(
        [Component("notes", NOTES, router)],
        config=local_config("notes", port=launched.front_port, host=launched.host),
        store=lambda: opened_store(data_dir=launched.data_dir, setup=True),
        interface=Path(__file__).with_name("launcher_page"),
        local=True,
        local_user="Ada",
    )
    run(
        app,
        Listen(launched.front_bind, launched.front_port),
        Listen(launched.worker_bind, launched.worker_port),
    )


if __name__ == "__main__":
    main()
