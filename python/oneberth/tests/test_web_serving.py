# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The moments of a backend's life an application uses, and the tokens of the
parts it starts itself.

``jobs`` is a sample component. While it starts, it asks its own backend and
is answered 503. Once the backend serves, it uploads to the front listener
with a token of ``jobs/ci`` and starts a worker that claims on the worker
listener with a token of ``jobs/worker``. Both tokens live in the backend's
memory. At the stop, the worker claims once more while the listeners serve.
The order runs in process first, then on uvicorn with the memory and the
PostgreSQL stores.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest
from fastapi import APIRouter

from oneberth.identity import OPERATOR, IdentityStore, Role, RoleTable
from oneberth.identity.memory import MemoryIdentityStore
from oneberth.stores import opened_store
from oneberth.web import (
    Asking,
    Component,
    Composition,
    Context,
    ServerError,
    compose_app,
    permit,
    serve,
)
from oneberth.web.testing import bearer, client_of, config_for, running

PUBLIC_URL = "http://127.0.0.1:8000"
SOME_TOKEN = "ob_svc_" + "x" * 43
SCHEMA = "oneberth_serving"

NOTES = RoleTable(
    app="notes",
    permissions=frozenset({"notes/items:read"}),
    roles=(Role("notes/user", frozenset({"notes/items:read"}), people=True),),
    default="notes/user",
)
JOBS = RoleTable(
    app="jobs",
    permissions=frozenset({"jobs/flows:upload", "jobs/tasks:claim"}),
    roles=(
        Role("jobs/worker", frozenset({"jobs/tasks:claim"}), resource="queue"),
        Role("jobs/ci", frozenset({"jobs/flows:upload"})),
    ),
)


class Sample:
    """Two components that note each moment of their lives in ``journal``.

    ``front`` and ``worker`` say how ``jobs`` reaches its own backend: in
    process by default, or at the listeners' addresses. ``jobs`` fails to
    start when ``refusing``, and to begin serving when ``failing``.
    """

    def __init__(self, *, failing: bool = False, refusing: bool = False) -> None:
        self.journal: list[str] = []
        self.tokens: list[str] = []
        self.failing = failing
        self.refusing = refusing
        self.front: Callable[[], httpx.AsyncClient] = lambda: client_of(self.app)
        self.worker: Callable[[], httpx.AsyncClient] = lambda: client_of(
            self.app, worker=True
        )
        self.app: Composition

    def compose(self, store: Any) -> Composition:
        self.app = compose_app(
            [self._notes(), self._jobs()],
            config=config_for("notes", public_url=PUBLIC_URL),
            store=store,
        )
        return self.app

    def _notes(self) -> Component:
        journal = self.journal

        @asynccontextmanager
        async def lifespan(context: Context) -> AsyncIterator[None]:
            journal.append("notes starts")
            try:
                yield
            finally:
                journal.append("notes stops")

        @asynccontextmanager
        async def serving(context: Context) -> AsyncIterator[None]:
            journal.append("notes serves")
            try:
                yield
            finally:
                journal.append("notes ends serving")

        router = APIRouter()

        @router.get("/items", dependencies=[permit("notes/items:read")])
        async def items() -> list[str]:
            return []

        return Component("notes", NOTES, router, lifespan=lifespan, serving=serving)

    def _jobs(self) -> Component:
        journal = self.journal

        @asynccontextmanager
        async def lifespan(context: Context) -> AsyncIterator[None]:
            journal.append("jobs starts")
            if self.refusing:
                raise RuntimeError("the records of jobs are not this build's")
            async with client_of(self.app) as front:
                asked = await front.post(
                    "/jobs/flows", json={}, headers=bearer(SOME_TOKEN)
                )
            journal.append(f"jobs asked while starting: {asked.status_code}")
            try:
                yield
            finally:
                journal.append("jobs stops")

        @asynccontextmanager
        async def serving(context: Context) -> AsyncIterator[None]:
            ci, _ = await context.access.create_own_token("jobs-ci", "jobs/ci")
            async with self.front() as front:
                uploaded = await front.post("/jobs/flows", json={}, headers=bearer(ci))
            journal.append(f"jobs uploaded: {uploaded.status_code}")
            if self.failing:
                raise RuntimeError("the flows are refused")
            token, _ = await context.access.create_own_token(
                "jobs-worker", "jobs/worker", resource="gpu"
            )
            self.tokens.append(token)
            async with self.worker() as worker:
                claimed = await worker.post(
                    "/jobs/queues/gpu/claims", json={}, headers=bearer(token)
                )
                journal.append(f"worker claimed: {claimed.json()}")
                journal.append("jobs serves")
                yield
                claimed = await worker.post(
                    "/jobs/queues/gpu/claims", json={}, headers=bearer(token)
                )
                journal.append(f"worker stops: {claimed.status_code}")

        router = APIRouter()

        @router.post("/flows", dependencies=[permit("jobs/flows:upload")])
        async def upload(principal: Asking) -> dict[str, str]:
            return {"by": principal.name}

        @router.post(
            "/queues/{queue}/claims", dependencies=[permit("jobs/tasks:claim", "queue")]
        )
        async def claim(queue: str, principal: Asking) -> dict[str, str]:
            return {"queue": queue, "by": principal.name}

        return Component("jobs", JOBS, router, lifespan=lifespan, serving=serving)


async def memory_store() -> MemoryIdentityStore:
    store = MemoryIdentityStore()
    await store.setup()
    return store


LIFE = [
    "notes starts",
    "jobs starts",
    "jobs asked while starting: 503",
    "notes serves",
    "jobs uploaded: 200",
    "worker claimed: {'queue': 'gpu', 'by': 'jobs-worker'}",
    "jobs serves",
]
END = [
    "worker stops: 200",
    "notes ends serving",
    "jobs stops",
    "notes stops",
]


async def test_serving_begins_once_all_started_and_ends_before_the_stop() -> None:
    sample = Sample()
    app = sample.compose(await memory_store())
    async with running(app) as client:
        assert sample.journal == LIFE
        started = await client.get("/health")
        services = await app.access.service_tokens(by=OPERATOR)
    async with client_of(app, worker=True) as worker, app.lifespan():
        ended = await worker.post(
            "/jobs/queues/gpu/claims", json={}, headers=bearer(sample.tokens[0])
        )

    assert sample.journal[len(LIFE) : len(LIFE) + len(END)] == END
    assert started.status_code == 200
    assert [token.name for token in services] == ["jobs-ci", "jobs-worker"]
    assert ended.status_code == 401


async def test_a_component_that_fails_to_begin_serving_stops_the_start() -> None:
    sample = Sample(failing=True)
    app = sample.compose(await memory_store())

    with pytest.raises(ServerError, match="jobs failed to begin serving: the flows"):
        async with running(app):
            pass

    assert sample.journal == [
        *LIFE[:5],
        "notes ends serving",
        "jobs stops",
        "notes stops",
    ]


async def test_a_component_that_fails_to_start_stops_the_start() -> None:
    sample = Sample(refusing=True)
    app = sample.compose(await memory_store())

    with pytest.raises(RuntimeError, match="the records of jobs"):
        async with running(app):
            pass

    assert sample.journal == ["notes starts", "jobs starts", "notes stops"]
    assert str(app.failure) == (
        "component jobs failed to start: the records of jobs are not this build's"
    )
    # A start that works forgets the one that failed.
    sample.refusing = False
    async with running(app):
        assert app.failure is None


async def test_the_answer_while_starting_says_where_own_requests_go() -> None:
    sample = Sample()
    app = sample.compose(await memory_store())
    async with client_of(app) as client:
        refused = await client.post("/jobs/flows", json={}, headers=bearer(SOME_TOKEN))

    assert refused.json() == {
        "error": "Unavailable",
        "detail": "the backend is starting or stopping: a component's own requests "
        "to it begin in its serving, once every component has started",
    }


# On uvicorn.


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.postgres)])
async def store_source(
    request: pytest.FixtureRequest,
) -> AsyncIterator[Callable[[], AbstractAsyncContextManager[IdentityStore]]]:
    if request.param == "memory":

        @asynccontextmanager
        async def in_memory() -> AsyncIterator[IdentityStore]:
            yield await memory_store()

        yield in_memory
        return
    url = request.getfixturevalue("database_url")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        yield lambda: opened_store(database_url=url, setup=True, schema=SCHEMA)
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    finally:
        await conn.close()


def _client_at(address: str) -> Callable[[], httpx.AsyncClient]:
    return lambda: httpx.AsyncClient(base_url=address, trust_env=False)


def _listening(sample: Sample) -> tuple[socket.socket, socket.socket]:
    """Two loopback sockets, and ``sample`` reaching its backend through them."""
    front, worker = (socket.create_server(("127.0.0.1", 0)) for _ in range(2))
    for listener, where in (("front", front), ("worker", worker)):
        address = f"http://127.0.0.1:{where.getsockname()[1]}"
        setattr(sample, listener, _client_at(address))
    return front, worker


async def test_a_served_backend_runs_both_moments_with_tokens_in_memory(
    store_source: Callable[[], AbstractAsyncContextManager[IdentityStore]],
) -> None:
    sample = Sample()
    app = sample.compose(store_source)
    front, worker = _listening(sample)
    journal_at_ready: list[str] = []
    ready, stop = asyncio.Event(), asyncio.Event()

    def said_ready() -> None:
        journal_at_ready.extend(sample.journal)
        ready.set()

    task = asyncio.create_task(
        serve(app, front, worker, ready=said_ready, log_level="warning", stop=stop)
    )
    async with asyncio.timeout(20):
        await asyncio.wait(
            {task, asyncio.create_task(ready.wait())}, return_when="FIRST_COMPLETED"
        )
    assert ready.is_set(), task.exception()
    async with sample.worker() as client:
        token, _ = await app.access.create_own_token(
            "other-worker", "jobs/worker", resource="cpu"
        )
        elsewhere = await client.post(
            "/jobs/queues/gpu/claims", json={}, headers=bearer(token)
        )
    stop.set()
    async with asyncio.timeout(20):
        await task

    assert journal_at_ready == LIFE
    assert sample.journal[len(LIFE) :] == END
    assert elsewhere.status_code == 403


async def test_a_served_backend_whose_component_fails_to_serve_never_says_ready() -> (
    None
):
    sample = Sample(failing=True)
    app = sample.compose(await memory_store())
    front, worker = _listening(sample)
    said: list[str] = []

    with pytest.raises(ServerError, match="jobs failed to begin serving"):
        async with asyncio.timeout(20):
            await serve(
                app,
                front,
                worker,
                ready=lambda: said.append("ready"),
                log_level="critical",
            )

    assert said == []
    assert sample.journal[-3:] == ["notes ends serving", "jobs stops", "notes stops"]


async def test_a_served_backend_whose_component_fails_to_start_says_which_and_why() -> (
    None
):
    sample = Sample(refusing=True)
    app = sample.compose(await memory_store())
    front, worker = _listening(sample)
    said: list[str] = []

    with pytest.raises(ServerError) as stopped:
        async with asyncio.timeout(20):
            await serve(
                app,
                front,
                worker,
                ready=lambda: said.append("ready"),
                log_level="critical",
            )

    assert str(stopped.value) == (
        "component jobs failed to start: the records of jobs are not this build's"
    )
    assert isinstance(stopped.value.__cause__, RuntimeError)
    assert said == []
    assert sample.journal == ["notes starts", "jobs starts", "notes stops"]
