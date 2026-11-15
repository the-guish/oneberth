# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""A composition of two sample components, over HTTP, in process.

``notes`` has a route of each kind the applications have: a plain answer, a
write, a long poll, a stream, a route out of the OpenAPI document, a page with
headers of its own, an error of its own. ``jobs`` has the routes of a worker,
served on the worker listener too: one that names its queue, one that acts on
the worker's own queue, and one that serves every queue. A person signs in
through the stand-in provider and uses every ``/auth`` route; the journey runs
on the memory, the SQLite and the PostgreSQL stores.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from oneberth.config import Config, ConfigError
from oneberth.identity import (
    GrantEntry,
    IdentityStore,
    Match,
    Matcher,
    Policy,
    Role,
    RoleTable,
    system_clock,
)
from oneberth.identity.memory import MemoryIdentityStore
from oneberth.identity.testing import ManualClock
from oneberth.stores import opened_store
from oneberth.web import (
    Asking,
    Component,
    Composition,
    CompositionError,
    Context,
    Device,
    ServerError,
    compose_app,
    permit,
    serve,
    while_connected,
)
from oneberth.web._server import say_ready
from oneberth.web.testing import (
    StandInProvider,
    bearer,
    client_of,
    config_for,
    read_qr,
    running,
    service_token,
    signed_in,
)

PUBLIC_URL = "http://127.0.0.1:8000"

NOTES = RoleTable(
    app="notes",
    permissions=frozenset({"notes/items:read", "notes/items:write"}),
    roles=(
        Role(
            "notes/user",
            frozenset({"notes/items:read", "notes/items:write"}),
            people=True,
        ),
        Role("notes/reader", frozenset({"notes/items:read"})),
    ),
    default="notes/user",
)
JOBS = RoleTable(
    app="jobs",
    permissions=frozenset({"jobs/tasks:claim", "jobs/status:read"}),
    roles=(
        Role("jobs/user", frozenset({"jobs/status:read"}), people=True),
        Role("jobs/worker", frozenset({"jobs/tasks:claim"}), resource="queue"),
        # A service that works on every queue: its grant names none.
        Role("jobs/dispatcher", frozenset({"jobs/tasks:claim"})),
    ),
    default="jobs/user",
)


class NoteRefusedError(Exception):
    """An application's own error."""


class Note(BaseModel):
    text: str


class Samples:
    """The two sample components, and what they saw."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.polls_ended = asyncio.Event()
        self.poll_started = asyncio.Event()
        self.notes = Component(
            "notes", NOTES, self._notes_router(), lifespan=self._life("notes"),
            errors={NoteRefusedError: 409}, title="Notes", version="1.2",
        )  # fmt: skip
        self.jobs = Component(
            "jobs", JOBS, self._jobs_router(), lifespan=self._life("jobs"),
            health=self._jobs_health, check_service_token=self._open_queue,
        )  # fmt: skip
        self.jobs_well = True

    def _life(
        self, name: str
    ) -> Callable[[Context], AbstractAsyncContextManager[None]]:
        @asynccontextmanager
        async def life(context: Context) -> AsyncIterator[None]:
            self.events.append(f"start {name} at {context.public_url}")
            yield
            self.events.append(f"stop {name}")

        return life

    async def _jobs_health(self) -> bool:
        return self.jobs_well

    async def _open_queue(self, role: str, resource: str | None) -> str | None:
        if resource == "closed":
            return "queue 'closed' takes no worker"
        return None

    def _notes_router(self) -> APIRouter:
        router = APIRouter()
        reading = permit("notes/items:read")

        @router.get("/items", dependencies=[reading])
        async def items(principal: Asking) -> dict[str, Any]:
            return {"for": principal.name, "kind": principal.kind.value}

        @router.post(
            "/items", status_code=201, dependencies=[permit("notes/items:write")]
        )
        async def write(note: Note) -> Note:
            if note.text == "refused":
                raise NoteRefusedError("that note is refused")
            return note

        @router.get("/changes", dependencies=[reading])
        async def changes(request: Request) -> dict[str, bool]:
            self.poll_started.set()
            try:
                await while_connected(request, asyncio.Event().wait())
            finally:
                self.polls_ended.set()
            return {"changed": False}

        @router.get("/events", dependencies=[reading])
        async def events() -> StreamingResponse:
            async def stream() -> AsyncIterator[str]:
                for n in range(3):
                    yield f"data: {n}\n\n"

            return StreamingResponse(stream(), media_type="text/event-stream")

        @router.get("/hidden", dependencies=[reading], include_in_schema=False)
        async def hidden() -> dict[str, str]:
            return {"hidden": "yes"}

        @router.get("/page", dependencies=[reading], include_in_schema=False)
        async def page() -> HTMLResponse:
            return HTMLResponse(
                "<p>a view</p>",
                headers={
                    "content-security-policy": "sandbox",
                    "x-frame-options": "SAMEORIGIN",
                },
            )

        @router.get("/boom", dependencies=[reading])
        async def boom() -> None:
            raise RuntimeError("a bug")

        @router.get("/phone", dependencies=[reading])
        async def phone(principal: Device) -> dict[str, str]:
            return {"device": principal.name}

        return router

    def _jobs_router(self) -> APIRouter:
        router = APIRouter()

        @router.post(
            "/queues/{queue}/claims", dependencies=[permit("jobs/tasks:claim", "queue")]
        )
        async def claim(queue: str, principal: Asking) -> dict[str, str]:
            return {"queue": queue, "by": principal.name}

        # It names no queue, and acts on the one the worker's grant names.
        @router.get("/mine", dependencies=[permit("jobs/tasks:claim", bound=True)])
        async def mine(request: Request, principal: Asking) -> dict[str, str | None]:
            access = request.app.state.oneberth.access
            return {"queue": access.bound_resource(principal, "jobs/tasks:claim")}

        # It names no queue, and serves them all.
        @router.get("/tasks", dependencies=[permit("jobs/tasks:claim")])
        async def tasks() -> dict[str, str]:
            return {"tasks": "of every queue"}

        @router.get("/status", dependencies=[permit("jobs/status:read")])
        async def status() -> dict[str, str]:
            return {"status": "fine"}

        return router


def compose(
    samples: Samples,
    store: IdentityStore | Callable[[], AbstractAsyncContextManager[IdentityStore]],
    *,
    config: Config | None = None,
    stand_in: StandInProvider | None = None,
    clock: Callable[..., Any] | None = None,
    interface: Path | None = None,
    max_body: int = 4096,
) -> Composition:
    return compose_app(
        [samples.notes, samples.jobs],
        config=config or config_for("notes", public_url=PUBLIC_URL),
        store=store,
        interface=interface,
        max_body=max_body,
        provider_transport=None if stand_in is None else stand_in.transport(),
        clock=clock or system_clock,
    )


@pytest.fixture
def samples() -> Samples:
    return Samples()


@pytest.fixture
async def memory() -> MemoryIdentityStore:
    store = MemoryIdentityStore()
    await store.setup()
    return store


@pytest.fixture
async def app(samples: Samples, memory: MemoryIdentityStore) -> AsyncIterator[Any]:
    composition = compose(samples, memory)
    async with running(composition) as client:
        yield composition, client


# The journey of a person, on each store.


@pytest.fixture(
    params=["memory", "sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]
)
async def store_source(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[Callable[[], AbstractAsyncContextManager[IdentityStore]]]:
    if request.param == "memory":

        @asynccontextmanager
        async def in_memory() -> AsyncIterator[IdentityStore]:
            store = MemoryIdentityStore()
            await store.setup()
            yield store

        yield in_memory
    elif request.param == "sqlite":
        yield lambda: opened_store(data_dir=tmp_path, setup=True)
    else:
        url = request.getfixturevalue("database_url")
        await _emptied(url)
        yield lambda: opened_store(database_url=url, setup=True)


async def _emptied(url: str) -> None:
    from oneberth.identity.postgres import SCHEMA
    from oneberth.identity.postgres._schema import TABLES

    async with opened_store(database_url=url, setup=True):
        pass
    conn = await asyncpg.connect(url)
    try:
        tables = ", ".join(f"{SCHEMA}.{t}" for t in TABLES if t != "schema_version")
        await conn.execute(f"TRUNCATE {tables}")
    finally:
        await conn.close()


async def sign_in_through(
    client: httpx.AsyncClient, stand_in: StandInProvider, return_to: str
) -> httpx.Response:
    """A browser's sign-in: to the provider and back."""
    begun = await client.get(
        f"/auth/login/{stand_in.provider_id}", params={"return_to": return_to}
    )
    assert begun.status_code == 303, begun.text
    back = await stand_in.authorize(begun.headers["location"])
    return await client.get(back)


async def test_a_person_signs_in_and_uses_every_route_of_auth(
    samples: Samples,
    store_source: Callable[[], AbstractAsyncContextManager[IdentityStore]],
) -> None:
    stand_in = StandInProvider()
    config = config_for(
        "notes",
        public_url=PUBLIC_URL,
        admins=["ada"],
        providers={"stand-in": stand_in.config},
    )
    composition = compose(samples, store_source, config=config, stand_in=stand_in)
    async with running(composition) as client:
        # Nobody yet, and the providers to sign in with.
        nobody = (await client.get("/auth/session")).json()
        assert nobody == {
            "mode": "providers",
            "providers": [{"id": "stand-in", "title": "Stand-in"}],
            "principal": None,
            "roles": [],
            "pairing": None,
        }
        assert (await client.get("/notes/items")).status_code == 401

        # The sign-in, back where the person was.
        landed = await sign_in_through(client, stand_in, "/ui/#/notes/3")
        assert landed.status_code == 303
        assert landed.headers["location"] == f"{PUBLIC_URL}/ui/#/notes/3"
        cookie = landed.headers["set-cookie"]
        assert "oneberth_session_8000=ob_ses_" in cookie
        assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
        session = (await client.get("/auth/session")).json()
        assert session["principal"]["name"] == "Ada Lovelace"
        assert session["principal"]["kind"] == "user"
        assert session["roles"] == ["jobs/user", "notes/user", "oneberth/admin"]
        assert (await client.get("/notes/items")).json() == {
            "for": "Ada Lovelace",
            "kind": "session",
        }
        assert (
            await client.post("/notes/items", json={"text": "hi"})
        ).status_code == 201

        # A personal token, minted from the fresh session, works as a bearer.
        minted = await client.post("/auth/tokens", json={"name": "laptop"})
        assert minted.status_code == 201
        token = minted.json()
        assert token["secret"].startswith("ob_pat_")
        listed = (await client.get("/auth/tokens")).json()["items"]
        assert [t["name"] for t in listed] == ["laptop"] and "secret" not in listed[0]
        script = client_of(composition)
        async with script:
            as_token = await script.get("/notes/items", headers=bearer(token["secret"]))
            assert as_token.json()["kind"] == "personal_token"
            refused = await script.post(
                "/auth/tokens", json={"name": "x"}, headers=bearer(token["secret"])
            )
            assert (refused.status_code, refused.json()["error"]) == (
                403,
                "BearerRefused",
            )

            # A phone is linked: the QR, the claim, the number, the device.
            pairing = (await client.post("/auth/pairings", json={})).json()
            link = read_qr(pairing["qr_svg"])
            assert link.startswith(f"{PUBLIC_URL}/#/link?v=1&c=")
            code = parse_qs(urlsplit(link).fragment.partition("?")[2])["c"][0]
            claimed = await script.post(
                "/auth/pairings/claim",
                json={"code": code, "device": {"name": "Pixel", "platform": "android"}},
            )
            phone = claimed.json()
            waiting = (
                await script.get("/auth/session", headers=bearer(phone["secret"]))
            ).json()
            assert waiting["principal"] is None and waiting["pairing"] == {
                "state": "claimed"
            }
            seen = (await client.get(f"/auth/pairings/{pairing['id']}")).json()
            assert seen["state"] == "claimed" and seen["device"]["name"] == "Pixel"
            wrong = "000000" if phone["number"] != "000000" else "111111"
            missed = await client.post(
                f"/auth/pairings/{pairing['id']}/approve", json={"number": wrong}
            )
            assert (missed.status_code, missed.json()["error"]) == (403, "WrongNumber")
            device = (
                await client.post(
                    f"/auth/pairings/{pairing['id']}/approve",
                    json={"number": phone["number"]},
                )
            ).json()
            assert device["name"] == "Pixel" and device["platform"] == "android"
            as_phone = await script.get("/notes/phone", headers=bearer(phone["secret"]))
            assert as_phone.json() == {"device": "Ada Lovelace"}
            not_phone = await client.get("/notes/phone")
            assert not_phone.status_code == 403
            assert [
                d["id"] for d in (await client.get("/auth/devices")).json()["items"]
            ] == [device["id"]]

            # Service tokens, by an admin: a worker bound to one queue.
            roles = (await client.get("/auth/services/roles")).json()["items"]
            assert roles == [
                {"name": "notes/reader", "needs_resource": False},
                {"name": "jobs/worker", "needs_resource": True},
                {"name": "jobs/dispatcher", "needs_resource": False},
            ]
            made = await client.post(
                "/auth/services",
                json={
                    "name": "w1",
                    "role": "jobs/worker",
                    "resource": "gpu",
                    "days": 7,
                },
            )
            assert made.status_code == 201
            worker_token = made.json()
            assert (worker_token["role"], worker_token["resource"]) == (
                "jobs/worker",
                "gpu",
            )
            worker = client_of(composition, worker=True)
            async with worker:
                claimed_task = await worker.post(
                    "/jobs/queues/gpu/claims",
                    json={},
                    headers=bearer(worker_token["secret"]),
                )
                assert claimed_task.json() == {"queue": "gpu", "by": "w1"}
                other = await worker.post(
                    "/jobs/queues/cpu/claims",
                    json={},
                    headers=bearer(worker_token["secret"]),
                )
                assert other.status_code == 403
                mine = await worker.get(
                    "/jobs/mine", headers=bearer(worker_token["secret"])
                )
                assert mine.json() == {"queue": "gpu"}
            services = (await client.get("/auth/services")).json()["items"]
            assert [s["name"] for s in services] == ["w1"]
            assert (
                await client.delete(f"/auth/services/{worker_token['id']}")
            ).status_code == 204
            gone = await script.get(
                "/jobs/mine", headers=bearer(worker_token["secret"])
            )
            assert gone.status_code == 401

            # Taking things away.
            assert (
                await client.delete(f"/auth/devices/{device['id']}")
            ).status_code == 204
            assert (
                await script.get("/notes/items", headers=bearer(phone["secret"]))
            ).status_code == 401
            assert (
                await client.delete(f"/auth/tokens/{token['id']}")
            ).status_code == 204
            assert (
                await script.get("/notes/items", headers=bearer(token["secret"]))
            ).status_code == 401

        # Sign-out ends the session and clears the cookie.
        out = await client.post("/auth/logout", json={})
        assert out.status_code == 204
        assert 'oneberth_session_8000=""' in out.headers["set-cookie"]
        assert (await client.get("/notes/items")).status_code == 401
        assert (await client.post("/auth/logout", json={})).status_code == 401


# Signing in, and what goes wrong.


async def test_a_failed_sign_in_returns_to_the_sign_in_page_with_a_code(
    samples: Samples, memory: MemoryIdentityStore
) -> None:
    stand_in = StandInProvider()
    config = config_for(
        "notes", public_url=PUBLIC_URL, providers={"stand-in": stand_in.config}
    )
    composition = compose(samples, memory, config=config, stand_in=stand_in)
    page = f"{PUBLIC_URL}/ui/#/sign-in?error="
    async with running(composition) as client:
        unknown = await client.get("/auth/login/okta")
        assert unknown.headers["location"] == page + "unknown_provider"

        begun = await client.get(
            "/auth/login/stand-in", params={"return_to": "https://evil.example"}
        )
        back = await stand_in.authorize(begun.headers["location"])
        client.cookies.clear()  # another browser brings the callback
        stolen = await client.get(back)
        assert stolen.headers["location"] == page + "state_mismatch"

        landed = await sign_in_through(client, stand_in, "//evil.example/x")
        assert landed.headers["location"] == f"{PUBLIC_URL}/ui/"

        begun = await client.get("/auth/login/stand-in")
        back = await stand_in.authorize(begun.headers["location"])
        await client.get(back)
        state = parse_qs(urlsplit(back).query)["state"][0]
        client.cookies.set(composition.cookies.login, state)  # the callback, replayed
        again = await client.get(back)
        assert again.headers["location"] == page + "expired"


async def test_a_person_no_allow_entry_admits_is_not_signed_in(
    samples: Samples, memory: MemoryIdentityStore
) -> None:
    stand_in = StandInProvider()
    config = Config(
        apps=config_for("notes", public_url=PUBLIC_URL).apps,
        providers={"stand-in": stand_in.config},
        policy=Policy(allow=(Match("stand-in", Matcher.EMAIL, "bob@example.com"),)),
    )
    composition = compose(samples, memory, config=config, stand_in=stand_in)
    async with running(composition) as client:
        refused = await sign_in_through(client, stand_in, "/ui/")
        assert refused.headers["location"].endswith("#/sign-in?error=not_allowed")
        assert "oneberth_session" not in refused.headers.get("set-cookie", "")


async def test_a_credential_is_minted_from_a_session_younger_than_ten_minutes(
    samples: Samples, memory: MemoryIdentityStore
) -> None:
    clock = ManualClock()
    composition = compose(samples, memory, clock=clock)
    async with running(composition) as client:
        await signed_in(composition, client)
        clock.advance(timedelta(minutes=10))
        for path, body in (("/auth/tokens", {"name": "t"}), ("/auth/pairings", {})):
            stale = await client.post(path, json=body)
            assert (stale.status_code, stale.json()["error"]) == (
                403,
                "FreshSignInRequired",
            )
        assert (await client.get("/auth/tokens")).json() == {"items": []}


async def test_a_bearer_of_an_admin_creates_and_revokes_no_service_token(
    samples: Samples, memory: MemoryIdentityStore
) -> None:
    config = config_for("notes", public_url=PUBLIC_URL, admins=["ada"])
    composition = compose(samples, memory, config=config)
    new = {"name": "stolen", "role": "notes/reader"}
    async with running(composition) as client, client_of(composition) as script:
        session = await signed_in(composition, client)
        personal = (await client.post("/auth/tokens", json={"name": "t"})).json()
        kept = (
            await client.post("/auth/services", json={**new, "name": "kept"})
        ).json()
        # The admin's personal token, and the session as a backend forwards it.
        for secret in (personal["secret"], session):
            sent = bearer(secret)
            made = await script.post("/auth/services", json=new, headers=sent)
            revoked = await script.delete(f"/auth/services/{kept['id']}", headers=sent)
            listed = await script.get("/auth/services", headers=sent)
            for refused in (made, revoked):
                assert (refused.status_code, refused.json()["error"]) == (
                    403,
                    "BearerRefused",
                ), refused.text
            assert [s["name"] for s in listed.json()["items"]] == ["kept"]
        # The browser's session still revokes it.
        gone = await client.delete(f"/auth/services/{kept['id']}")

    assert gone.status_code == 204


async def test_a_service_token_is_created_from_a_session_younger_than_ten_minutes(
    samples: Samples, memory: MemoryIdentityStore
) -> None:
    clock = ManualClock()
    config = config_for("notes", public_url=PUBLIC_URL, admins=["ada"])
    composition = compose(samples, memory, config=config, clock=clock)
    async with running(composition) as client:
        await signed_in(composition, client)
        made = await client.post(
            "/auth/services", json={"name": "ci", "role": "notes/reader"}
        )
        clock.advance(timedelta(minutes=10))
        stale = await client.post(
            "/auth/services", json={"name": "late", "role": "notes/reader"}
        )
        # Taking access away needs no fresh sign-in.
        revoked = await client.delete(f"/auth/services/{made.json()['id']}")

    assert made.status_code == 201, made.text
    assert (stale.status_code, stale.json()["error"]) == (403, "FreshSignInRequired")
    assert revoked.status_code == 204


async def test_a_secure_origin_sets_the_host_prefixed_cookie(
    samples: Samples, memory: MemoryIdentityStore
) -> None:
    stand_in = StandInProvider()
    url = "https://notes.example.com"
    config = config_for(
        "notes", public_url=url, providers={"stand-in": stand_in.config}
    )
    composition = compose(samples, memory, config=config, stand_in=stand_in)
    async with running(composition) as client:
        landed = await sign_in_through(client, stand_in, "/ui/")
        (cookie,) = [
            c for c in landed.headers.get_list("set-cookie") if "_session=" in c
        ]
        assert cookie.startswith("__Host-oneberth_session=ob_ses_")
        assert "Secure" in cookie and "Path=/" in cookie
        assert (await client.get("/notes/items")).status_code == 200


# The checks on a request, before the handler.


@pytest.mark.parametrize(
    ("method", "path", "headers", "body", "status", "error"),
    [
        (
            "GET",
            "/notes/items",
            {"authorization": "Bearer ob_pat_x"},
            None,
            400,
            "TwoCredentials",
        ),
        (
            "POST",
            "/notes/items",
            {"sec-fetch-site": "cross-site"},
            b'{"text": "a"}',
            403,
            "CrossSite",
        ),
        (
            "POST",
            "/notes/items",
            {"sec-fetch-site": "same-site"},
            b'{"text": "a"}',
            403,
            "CrossSite",
        ),
        (
            "POST",
            "/notes/items",
            {"content-type": "text/plain"},
            b'{"text": "a"}',
            415,
            "UnsupportedMediaType",
        ),
        (
            "POST",
            "/notes/items",
            {"content-type": "application/x-www-form-urlencoded"},
            b"text=a",
            415,
            "UnsupportedMediaType",
        ),
        (
            "POST",
            "/notes/items",
            {"origin": "https://evil.example"},
            b'{"text": "a"}',
            403,
            "CrossOrigin",
        ),
        ("POST", "/notes/items", {"origin": ""}, b'{"text": "a"}', 403, "CrossOrigin"),
        ("POST", "/notes/items", {}, b"{" + b" " * 5000 + b"}", 413, "PayloadTooLarge"),
        ("POST", "/notes/items", {}, b'{"text": 1}', 422, "InvalidRequest"),
        ("POST", "/notes/items", {}, b'{"text": "refused"}', 409, "NoteRefusedError"),
        ("GET", "/notes/boom", {}, None, 500, "InternalError"),
        ("GET", "/notes/nothing", {}, None, 404, "NotFound"),
        ("DELETE", "/notes/items", {}, None, 405, "MethodNotAllowed"),
        ("GET", "/jobs/mine", {}, None, 403, "Forbidden"),
    ],
)
async def test_a_request_from_a_browser_is_checked(
    app: tuple[Composition, httpx.AsyncClient],
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes | None,
    status: int,
    error: str,
) -> None:
    composition, client = app
    await signed_in(composition, client)
    sent = (
        {"content-type": "application/json", **headers} if body is not None else headers
    )

    answer = await client.request(method, path, content=body, headers=sent)

    assert (answer.status_code, answer.json()["error"]) == (status, error), answer.text
    assert answer.json()["detail"]
    assert answer.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    ("method", "path", "headers", "status", "error"),
    [
        ("GET", "/notes/items", {}, 401, "Unauthorized"),
        (
            "GET",
            "/notes/items",
            {"authorization": "Bearer ob_pat_unknown"},
            401,
            "Unauthorized",
        ),
        (
            "GET",
            "/notes/items",
            {"authorization": "Bearer something"},
            401,
            "Unauthorized",
        ),
        (
            "GET",
            "/notes/items",
            {"cookie": "oneberth_session_8000=ob_pat_x"},
            401,
            "Unauthorized",
        ),
        ("GET", "/auth/tokens", {}, 401, "Unauthorized"),
        (
            "POST",
            "/jobs/queues/gpu/claims",
            {"authorization": "reader"},
            403,
            "Forbidden",
        ),
        ("GET", "/auth/tokens", {"authorization": "reader"}, 403, "Forbidden"),
        ("GET", "/auth/services", {"authorization": "reader"}, 403, "Forbidden"),
        ("GET", "/auth/services/roles", {"authorization": "reader"}, 403, "Forbidden"),
    ],
)
async def test_who_is_asking_is_found_before_the_handler(
    app: tuple[Composition, httpx.AsyncClient],
    method: str,
    path: str,
    headers: dict[str, str],
    status: int,
    error: str,
) -> None:
    composition, client = app
    if headers.get("authorization") == "reader":
        headers = bearer(await service_token(composition, "notes/reader"))

    answer = await client.request(
        method,
        path,
        headers={"content-type": "application/json", **headers},
        content=b"{}",
    )

    assert (answer.status_code, answer.json()["error"]) == (status, error), answer.text
    if status == 401:
        assert answer.headers["www-authenticate"] == "Bearer"


async def test_a_body_over_the_limit_is_refused_while_it_is_read(
    app: tuple[Composition, httpx.AsyncClient],
) -> None:
    composition, client = app
    await signed_in(composition, client)

    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"text": "'
        yield b"a" * 5000
        yield b'"}'

    answer = await client.post(
        "/notes/items", content=chunks(), headers={"content-type": "application/json"}
    )

    assert (answer.status_code, answer.json()["error"]) == (413, "PayloadTooLarge")


async def test_a_write_with_a_bearer_needs_no_origin(
    app: tuple[Composition, httpx.AsyncClient],
) -> None:
    composition, client = app
    token = await service_token(composition, "jobs/worker", "gpu")

    answer = await client.post(
        "/jobs/queues/gpu/claims",
        json={},
        headers={**bearer(token), "origin": "https://anywhere.example"},
    )

    assert answer.status_code == 200


async def test_a_delete_without_a_body_needs_no_content_type(
    app: tuple[Composition, httpx.AsyncClient],
) -> None:
    composition, client = app
    await signed_in(composition, client)
    token = (await client.post("/auth/tokens", json={"name": "t"})).json()

    assert (await client.delete(f"/auth/tokens/{token['id']}")).status_code == 204


async def test_a_service_token_refused_by_its_application_or_its_role_is_not_created(
    samples: Samples, memory: MemoryIdentityStore
) -> None:
    config = config_for("notes", public_url=PUBLIC_URL, admins=["ada"])
    composition = compose(samples, memory, config=config)
    async with running(composition) as client:
        await signed_in(composition, client)
        closed = await client.post(
            "/auth/services",
            json={"name": "w1", "role": "jobs/worker", "resource": "closed"},
        )
        person = await client.post(
            "/auth/services", json={"name": "w2", "role": "notes/user"}
        )
        listed = (await client.get("/auth/services")).json()["items"]

    assert (closed.status_code, closed.json()) == (
        422,
        {"error": "InvalidValue", "detail": "queue 'closed' takes no worker"},
    )
    assert (person.status_code, person.json()["error"]) == (422, "InvalidValue")
    assert "a role for people" in person.json()["detail"]
    assert listed == []


# The security headers, the interface, the documents and the health.


async def test_every_answer_carries_the_security_headers_unless_its_route_sets_them(
    samples: Samples, memory: MemoryIdentityStore, tmp_path: Path
) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>ui</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-1a2b.js").write_text("console.log(1)")
    composition = compose(samples, memory, interface=tmp_path)
    async with running(composition) as client:
        await signed_in(composition, client)
        api = await client.get("/notes/items")
        page = await client.get("/notes/page")
        index = await client.get("/ui/")
        asset = await client.get("/ui/assets/app-1a2b.js")
        missing = await client.get("/ui/assets/gone.js")
        root = await client.get("/")

    for answer in (api, index, asset, missing):
        assert answer.headers["content-security-policy"].startswith(
            "default-src 'none'"
        )
        assert answer.headers["x-frame-options"] == "DENY"
        assert answer.headers["referrer-policy"] == "same-origin"
    assert api.headers["cache-control"] == "no-store"
    assert (
        page.headers["content-security-policy"],
        page.headers["x-frame-options"],
    ) == (
        "sandbox",
        "SAMEORIGIN",
    )
    assert (
        index.text.startswith("<!doctype html>")
        and index.headers["cache-control"] == "no-cache"
    )
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert (missing.status_code, missing.headers["cache-control"]) == (404, "no-cache")
    assert (root.status_code, root.headers["location"]) == (307, "/ui/")


async def test_one_openapi_document_per_component(
    app: tuple[Composition, httpx.AsyncClient],
) -> None:
    _, client = app

    notes = (await client.get("/notes/openapi.json")).json()
    jobs = (await client.get("/jobs/openapi.json")).json()
    auth = (await client.get("/auth/openapi.json")).json()

    assert (notes["info"]["title"], notes["info"]["version"]) == ("Notes", "1.2")
    assert sorted(notes["paths"]) == [
        "/notes/boom",
        "/notes/changes",
        "/notes/events",
        "/notes/items",
        "/notes/phone",
    ]
    assert sorted(jobs["paths"]) == [
        "/jobs/mine",
        "/jobs/queues/{queue}/claims",
        "/jobs/status",
        "/jobs/tasks",
    ]
    assert (
        "/auth/tokens" in auth["paths"]
        and "/auth/login/{provider}" not in auth["paths"]
    )
    refusal = notes["paths"]["/notes/items"]["get"]["responses"]["default"]
    assert refusal["content"]["application/json"]["schema"]["$ref"].endswith(
        "ErrorBody"
    )


async def test_the_components_start_in_order_and_stop_in_reverse(
    samples: Samples, memory: MemoryIdentityStore
) -> None:
    composition = compose(samples, memory)
    async with client_of(composition) as client:
        starting = await client.get("/health")
        async with composition.lifespan():
            well = await client.get("/health")
            samples.jobs_well = False
            failing = await client.get("/health")
        stopped = await client.get("/notes/items", headers=bearer("ob_pat_x"))
        assert (stopped.status_code, stopped.json()["error"]) == (503, "Unavailable")

    assert samples.events == [
        f"start notes at {PUBLIC_URL}",
        f"start jobs at {PUBLIC_URL}",
        "stop jobs",
        "stop notes",
    ]
    assert (starting.status_code, starting.json()["status"]) == (503, "starting")
    assert (well.status_code, well.json()) == (
        200,
        {"status": "ok", "components": {"jobs": "ok"}},
    )
    assert (failing.status_code, failing.json()["components"]) == (
        503,
        {"jobs": "failing"},
    )


async def test_the_worker_listener_serves_the_routes_of_worker_roles_alone(
    app: tuple[Composition, httpx.AsyncClient],
) -> None:
    composition, _ = app
    token = await service_token(composition, "jobs/worker", "gpu")
    async with client_of(composition, worker=True) as worker:
        claim = await worker.post(
            "/jobs/queues/gpu/claims", json={}, headers=bearer(token)
        )
        status = await worker.get("/jobs/status", headers=bearer(token))
        notes = await worker.get("/notes/items", headers=bearer(token))
        auth = await worker.get("/auth/session")
        health = await worker.get("/health")

    assert claim.status_code == 200
    assert [a.status_code for a in (status, notes, auth)] == [404, 404, 404]
    assert health.json()["status"] == "ok"


@pytest.mark.parametrize("on_worker_listener", [True, False])
async def test_a_worker_of_one_queue_is_refused_a_route_that_serves_every_queue(
    app: tuple[Composition, httpx.AsyncClient], on_worker_listener: bool
) -> None:
    composition, _ = app
    worker = bearer(await service_token(composition, "jobs/worker", "gpu"))
    dispatcher = bearer(await service_token(composition, "jobs/dispatcher"))
    async with client_of(composition, worker=on_worker_listener) as client:
        every = await client.get("/jobs/tasks", headers=worker)
        mine = await client.get("/jobs/mine", headers=worker)
        named = await client.post("/jobs/queues/gpu/claims", json={}, headers=worker)
        every_queue = await client.get("/jobs/tasks", headers=dispatcher)
        no_one_queue = await client.get("/jobs/mine", headers=dispatcher)

    # The worker's grant holds on its queue alone: where a path names it, and
    # where the route says it acts on the grant's own queue.
    assert (every.status_code, every.json()["error"]) == (403, "Forbidden")
    assert (mine.status_code, mine.json()) == (200, {"queue": "gpu"})
    assert named.status_code == 200
    # A grant for every queue passes both, and is confined to none.
    assert every_queue.json() == {"tasks": "of every queue"}
    assert no_one_queue.json() == {"queue": None}


def test_a_route_takes_its_resource_from_its_path_or_from_the_grant() -> None:
    with pytest.raises(ValueError, match="not from both"):
        permit("jobs/tasks:claim", "queue", bound=True)


# What compose_app refuses.


def _router(*routes: tuple[str, Any]) -> APIRouter:
    router = APIRouter()
    for path, dependencies in routes:

        async def handler() -> None:
            return None

        router.add_api_route(path, handler, dependencies=dependencies)
    return router


def _with_mount() -> APIRouter:
    router = _router(("/a", [permit("notes/items:read")]))
    router.add_route("/plain", lambda request: HTMLResponse(""))
    return router


@pytest.mark.parametrize(
    ("components", "problem"),
    [
        ([], "at least one component"),
        ([Component("notes", NOTES, _router(("/a", [])))], "declares no permission"),
        (
            [
                Component(
                    "notes", NOTES, _router(("/a", [permit("notes/items:delete")]))
                )
            ],
            "which no application registered",
        ),
        (
            [
                Component(
                    "notes",
                    NOTES,
                    _router(("/a", [permit("jobs/tasks:claim", "queue")])),
                )
            ],
            "which no application registered",
        ),
        (
            [
                Component(
                    "notes",
                    NOTES,
                    _router(("/a", [permit("notes/items:read", "queue")])),
                )
            ],
            "is not a parameter of its path",
        ),
        (
            [
                Component(
                    "notes",
                    NOTES,
                    _router(
                        (
                            "/a",
                            [permit("notes/items:read"), permit("notes/items:write")],
                        )
                    ),
                )
            ],
            "declares 2 permissions",
        ),
        ([Component("notes", NOTES, _with_mount())], "is not a FastAPI route"),
        ([Component("notes", JOBS, APIRouter())], "declares the roles of 'jobs'"),
        (
            [
                Component("notes", NOTES, APIRouter()),
                Component("notes", NOTES, APIRouter()),
            ],
            "two components are named 'notes'",
        ),
        (
            [Component("auth", RoleTable("auth", frozenset(), ()), APIRouter())],
            "cannot name a component",
        ),
    ],
)
def test_compose_app_refuses_components_that_do_not_hold(
    components: list[Component], problem: str, memory: MemoryIdentityStore
) -> None:
    with pytest.raises(CompositionError, match=problem):
        compose_app(components, config=config_for("notes", "auth"), store=memory)


@pytest.mark.parametrize(
    ("config", "problem"),
    [
        (config_for("other"), "apps.notes: missing"),
        (
            Config(
                apps=config_for("notes").apps,
                policy=Policy(
                    allow=(Match("test", Matcher.EVERYONE),),
                    grants=(
                        GrantEntry(
                            Match("test", Matcher.EVERYONE), frozenset({"jobs/admin"})
                        ),
                    ),
                ),
            ),
            "jobs/admin",
        ),
    ],
)
def test_compose_app_refuses_a_configuration_that_does_not_fit(
    samples: Samples, memory: MemoryIdentityStore, config: Config, problem: str
) -> None:
    with pytest.raises(ConfigError, match=problem):
        compose(samples, memory, config=config)


async def test_a_store_of_another_version_stops_the_start(samples: Samples) -> None:
    from oneberth.identity import SchemaVersionError

    composition = compose(samples, MemoryIdentityStore())  # never set up
    with pytest.raises(SchemaVersionError):
        async with composition.lifespan():
            pass


# The server, on real sockets.


@asynccontextmanager
async def served(
    composition: Composition, *, worker: bool = False
) -> AsyncIterator[tuple[str, str | None]]:
    """``composition`` on uvicorn, on loopback ports of its own, for the block."""
    sockets = [socket.create_server(("127.0.0.1", 0)) for _ in range(1 + worker)]
    addresses = [f"http://127.0.0.1:{s.getsockname()[1]}" for s in sockets]
    ready = asyncio.Event()
    stop = asyncio.Event()
    task = asyncio.create_task(
        serve(
            composition,
            sockets[0],
            sockets[1] if worker else None,
            ready=ready.set,
            log_level="warning",
            grace_seconds=2,
            stop=stop,
        )
    )
    async with asyncio.timeout(20):
        await asyncio.wait(
            {task, asyncio.create_task(ready.wait())}, return_when="FIRST_COMPLETED"
        )
    assert ready.is_set(), task.exception()
    try:
        yield addresses[0], addresses[1] if worker else None
    finally:
        stop.set()
        async with asyncio.timeout(20):
            await task


async def test_a_long_poll_ends_when_the_client_leaves(
    samples: Samples, memory: MemoryIdentityStore
) -> None:
    composition = compose(samples, memory)
    async with served(composition) as (front, _):
        token = await service_token(composition, "notes/reader")
        async with httpx.AsyncClient(base_url=front, headers=bearer(token)) as client:
            poll = asyncio.create_task(client.get("/notes/changes"))
            async with asyncio.timeout(10):
                await samples.poll_started.wait()
            poll.cancel()  # the client leaves
            async with asyncio.timeout(10):
                await samples.polls_ended.wait()


async def test_a_stream_of_events_reaches_the_client(
    samples: Samples, memory: MemoryIdentityStore
) -> None:
    composition = compose(samples, memory)
    async with served(composition) as (front, _):
        token = await service_token(composition, "notes/reader")
        async with (
            httpx.AsyncClient(base_url=front, headers=bearer(token)) as client,
            client.stream("GET", "/notes/events") as stream,
        ):
            lines = [line async for line in stream.aiter_lines() if line]

    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["x-content-type-options"] == "nosniff"
    assert lines == ["data: 0", "data: 1", "data: 2"]


async def test_the_server_serves_both_listeners_and_says_ready(
    samples: Samples, memory: MemoryIdentityStore, capsys: pytest.CaptureFixture[str]
) -> None:
    composition = compose(samples, memory)
    front_socket = socket.create_server(("127.0.0.1", 0))
    worker_socket = socket.create_server(("127.0.0.1", 0))
    front = f"http://127.0.0.1:{front_socket.getsockname()[1]}"
    worker = f"http://127.0.0.1:{worker_socket.getsockname()[1]}"
    stop, accepting = asyncio.Event(), asyncio.Event()

    def ready() -> None:
        say_ready()
        accepting.set()

    task = asyncio.create_task(
        serve(
            composition,
            front_socket,
            worker_socket,
            ready=ready,
            log_level="warning",
            stop=stop,
        )
    )
    async with asyncio.timeout(20):
        await accepting.wait()
    assert capsys.readouterr().out == "ready\n"
    token = await service_token(composition, "jobs/worker", "gpu")
    async with httpx.AsyncClient(headers=bearer(token)) as client:
        on_worker = await client.post(f"{worker}/jobs/queues/gpu/claims", json={})
        on_front = await client.post(f"{front}/jobs/queues/gpu/claims", json={})
        not_on_worker = await client.get(f"{worker}/jobs/status")
    stop.set()
    async with asyncio.timeout(20):
        await task

    assert (on_worker.status_code, on_front.status_code, not_on_worker.status_code) == (
        200,
        200,
        404,
    )
    assert samples.events[-2:] == ["stop jobs", "stop notes"]


async def test_a_backend_that_cannot_start_does_not_say_ready(samples: Samples) -> None:
    composition = compose(samples, MemoryIdentityStore())  # never set up
    said: list[str] = []

    with pytest.raises(ServerError, match="front listener did not start"):
        await serve(
            composition,
            socket.create_server(("127.0.0.1", 0)),
            ready=lambda: said.append("ready"),
            log_level="critical",
        )
    assert said == []
