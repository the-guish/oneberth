# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""A component whose router includes routers, one and two levels deep.

``shop`` declares a permission on a route, and on an ``include_router`` call
for the routes under it. Its worker route sits two routers down, with its
resource in a prefix. ``compose_app`` checks every included route as a direct
one, and the gate, the worker listener and the OpenAPI document serve them so.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from oneberth.identity import Role, RoleTable
from oneberth.identity.memory import MemoryIdentityStore
from oneberth.web import (
    Asking,
    Component,
    Composition,
    CompositionError,
    compose_app,
    permit,
)
from oneberth.web.testing import (
    bearer,
    client_of,
    config_for,
    running,
    service_token,
    signed_in,
)

SHOP = RoleTable(
    app="shop",
    permissions=frozenset({"shop/items:read", "shop/orders:claim"}),
    roles=(
        Role("shop/user", frozenset({"shop/items:read"}), people=True),
        Role("shop/worker", frozenset({"shop/orders:claim"}), resource="queue"),
    ),
    default="shop/user",
)
READ = "shop/items:read"


def shop_router() -> APIRouter:
    """``/direct``; ``/items/list`` and ``/items/deep/{item}``, under a permit on
    ``include_router``; ``/work/queues/{queue}/claims``, two routers down."""
    deep = APIRouter()

    @deep.get("/{item}")
    async def item(item: str) -> dict[str, str]:
        return {"item": item}

    items = APIRouter()

    @items.get("/list")
    async def listed(principal: Asking) -> dict[str, str]:
        return {"for": principal.name}

    items.include_router(deep, prefix="/deep")

    claims = APIRouter()

    @claims.post("/claims", dependencies=[permit("shop/orders:claim", "queue")])
    async def claim(queue: str, principal: Asking) -> dict[str, str]:
        return {"queue": queue, "by": principal.name}

    work = APIRouter()
    work.include_router(claims, prefix="/queues/{queue}")

    router = APIRouter()

    @router.get("/direct", dependencies=[permit(READ)])
    async def direct() -> dict[str, str]:
        return {"direct": "yes"}

    router.include_router(items, prefix="/items", dependencies=[permit(READ)])
    router.include_router(work, prefix="/work")
    return router


@pytest.fixture
async def shop() -> AsyncIterator[tuple[Composition, httpx.AsyncClient]]:
    store = MemoryIdentityStore()
    await store.setup()
    composition = compose_app(
        [Component("shop", SHOP, shop_router())],
        config=config_for("shop"),
        store=store,
    )
    async with running(composition) as client:
        yield composition, client


async def test_a_request_reaches_an_included_route_with_its_permission_checked(
    shop: tuple[Composition, httpx.AsyncClient],
) -> None:
    composition, client = shop
    worker = bearer(await service_token(composition, "shop/worker", "gpu"))
    nobody = await client.get("/shop/items/list")
    worker_reads = await client.get("/shop/items/deep/42", headers=worker)
    claim = await client.post("/shop/work/queues/gpu/claims", json={}, headers=worker)
    other_queue = await client.post(
        "/shop/work/queues/cpu/claims", json={}, headers=worker
    )
    await signed_in(composition, client)
    listed = await client.get("/shop/items/list")
    deep = await client.get("/shop/items/deep/42")
    person_claims = await client.post("/shop/work/queues/gpu/claims", json={})

    assert nobody.status_code == 401
    assert (listed.status_code, listed.json()) == (200, {"for": "Ada Lovelace"})
    assert (deep.status_code, deep.json()) == (200, {"item": "42"})
    assert (claim.status_code, claim.json()["queue"]) == (200, "gpu")
    for refused in (worker_reads, other_queue, person_claims):
        assert (refused.status_code, refused.json()["error"]) == (403, "Forbidden")


async def test_an_included_worker_route_is_on_the_worker_listener_alone(
    shop: tuple[Composition, httpx.AsyncClient],
) -> None:
    composition, _ = shop
    token = bearer(await service_token(composition, "shop/worker", "gpu"))
    async with client_of(composition, worker=True) as worker:
        claim = await worker.post(
            "/shop/work/queues/gpu/claims", json={}, headers=token
        )
        other_queue = await worker.post(
            "/shop/work/queues/cpu/claims", json={}, headers=token
        )
        hidden = [
            await worker.get(path, headers=token)
            for path in ("/shop/direct", "/shop/items/list", "/shop/items/deep/1")
        ]

    assert (claim.status_code, claim.json()["queue"]) == (200, "gpu")
    assert other_queue.status_code == 403
    assert [(a.status_code, a.json()["error"]) for a in hidden] == [
        (404, "NotFound")
    ] * 3


async def test_the_openapi_document_lists_included_routes(
    shop: tuple[Composition, httpx.AsyncClient],
) -> None:
    _, client = shop

    document = (await client.get("/shop/openapi.json")).json()

    assert sorted(document["paths"]) == [
        "/shop/direct",
        "/shop/items/deep/{item}",
        "/shop/items/list",
        "/shop/work/queues/{queue}/claims",
    ]


# What compose_app refuses, for a route one and two routers down.


def _route(dependencies: list[Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/r/{name}", dependencies=dependencies)
    async def handler(name: str) -> None:
        return None

    return router


def _plain() -> APIRouter:
    router = _route([permit(READ)])
    router.add_route("/plain", lambda request: HTMLResponse(""))
    return router


def _nested(inner: APIRouter, depth: int, dependencies: list[Any]) -> APIRouter:
    """``inner`` included ``depth`` routers down, each with a prefix; the
    outermost ``include_router`` call carries ``dependencies``."""
    router = inner
    for level in range(depth):
        outer = APIRouter()
        outer.include_router(
            router,
            prefix=f"/level{level}",
            dependencies=dependencies if level == depth - 1 else [],
        )
        router = outer
    return router


@pytest.mark.parametrize("depth", [1, 2])
@pytest.mark.parametrize(
    ("inner", "on_include", "problem"),
    [
        (lambda: _route([]), [], "declares no permission"),
        (lambda: _route([permit("shop/items:write")]), [], "no application registered"),
        (lambda: _route([]), [permit("shop/items:write")], "no application registered"),
        (lambda: _route([permit(READ, "queue")]), [], "not a parameter of its path"),
        (lambda: _route([]), [permit(READ, "queue")], "not a parameter of its path"),
        (lambda: _route([permit(READ)]), [permit(READ)], "declares 2 permissions"),
        (_plain, [], "/plain is not a FastAPI route"),
    ],
)
def test_compose_app_refuses_an_included_route_that_does_not_hold(
    inner: Any, on_include: list[Any], problem: str, depth: int
) -> None:
    router = _nested(inner(), depth, on_include)
    with pytest.raises(CompositionError, match=problem):
        compose_app(
            [Component("shop", SHOP, router)],
            config=config_for("shop"),
            store=MemoryIdentityStore(),
        )


@pytest.mark.parametrize("depth", [1, 2])
def test_a_permit_on_include_router_with_its_resource_in_a_prefix_holds(
    depth: int,
) -> None:
    router = APIRouter()
    router.include_router(
        _nested(_route([]), depth, []),
        prefix="/queues/{queue}",
        dependencies=[permit("shop/orders:claim", "queue")],
    )

    composition = compose_app(
        [Component("shop", SHOP, router)],
        config=config_for("shop"),
        store=MemoryIdentityStore(),
    )

    assert composition.name == "shop"
