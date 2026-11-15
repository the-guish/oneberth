# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""What an application gives oneberth, and the two dependencies of its routes.

An application writes its routes on a FastAPI ``APIRouter``. Each route
declares the permission it needs with ``permit``, and takes the principal with
``Asking``, or with ``Browsing``, ``FreshBrowsing`` or ``Device`` when it needs
that kind of credential::

    router = APIRouter()

    @router.post("/queues/{queue}/claims", dependencies=[permit(CLAIM, "queue")])
    async def claim(queue: str, principal: Asking) -> Claimed: ...

A router may include routers, to any depth. A ``permit`` on an
``include_router`` call declares the permission of every route under it, and a
route declares one permit in all::

    router.include_router(runs, prefix="/runs", dependencies=[permit(READ)])

``compose_app`` serves the router under ``/<name>/``. Before the handler runs,
and before its body is read, the gate finds who is asking and checks the
permission on the resource that the path parameter names.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Request
from fastapi.dependencies.models import Dependant

from oneberth.config import Config
from oneberth.identity import Access, Principal, RoleTable
from oneberth.web._backend import backend_of
from oneberth.web._errors import ErrorBodyOf, default_error_body

T = TypeVar("T")

PERMIT_MARK = "__oneberth_permit__"
"""Where a ``permit`` dependency says what it asks for."""


@dataclass(frozen=True, slots=True)
class Context:
    """What a component's start is given: the running backend's parts."""

    access: Access
    config: Config
    public_url: str


Lifespan = Callable[[Context], AbstractAsyncContextManager[None]]
"""What a component starts and stops: entered when the backend starts."""

Health = Callable[[], Awaitable[bool]]
"""Whether a component is well, for ``/health``."""


@dataclass(frozen=True)
class Component:
    """What an application gives oneberth to compose."""

    name: str
    """Its name, the first segment of its addresses: ``/<name>/…``."""
    roles: RoleTable
    """Its permissions and roles; ``roles.app`` is ``name``."""
    router: APIRouter
    """Its routes, each with a ``permit``."""
    lifespan: Lifespan | None = None
    """What it starts and stops with the backend, such as its stores."""
    health: Health | None = None
    errors: Mapping[type[Exception], int] = field(default_factory=dict)
    """The status each of its errors answers with. A subclass takes its
    nearest base's."""
    error_body: ErrorBodyOf = default_error_body
    """The body of one of its errors: ``{"error": …, "detail": …}`` and, if it
    wants, more keys."""
    title: str | None = None
    """The title of its OpenAPI document; its name by default."""
    version: str = "0"


@dataclass(frozen=True, slots=True)
class Permit:
    """What a route declares: the permission it needs, and the path parameter
    that names the resource the permission applies to."""

    permission: str
    resource: str | None = None


async def asking(request: Request) -> Principal:
    """The principal behind the request; a 401 for nobody."""
    return await backend_of(request).principal(request)


Asking = Annotated[Principal, Depends(asking)]
"""The principal, injected into a handler: a user through any credential, or a
service."""


async def browsing(request: Request, principal: Asking) -> Principal:
    """The principal of a browser session; a 403 for a bearer."""
    backend_of(request).access.require_browser(principal)
    return principal


async def browsing_fresh(request: Request, principal: Asking) -> Principal:
    """The principal of a browser session younger than ten minutes."""
    backend_of(request).access.require_browser(principal, fresh=True)
    return principal


async def device(request: Request, principal: Asking) -> Principal:
    """The principal of a linked phone; a 403 for anyone else."""
    backend_of(request).access.require_device(principal)
    return principal


Browsing = Annotated[Principal, Depends(browsing)]
FreshBrowsing = Annotated[Principal, Depends(browsing_fresh)]
Device = Annotated[Principal, Depends(device)]


def permit(permission: str, resource: str | None = None) -> Any:
    """A dependency that declares the permission a route needs.

    ``resource`` names the path parameter that holds the resource, such as
    ``"queue"`` for ``/queues/{queue}/…``. Its value is the principal. The gate
    has checked the permission before the handler runs; this checks it again,
    so the route holds outside a composition too.
    """
    declared = Permit(permission, resource)

    async def permitted(request: Request, principal: Asking) -> Principal:
        value = request.path_params.get(resource) if resource is not None else None
        backend_of(request).access.authorize(principal, permission, value)
        return principal

    setattr(permitted, PERMIT_MARK, declared)
    return Depends(permitted)


def permits_of(dependant: Dependant) -> tuple[list[Permit], bool]:
    """The ``permit`` declarations in a route's dependencies, and whether the
    route needs a principal at all."""
    permits: list[Permit] = []
    signed_in = False
    stack = [dependant]
    while stack:
        current = stack.pop()
        declared = getattr(current.call, PERMIT_MARK, None)
        if isinstance(declared, Permit):
            permits.append(declared)
        if current.call is asking:
            signed_in = True
        stack.extend(current.dependencies)
    return permits, signed_in or bool(permits)


async def while_connected(request: Request, work: Awaitable[T]) -> T | None:
    """``work``'s result, or ``None`` once the client has left.

    A long poll waits on this: when the client goes, ``work`` is cancelled and
    the handler ends.
    """
    task = asyncio.ensure_future(work)

    async def gone() -> None:
        while (await request.receive())["type"] != "http.disconnect":
            pass

    watcher = asyncio.ensure_future(gone())
    try:
        await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for pending in (task, watcher):
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending
    if task.cancelled():
        return None
    return task.result()
