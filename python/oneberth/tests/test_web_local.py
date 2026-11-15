# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""A composition in the local mode, over HTTP, in process and as a process.

The launcher's path runs on the memory and the SQLite stores: the launch
secret asks for a ticket, the window swaps it for a session, and the launcher
mints a worker's token that the worker listener takes. A start after a stop
keeps the personal token and ends the rest. Two tests start the real server
process: with a launch secret on its standard input, and by hand.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import APIRouter

from oneberth.config import ConfigError, local_config
from oneberth.identity import (
    CredentialKind,
    IdentityStore,
    Role,
    RoleTable,
    new_secret,
)
from oneberth.identity.memory import MemoryIdentityStore
from oneberth.identity.testing import ManualClock
from oneberth.stores import opened_store
from oneberth.web import (
    Asking,
    Component,
    Composition,
    ServerError,
    compose_app,
    permit,
    read_launch_secret,
    serve,
)
from oneberth.web.testing import (
    StandInProvider,
    bearer,
    client_of,
    config_for,
    launcher,
    running,
    signed_in,
)

PUBLIC_URL = "http://127.0.0.1:8000"
PROCESS = Path(__file__).with_name("local_backend_process.py")

NOTES = RoleTable(
    app="notes",
    permissions=frozenset({"notes/items:read", "notes/tasks:claim"}),
    roles=(
        Role("notes/user", frozenset({"notes/items:read"}), people=True),
        Role("notes/worker", frozenset({"notes/tasks:claim"}), resource="queue"),
    ),
    default="notes/user",
)


def notes() -> Component:
    router = APIRouter()

    @router.get("/items", dependencies=[permit("notes/items:read")])
    async def items(principal: Asking) -> dict[str, str]:
        return {"for": principal.name}

    @router.post(
        "/queues/{queue}/claims", dependencies=[permit("notes/tasks:claim", "queue")]
    )
    async def claim(queue: str, principal: Asking) -> dict[str, str]:
        return {"queue": queue, "by": principal.name}

    return Component("notes", NOTES, router)


def compose_local(
    store: IdentityStore | Callable[[], AbstractAsyncContextManager[IdentityStore]],
    clock: ManualClock | None = None,
) -> Composition:
    return compose_app(
        [notes()],
        config=local_config("notes", port=8000),
        store=store,
        clock=clock or ManualClock(),
        local=True,
        local_user="Ada",
    )


@pytest.fixture(params=["memory", "sqlite"])
async def store_source(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[Callable[[], AbstractAsyncContextManager[IdentityStore]]]:
    """What opens the desktop's store at each start, on the same data."""
    if request.param == "memory":
        store = MemoryIdentityStore()
        await store.setup()

        @asynccontextmanager
        async def kept() -> AsyncIterator[IdentityStore]:
            yield store

        yield kept
    else:
        yield lambda: opened_store(data_dir=tmp_path, setup=True)


async def test_the_launcher_signs_the_local_user_in_and_starts_a_worker(
    store_source: Callable[[], AbstractAsyncContextManager[IdentityStore]],
) -> None:
    clock = ManualClock()
    app = compose_local(store_source, clock)
    async with running(app) as window, client_of(app) as by_launcher:
        nobody = (await window.get("/auth/session")).json()
        assert nobody == {
            "mode": "local",
            "providers": [],
            "principal": None,
            "roles": [],
            "pairing": None,
        }

        # The launch secret alone asks for a ticket.
        assert (await by_launcher.post("/auth/tickets", json={})).status_code == 401
        wrong = bearer(new_secret(CredentialKind.LAUNCH))
        asked = await by_launcher.post("/auth/tickets", json={}, headers=wrong)
        assert asked.status_code == 401
        asked = await by_launcher.post("/auth/tickets", json={}, headers=launcher(app))
        assert asked.status_code == 201, asked.text
        url = asked.json()["url"]
        assert url == f"{PUBLIC_URL}/auth/local?ticket={asked.json()['ticket']}"

        # The window swaps it for a session that ends with the browser's.
        opened = await window.get(url)
        assert (opened.status_code, opened.headers["location"]) == (
            303,
            f"{PUBLIC_URL}/ui/",
        )
        cookie = opened.headers["set-cookie"]
        assert cookie.startswith("oneberth_session_8000=ob_ses_")
        assert "max-age" not in cookie.lower()
        session = (await window.get("/auth/session")).json()
        assert session["principal"]["provider"] == "!local"
        assert session["principal"]["name"] == "Ada"
        assert session["roles"] == ["notes/user", "oneberth/admin"]
        assert (await window.get("/notes/items")).json() == {"for": "Ada"}

        # A ticket works once.
        again = await by_launcher.get(url)
        assert (again.status_code, "set-cookie" in again.headers) == (303, False)

        # No fresh sign-in for a personal token, hours later.
        clock.advance(timedelta(hours=13))
        minted = await window.post("/auth/tokens", json={"name": "script"})
        assert minted.status_code == 201, minted.text
        personal = minted.json()["secret"]

        # The launcher mints a worker's token, which the worker listener takes.
        made = await by_launcher.post(
            "/auth/services",
            json={"name": "worker-1", "role": "notes/worker", "resource": "gpu"},
            headers=launcher(app),
        )
        assert made.status_code == 201, made.text
        worker_token = made.json()["secret"]
        async with client_of(app, worker=True) as worker:
            claimed = await worker.post(
                "/notes/queues/gpu/claims", json={}, headers=bearer(worker_token)
            )
            other = await worker.post(
                "/notes/queues/cpu/claims", json={}, headers=bearer(worker_token)
            )
            on_worker = await worker.get("/notes/items", headers=bearer(personal))
        assert claimed.json() == {"queue": "gpu", "by": "worker-1"}
        assert (other.status_code, on_worker.status_code) == (403, 404)
        listed = (await window.get("/auth/services")).json()["items"]
        assert [(t["name"], t["role"]) for t in listed] == [
            ("worker-1", "notes/worker")
        ]
        refused = await by_launcher.post(
            "/auth/services",
            json={"name": "l", "role": "oneberth/launcher"},
            headers=launcher(app),
        )
        assert refused.status_code == 422

        # A ticket after a minute signs nobody in.
        late = await by_launcher.post("/auth/tickets", json={}, headers=launcher(app))
        clock.advance(timedelta(minutes=1))
        assert "set-cookie" not in (await by_launcher.get(late.json()["url"])).headers
        window_cookie = window.cookies.get(app.cookies.session)

    # The next start: the session, the launch secret and the worker's token
    # ended with the stop. The personal token stays.
    app = compose_local(store_source, clock)
    async with running(app) as client:
        client.cookies.set(app.cookies.session, window_cookie or "")
        assert (await client.get("/auth/session")).json()["principal"] is None
        client.cookies.clear()
        async with client_of(app, worker=True) as worker:
            ended = await worker.post(
                "/notes/queues/gpu/claims", json={}, headers=bearer(worker_token)
            )
        assert ended.status_code == 401
        script = await client.get("/notes/items", headers=bearer(personal))
        assert script.json() == {"for": "Ada"}


@pytest.mark.parametrize(
    ("host", "front", "worker"),
    [
        ("127.0.0.1:8000", 200, 200),
        ("localhost:8000", 200, 200),
        ("localhost", 200, 200),
        ("[::1]:8000", 200, 200),
        ("192.168.1.10:8000", 200, 200),
        ("evil.example:8000", 403, 200),
        ("localhost.evil.example", 403, 200),
        ("host.docker.internal:8000", 403, 200),
        ("127.0.0.1:port", 403, 200),
    ],
)
async def test_the_front_listener_answers_a_host_of_localhost_or_an_ip_address(
    host: str, front: int, worker: int
) -> None:
    store = MemoryIdentityStore()
    await store.setup()
    app = compose_local(store)
    async with running(app) as client, client_of(app, worker=True) as on_worker:
        assert (await client.get("/health", headers={"host": host})).status_code == (
            front
        )
        answer = await on_worker.get("/health", headers={"host": host})
        assert answer.status_code == worker


async def test_the_application_tests_sign_the_local_user_in() -> None:
    store = MemoryIdentityStore()
    await store.setup()
    app = compose_local(store)
    async with running(app) as client:
        await signed_in(app, client)
        assert (await client.get("/notes/items")).json() == {"for": "Ada"}


async def test_the_local_mode_signs_in_through_no_provider() -> None:
    store = MemoryIdentityStore()
    with pytest.raises(ConfigError, match="local mode"):
        compose_app(
            [notes()],
            config=config_for("notes", public_url=PUBLIC_URL),
            store=store,
            local=True,
        )
    with pytest.raises(ConfigError, match="local mode"):
        local_config("notes", port=8000, host="example.com")


async def test_the_local_mode_starts_with_a_launch_secret() -> None:
    store = MemoryIdentityStore()
    await store.setup()
    with pytest.raises(ServerError, match="launch secret"):
        await serve(compose_local(store), socket.create_server(("127.0.0.1", 0)))
    with pytest.raises(ServerError, match="local mode alone"):
        await serve(
            compose_app(
                [notes()],
                config=config_for("notes", public_url=PUBLIC_URL),
                store=store,
            ),
            socket.create_server(("127.0.0.1", 0)),
            launch_secret=new_secret(CredentialKind.LAUNCH),
        )


async def test_the_mode_of_providers_has_no_tickets() -> None:
    store = MemoryIdentityStore()
    await store.setup()
    stand_in = StandInProvider()
    app = compose_app(
        [notes()],
        config=config_for(
            "notes", public_url=PUBLIC_URL, providers={"stand-in": stand_in.config}
        ),
        store=store,
        provider_transport=stand_in.transport(),
    )
    async with running(app) as client:
        assert (await client.get("/auth/session")).json()["mode"] == "providers"
        assert (await client.get("/auth/local?ticket=x")).status_code == 404
        asked = await client.post(
            "/auth/tickets",
            json={},
            headers=bearer(new_secret(CredentialKind.LAUNCH)),
        )
        assert asked.status_code == 401


class Lines:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.closed = False

    def isatty(self) -> bool:
        return False

    def readline(self) -> str:
        return self.lines.pop(0) if self.lines else ""


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        ([], None),
        (["\n"], None),
        (["ob_lch_" + "a" * 43 + "\n"], "ob_lch_" + "a" * 43),
        (["ob_lch_" + "a" * 43], "ob_lch_" + "a" * 43),
        (["  ob_lch_" + "a" * 43 + "  \r\n"], "ob_lch_" + "a" * 43),
        (["hello\n"], ServerError),
    ],
)
def test_the_launch_secret_is_the_first_line_of_standard_input(
    lines: list[str], expected: str | type[Exception] | None
) -> None:
    stream: Any = Lines(lines)
    if isinstance(expected, type):
        with pytest.raises(expected):
            read_launch_secret(stream)
    else:
        assert read_launch_secret(stream) == expected


# The real server process.


def _free_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as bound:
        port: int = bound.getsockname()[1]
        return port


@asynccontextmanager
async def started(
    tmp_path: Path, launch_secret: str | None
) -> AsyncIterator[tuple[str, list[str]]]:
    """The sample backend as a process, its address, and what it printed until
    ``ready`` and the line after it, if any."""
    port = _free_port()
    log = (tmp_path / "server.log").open("wb")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        os.fspath(PROCESS),
        str(port),
        os.fspath(tmp_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=log,
    )
    assert process.stdin is not None and process.stdout is not None
    if launch_secret is not None:
        process.stdin.write(f"{launch_secret}\n".encode())
        await process.stdin.drain()
    else:
        process.stdin.close()
    printed: list[str] = []
    try:
        async with asyncio.timeout(60):
            while "ready" not in printed:
                line = await process.stdout.readline()
                assert line, (tmp_path / "server.log").read_text()
                printed.append(line.decode().strip())
            if launch_secret is None:
                printed.append((await process.stdout.readline()).decode().strip())
        yield f"http://127.0.0.1:{port}", printed
    finally:
        if process.returncode is None:
            process.send_signal(signal.SIGTERM)
        async with asyncio.timeout(30):
            code = await process.wait()
        log.close()
        assert code == 0, (tmp_path / "server.log").read_text()


async def test_the_server_process_takes_the_launch_secret_on_standard_input(
    tmp_path: Path,
) -> None:
    secret = new_secret(CredentialKind.LAUNCH)
    async with (
        started(tmp_path, secret) as (address, printed),
        httpx.AsyncClient(base_url=address) as launcher_client,
        httpx.AsyncClient(base_url=address, headers={"origin": address}) as window,
    ):
        assert printed == ["ready"]
        asked = await launcher_client.post(
            "/auth/tickets", json={}, headers=bearer(secret)
        )
        assert asked.status_code == 201, asked.text
        await window.get(asked.json()["url"])
        session = (await window.get("/auth/session")).json()
        made = await launcher_client.post(
            "/auth/services",
            json={"name": "worker-1", "role": "notes/worker", "resource": "gpu"},
            headers=bearer(secret),
        )
        worker = await launcher_client.post(
            "/notes/queues/gpu/claims",
            json={},
            headers=bearer(made.json()["secret"]),
        )

    assert (session["mode"], session["principal"]["provider"]) == ("local", "!local")
    assert worker.json() == {"queue": "gpu", "by": "worker-1"}


async def test_a_start_by_hand_prints_the_address_with_a_ticket(
    tmp_path: Path,
) -> None:
    async with (
        started(tmp_path, None) as (address, printed),
        httpx.AsyncClient(base_url=address) as browser,
    ):
        assert printed[-2] == "ready"
        assert printed[-1].startswith(f"open {address}/auth/local?ticket=")
        opened = await browser.get(printed[-1].removeprefix("open "))
        assert opened.status_code == 303
        session = (await browser.get("/auth/session")).json()

    assert session["principal"]["provider"] == "!local"
