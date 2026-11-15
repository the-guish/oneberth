# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The two outer layers of a listener, in plain ASGI.

``Shield`` is outermost. It adds the security headers to every answer that
does not set them itself, and turns an error nobody handled into a 500 of the
one answer shape. ``Gate`` comes next. It runs the checks on a request, limits
the size of a body, and, for a route that needs a principal, finds who is
asking and checks the route's permission. All of that happens before the route
reads its body: a refused request never reaches a handler.

Plain ASGI, so a stream passes through untouched and a client that leaves is
seen by the handler.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from starlette.convertors import Convertor
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.requests import HTTPConnection
from starlette.routing import compile_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from oneberth.identity import IdentityError
from oneberth.web._backend import PRINCIPAL_KEY, Backend
from oneberth.web._checks import bearer_of, check_request, is_local_host
from oneberth.web._errors import Refusal, identity_refusal

log = logging.getLogger("oneberth.web")

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ]
)
"""Scripts, styles and connections from the page's own origin; inline styles,
which React sets; frames of the same origin, for a view an application serves."""

SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("content-security-policy", CONTENT_SECURITY_POLICY),
    ("x-frame-options", "DENY"),
    ("x-content-type-options", "nosniff"),
    ("referrer-policy", "same-origin"),
    ("cache-control", "no-store"),
)
"""What every answer carries unless its route sets the header itself."""


class Shield:
    """The security headers, and the 500 of an error nobody handled."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS:
                    headers.setdefault(name, value)
            await send(message)

        try:
            await self.app(scope, receive, with_headers)
        except Exception:
            log.exception("%s %s failed", scope.get("method"), scope.get("path"))
            if started:
                raise
            answer = Refusal(500, "InternalError", "the server failed to answer")
            await answer.answer()(scope, receive, with_headers)


@dataclass(frozen=True, slots=True)
class Rule:
    """What a route needs: a principal, and the permission it must hold on the
    resource its path parameter names. ``permission`` is ``None`` for a route
    that needs a principal alone, such as a person's tokens."""

    path: str
    """The whole path, as the listener serves it: ``/jobs/queues/{queue}``."""
    methods: frozenset[str]
    permission: str | None = None
    resource: str | None = None
    bound: bool = False
    """Whether the route acts on the resource of the principal's own grant.
    A route that names no resource refuses a bound grant otherwise."""

    def matches(self, scope: Scope) -> dict[str, Any] | None:
        """The path parameters of a request this route serves; ``None`` otherwise."""
        if scope["method"] not in self.methods:
            return None
        pattern, _, convertors = _compiled(self.path)
        found = pattern.match(_route_path(scope))
        if found is None:
            return None
        return {
            name: convertors[name].convert(value)
            for name, value in found.groupdict().items()
        }


def _route_path(scope: Scope) -> str:
    """The path below the root path a proxy serves the listener under."""
    path: str = scope["path"]
    root: str = scope.get("root_path", "")
    if root and path.startswith(root + "/"):
        return path[len(root) :]
    return path


@functools.lru_cache(maxsize=4096)
def _compiled(path: str) -> tuple[re.Pattern[str], str, dict[str, Convertor[Any]]]:
    return compile_path(path)


class BodyTooLarge(HTTPException):
    """Raised while a body is read past the limit. An ``HTTPException``, so
    FastAPI passes it on rather than calling it a body it could not parse."""

    def __init__(self, limit: int) -> None:
        super().__init__(413, f"the body is over {limit} bytes")


class Gate:
    """The checks on a request, the limit on a body, who is asking and the
    check of a route's permission."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        backend: Backend,
        rules: Sequence[Rule],
        local_host: bool = False,
        served: frozenset[Rule] | None = None,
    ) -> None:
        self.app = app
        self.backend = backend
        self.rules = rules
        self.local_host = local_host
        """Whether the ``Host`` must be ``localhost`` or an IP address."""
        self.served = served
        """The rules whose routes this listener serves; ``None`` for all of them.
        A request that meets another rule first is answered 404, as FastAPI
        would pick that rule's route."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        try:
            await self._check(scope, connection)
        except Refusal as refusal:
            await refusal.answer()(scope, receive, send)
            return
        except IdentityError as error:
            refused = identity_refusal(error)
            headers = {"www-authenticate": "Bearer"} if refused.status == 401 else None
            await refused.answer(headers)(scope, receive, send)
            return
        await self.app(scope, self._limited(receive), send)

    async def _check(self, scope: Scope, connection: HTTPConnection) -> None:
        backend = self.backend
        headers = connection.headers
        if self.local_host and not is_local_host(headers.getlist("host")):
            raise Refusal(
                403,
                "Forbidden",
                "the local mode answers a Host of localhost or an IP address",
            )
        length = headers.get("content-length")
        refusal = check_request(
            scope["method"],
            content_type=headers.get("content-type"),
            has_body=(length not in (None, "0")) or "transfer-encoding" in headers,
            fetch_site=headers.get("sec-fetch-site"),
            origin=headers.get("origin"),
            bearer=bearer_of(headers.get("authorization")) is not None,
            cookie=backend.cookies.session in connection.cookies,
            public_url=backend.public_url,
        )
        if refusal is not None:
            raise refusal
        if length is not None and (
            not length.isdigit() or int(length) > backend.max_body
        ):
            raise Refusal(
                413, "PayloadTooLarge", f"the body is over {backend.max_body} bytes"
            )
        rule, path_params = self._rule(scope)
        if rule is None:
            return
        if self.served is not None and rule not in self.served:
            raise Refusal(404, "NotFound", "Not Found")
        principal = await backend.principal_of(connection)
        scope[PRINCIPAL_KEY] = principal
        if rule.permission is not None:
            resource = path_params.get(rule.resource) if rule.resource else None
            backend.access.authorize(
                principal,
                rule.permission,
                None if resource is None else str(resource),
                bound=rule.bound,
            )

    def _rule(self, scope: Scope) -> tuple[Rule | None, dict[str, Any]]:
        for rule in self.rules:
            params = rule.matches(scope)
            if params is not None:
                return rule, params
        return None, {}

    def _limited(self, receive: Receive) -> Receive:
        limit = self.backend.max_body
        size = 0

        async def counted() -> Message:
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    raise BodyTooLarge(limit)
            return message

        return counted
