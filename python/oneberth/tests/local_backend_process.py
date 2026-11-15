# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""A start command in the local mode, for the tests of the server process.

    python local_backend_process.py PORT DATA_DIR

It composes the sample of ``test_web_local.py`` on the SQLite store in
``DATA_DIR`` and calls ``run``, as an application's start command does.
"""

from __future__ import annotations

import sys

from fastapi import APIRouter

from oneberth.config import local_config
from oneberth.identity import Role, RoleTable
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


def main() -> None:
    port, data_dir = int(sys.argv[1]), sys.argv[2]
    router = APIRouter()

    @router.post(
        "/queues/{queue}/claims", dependencies=[permit("notes/tasks:claim", "queue")]
    )
    async def claim(queue: str, principal: Asking) -> dict[str, str]:
        return {"queue": queue, "by": principal.name}

    app = compose_app(
        [Component("notes", NOTES, router)],
        config=local_config("notes", port=port),
        store=lambda: opened_store(data_dir=data_dir, setup=True),
        local=True,
    )
    run(app, Listen("127.0.0.1", port))


if __name__ == "__main__":
    main()
