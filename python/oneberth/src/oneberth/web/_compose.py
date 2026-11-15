# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""``compose_app``: the web application of a backend, built from components.

It serves each component's routes under ``/<name>/``, oneberth's routes under
``/auth``, the interface under ``/ui/`` and ``/health``. It finds who is
asking and checks a route's permission before the handler runs, applies the
checks on a request and the security headers, and limits the size of a body.
It builds the front listener and the worker listener, writes one OpenAPI
document per component, starts the components in order and stops them in
reverse, and answers every error with one shape.

A component's life has four moments: its ``lifespan`` starts, then its
``serving`` begins once both listeners accept connections; at the stop, its
``serving`` ends while the listeners still serve, then its ``lifespan`` stops.
Each moment runs in the order of the components, and each end in reverse.
"""

from __future__ import annotations

import getpass
import logging
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import fastapi.routing
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from starlette.types import Receive, Scope, Send

from oneberth.config import Config, ConfigError
from oneberth.identity import (
    ONEBERTH_ROLES,
    Access,
    Clock,
    IdentityError,
    IdentityStore,
    InvalidValueError,
    Registry,
    ServiceTokenCheck,
    check_schema,
    system_clock,
)
from oneberth.identity._roles import is_app_name
from oneberth.web import _auth
from oneberth.web._backend import Backend
from oneberth.web._checks import Cookies
from oneberth.web._component import Component, Context, Permit, permits_of
from oneberth.web._errors import (
    ErrorBody,
    Refusal,
    http_error_name,
    identity_refusal,
    status_in,
)
from oneberth.web._gate import Gate, Rule, Shield
from oneberth.web._interface import interface_app, not_built

if TYPE_CHECKING:
    import httpx

log = logging.getLogger("oneberth.web")

MAX_BODY_BYTES = 16 * 1024 * 1024
"""The largest body a request may carry, by default."""

RESERVED_NAMES = frozenset({"auth", "ui", "health", "oneberth"})
"""Addresses of oneberth's own; no component is named so."""

StoreSource = IdentityStore | Callable[[], AbstractAsyncContextManager[IdentityStore]]
"""A store open already, or what opens it for the life of the backend, such as
``lambda: opened_store(database_url=url)``."""


class ServerError(RuntimeError):
    """The backend did not start: a listener could not be opened, or a
    component failed to start or to begin serving."""


class CompositionError(ValueError):
    """The components cannot be composed. ``problems`` lists every one found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("the components cannot be composed:\n" + "\n".join(problems))


class Composition:
    """A backend's web application: the front listener, and the worker listener.

    It is itself the front listener's ASGI application. ``worker`` serves the
    routes a worker role may call, and shares the front listener's state: the
    front listener's lifespan starts and stops both.
    """

    def __init__(
        self,
        front: FastAPI,
        worker: FastAPI,
        backend: Backend,
        apps: Sequence[Component] = (),
        started: _Started | None = None,
    ) -> None:
        self.front = front
        self.worker = worker
        self._backend = backend
        self._apps = tuple(apps)
        self._started = _Started() if started is None else started

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.front(scope, receive, send)

    @property
    def name(self) -> str:
        return self._backend.name

    @property
    def public_url(self) -> str:
        return self._backend.public_url

    @property
    def cookies(self) -> Cookies:
        return self._backend.cookies

    @property
    def registry(self) -> Registry:
        return self._backend.registry

    @property
    def access(self) -> Access:
        """The ``Access`` of the running backend; ``Refusal`` before it starts."""
        return self._backend.access

    @property
    def local(self) -> bool:
        """Whether this is the local mode: one user, signed in with a ticket."""
        return self._backend.local

    @property
    def launch_secret(self) -> str | None:
        """The launch secret of this start, in the local mode.

        Set it before the backend starts: ``serve`` does with the secret it is
        given.
        """
        return self._backend.launch_secret

    @launch_secret.setter
    def launch_secret(self, secret: str | None) -> None:
        if secret is not None and not self.local:
            raise ValueError("a launch secret is for the local mode alone")
        self._backend.launch_secret = secret

    def ticket_url(self, ticket: str) -> str:
        """Where ``ticket`` signs the local user in: what the window opens."""
        return self._backend.ticket_url(ticket)

    def lifespan(self) -> AbstractAsyncContextManager[None]:
        """Start the backend and stop it at the end of the block."""
        return cast(
            AbstractAsyncContextManager[None],
            self.front.router.lifespan_context(self.front),
        )

    @asynccontextmanager
    async def serving(self) -> AsyncIterator[None]:
        """The components' ``serving``, for the block: begun in order, ended
        in reverse. ``serve`` runs it once both listeners accept connections,
        and ends it before they stop.

        When one fails to begin, those begun already end, and this raises
        ``ServerError``. A failure at the end is logged, and the other
        components still end.
        """
        context = self._started.context
        if context is None:
            raise ServerError("the backend has not started")
        begun: list[tuple[Component, AbstractAsyncContextManager[None]]] = []
        try:
            for component in self._apps:
                if component.serving is None:
                    continue
                moment = component.serving(context)
                try:
                    await moment.__aenter__()
                except Exception as error:
                    log.exception(
                        "component %s failed to begin serving", component.name
                    )
                    raise ServerError(
                        f"component {component.name} failed to begin serving: {error}"
                    ) from error
                begun.append((component, moment))
                log.info("component %s serves", component.name)
            yield
        finally:
            for component, moment in reversed(begun):
                try:
                    await moment.__aexit__(None, None, None)
                except Exception:
                    log.exception("component %s failed to end serving", component.name)


def compose_app(
    apps: Sequence[Component],
    *,
    config: Config,
    store: StoreSource,
    interface: Path | None = None,
    name: str | None = None,
    max_body: int = MAX_BODY_BYTES,
    clock: Clock = system_clock,
    provider_transport: httpx.AsyncBaseTransport | None = None,
    local: bool = False,
    local_user: str | None = None,
) -> Composition:
    """Compose ``apps`` into the web application a backend serves.

    ``config`` is the deployment's sign-in configuration, and the backend's
    ``public_url`` is the one under its ``name``: the first component's by
    default. ``store`` is the deployment's store. ``interface`` is the
    directory of the built interface. ``clock`` and ``provider_transport``
    stand in for the time and the providers' network in tests.

    ``local`` asks for the local mode (identity.md, "Locally"): one user, the
    person at the machine, signed in with a ticket that the holder of the
    launch secret asks for. ``config`` then names no provider and no allow
    list, as ``local_config`` makes it. ``local_user`` is the name the local
    user goes by: the login name of the operating system by default. The
    backend starts once ``launch_secret`` is set; ``serve`` and ``run`` set it.

    Raises ``CompositionError`` for components that cannot be composed: a route
    without a permission, a permission nobody registered, two components of
    one name. Raises ``ConfigError`` for a configuration that does not fit.
    """
    problems: list[str] = []
    if not apps:
        problems.append("compose at least one component")
    seen: set[str] = set()
    for component in apps:
        if not is_app_name(component.name) or component.name in RESERVED_NAMES:
            problems.append(
                f"{component.name!r} cannot name a component: lower-case letters, "
                f"digits and -, and none of {', '.join(sorted(RESERVED_NAMES))}"
            )
        if component.name in seen:
            problems.append(f"two components are named {component.name!r}")
        seen.add(component.name)
        if component.roles.app != component.name:
            problems.append(
                f"component {component.name!r} declares the roles of "
                f"{component.roles.app!r}"
            )
    if problems:
        raise CompositionError(problems)
    registry = Registry([ONEBERTH_ROLES, *(c.roles for c in apps)])
    backend_name = apps[0].name if name is None else name
    try:
        config.policy.check(registry)
    except InvalidValueError as error:
        raise ConfigError([str(error)]) from None
    if local and (config.providers or config.policy.allow or config.policy.grants):
        raise ConfigError(
            [
                "the local mode signs its one user in with a ticket: the "
                "configuration names no provider, [[allow]] or [[grant]]"
            ]
        )
    public_url = config.app(backend_name).public_url
    backend = Backend(
        name=backend_name,
        config=config,
        public_url=public_url,
        cookies=Cookies.of(public_url),
        registry=registry,
        max_body=max_body,
        local=local,
    )

    token_checks: Mapping[str, ServiceTokenCheck] = {
        c.name: c.check_service_token for c in apps if c.check_service_token is not None
    }
    declared: dict[str, list[_Declared]] = {}
    for component in apps:
        declared[component.name] = _declared(component, registry, problems)
    if problems:
        raise CompositionError(problems)
    started = _Started()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            if callable(store):
                opened = await stack.enter_async_context(store())
            else:
                opened = store
            await check_schema(opened)
            access = config.access(
                opened,
                registry,
                clock=clock,
                local=local,
                service_token_checks=token_checks,
            )
            if local:
                if backend.launch_secret is None:
                    raise ConfigError(["the local mode starts with a launch secret"])
                await access.start_local(
                    backend.launch_secret, name=local_user or _login_name()
                )
                stack.push_async_callback(access.stop_local)
            # After every component has stopped: the tokens of the parts the
            # backend started end with it.
            stack.callback(access.end_tokens_in_memory)
            providers = None
            if config.providers:
                from oneberth.providers import Providers

                providers = Providers(
                    access, config.providers, transport=provider_transport
                )
            context = Context(access=access, config=config, public_url=public_url)
            for component in apps:
                if component.lifespan is not None:
                    await stack.enter_async_context(component.lifespan(context))
                    log.info("component %s started", component.name)
            backend.access_or_none = access
            backend.providers = providers
            started.context = context
            try:
                yield
            finally:
                started.context = None
                backend.access_or_none = None
                backend.providers = None
        log.info("backend %s stopped", backend_name)

    front = _listener(apps, backend, lifespan)
    front.include_router(_auth.router)
    front_rules = _own_rules(_auth.router)
    front.add_api_route("/health", _health, include_in_schema=False)
    front.add_api_route(
        "/auth/openapi.json",
        _document("oneberth", "0", [(_auth.router, "")]),
        include_in_schema=False,
    )
    for component in apps:
        prefix = f"/{component.name}"
        front.add_api_route(
            f"{prefix}/openapi.json",
            _document(
                component.title or component.name,
                component.version,
                [(component.router, prefix)],
            ),
            include_in_schema=False,
        )
        _include(front, component.router, prefix)
        front_rules += _rules(prefix, declared[component.name])
    front.add_api_route("/", _to_interface, include_in_schema=False)
    front.add_api_route("/ui", _to_interface, include_in_schema=False)
    if interface is not None:
        front.mount("/ui", interface_app(interface), name="ui")
    else:
        front.add_api_route("/ui/", not_built, include_in_schema=False)
    front.add_middleware(Gate, backend=backend, rules=front_rules, local_host=local)
    front.add_middleware(Shield)

    # The worker listener holds the whole router of a component with a worker
    # route, and its gate answers 404 for every route of the component that no
    # worker role may call. A router that includes routers cannot be cut into
    # its routes without FastAPI's own parts.
    worker = _listener(apps, backend, None)
    worker.add_api_route("/health", _health, include_in_schema=False)
    worker_rules: list[Rule] = []
    served: set[Rule] = set()
    for component in apps:
        prefix = f"/{component.name}"
        rules = _rules(prefix, declared[component.name])
        if any(registry.held_by_worker_role(r.permission or "") for r in rules):
            _include(worker, component.router, prefix)
            worker_rules += rules
            served.update(
                r for r in rules if registry.held_by_worker_role(r.permission or "")
            )
    worker.add_middleware(
        Gate, backend=backend, rules=worker_rules, served=frozenset(served)
    )
    worker.add_middleware(Shield)
    for component in apps:
        if component.health is not None:
            backend.health[component.name] = component.health
    return Composition(front, worker, backend, apps, started)


@dataclass(slots=True)
class _Started:
    """What the lifespan of a running backend gives its components."""

    context: Context | None = None


def _login_name() -> str | None:
    try:
        return getpass.getuser()
    except (ImportError, KeyError, OSError):
        return None


@dataclass(frozen=True, slots=True)
class _Declared:
    """A route of a component, its whole path below the component's address,
    and the permission it declares."""

    path: str
    methods: frozenset[str]
    permit: Permit


def _routes_of(router: APIRouter) -> Iterable[Any]:
    """Every route of ``router`` and of the routers it includes, at any depth.

    Each has its whole path, with the prefixes of the routers above it, and the
    dependencies of every ``include_router`` call above it. From FastAPI 0.141,
    an included router stays one entry, and ``iter_route_contexts`` walks it.
    Before 0.141, ``include_router`` copied each route, with that path and
    those dependencies, into the including router.
    """
    walk = getattr(fastapi.routing, "iter_route_contexts", None)
    if walk is None:
        return list(router.routes)
    return list(walk(router.routes))


def _declared(
    component: Component, registry: Registry, problems: list[str]
) -> list[_Declared]:
    """Each route of a component and the permission it declares, or the problems.

    A route takes its ``permit`` from its own dependencies, or from those of an
    ``include_router`` call above it. It declares one in all.
    """
    found: list[_Declared] = []
    for route in _routes_of(component.router):
        original = getattr(route, "original_route", route)
        if not isinstance(original, APIRoute):
            path = getattr(route, "path", None) or getattr(original, "path", original)
            problems.append(
                f"{component.name}: {path} is not a FastAPI route, and declares "
                "no permission"
            )
            continue
        methods = ",".join(sorted(route.methods or ()))
        where = f"{component.name}: {methods} {route.path}"
        permits, _ = permits_of(route.dependant)
        if not permits:
            problems.append(f"{where} declares no permission: add permit(...)")
            continue
        if len(permits) > 1:
            problems.append(
                f"{where} declares {len(permits)} permissions, with those of the "
                "include_router calls above it: one, please"
            )
            continue
        (permit,) = permits
        if not registry.has_permission(permit.permission):
            problems.append(
                f"{where} needs {permit.permission!r}, which no application registered"
            )
            continue
        if (
            permit.resource is not None
            and permit.resource not in route.param_convertors
        ):
            problems.append(
                f"{where}: the resource {permit.resource!r} is not a parameter of "
                "its path"
            )
            continue
        found.append(_Declared(route.path, frozenset(route.methods or ()), permit))
    return found


def _rules(prefix: str, declared: Sequence[_Declared]) -> list[Rule]:
    return [
        Rule(
            prefix + route.path,
            route.methods,
            route.permit.permission,
            route.permit.resource,
        )
        for route in declared
    ]


def _own_rules(router: APIRouter) -> list[Rule]:
    """oneberth's own routes that need a principal; the router holds its prefix."""
    rules: list[Rule] = []
    for route in router.routes:
        if isinstance(route, APIRoute):
            permits, signed_in = permits_of(route.dependant)
            if signed_in:
                permission = permits[0].permission if permits else None
                rules.append(
                    Rule(route.path, frozenset(route.methods or ()), permission)
                )
    return rules


def _include(app: FastAPI, router: APIRouter, prefix: str) -> None:
    app.include_router(
        router,
        prefix=prefix,
        responses={"default": {"model": ErrorBody, "description": "A refusal"}},
    )


def _listener(
    apps: Sequence[Component],
    backend: Backend,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None,
) -> FastAPI:
    app = FastAPI(
        title=backend.name,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.oneberth = backend
    _install_errors(app, apps)
    return app


def _install_errors(app: FastAPI, apps: Sequence[Component]) -> None:
    async def refused(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, Refusal)
        return exc.answer()

    async def identity(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, IdentityError)
        refusal = identity_refusal(exc)
        headers = {"www-authenticate": "Bearer"} if refusal.status == 401 else None
        return refusal.answer(headers)

    async def invalid(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        problems = "; ".join(
            f"{'.'.join(str(p) for p in error.get('loc', ()))}: {error.get('msg')}"
            for error in exc.errors()
        )
        return Refusal(422, "InvalidRequest", problems or "invalid request").answer()

    async def http(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, HTTPException)
        return Refusal(
            exc.status_code, http_error_name(exc.status_code), str(exc.detail)
        ).answer(exc.headers)

    app.add_exception_handler(Refusal, refused)
    app.add_exception_handler(IdentityError, identity)
    app.add_exception_handler(RequestValidationError, invalid)
    app.add_exception_handler(HTTPException, http)
    for component in apps:
        for cls in component.errors:

            async def application(
                request: Request, exc: Exception, component: Component = component
            ) -> JSONResponse:
                status = status_in(component.errors, exc) or 500
                return JSONResponse(component.error_body(exc), status_code=status)

            app.add_exception_handler(cls, application)


async def _health(request: Request) -> JSONResponse:
    backend: Backend = request.app.state.oneberth
    if backend.access_or_none is None:
        return JSONResponse({"status": "starting", "components": {}}, status_code=503)
    states: dict[str, str] = {}
    for component, healthy in backend.health.items():
        try:
            well = bool(await healthy())
        except Exception:
            log.exception("the health of %s could not be read", component)
            well = False
        states[component] = "ok" if well else "failing"
    ok = all(state == "ok" for state in states.values())
    return JSONResponse(
        {"status": "ok" if ok else "failing", "components": states},
        status_code=200 if ok else 503,
    )


async def _to_interface() -> RedirectResponse:
    return RedirectResponse("/ui/")


def _document(
    title: str, version: str, routers: Sequence[tuple[APIRouter, str]]
) -> Callable[[], Any]:
    """The OpenAPI document of some routers, written at the first ask."""
    cache: dict[str, Any] = {}

    async def document() -> JSONResponse:
        if "document" not in cache:
            app = FastAPI(title=title, version=version)
            for router, prefix in routers:
                _include(app, router, prefix)
            cache["document"] = app.openapi()
        return JSONResponse(cache["document"], headers={"cache-control": "no-cache"})

    return document
