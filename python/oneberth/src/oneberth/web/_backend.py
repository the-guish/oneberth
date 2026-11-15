# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""What both listeners of a composition share: the configuration, the cookies,
the ``Access`` the store is opened on, and who is asking."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from starlette.requests import HTTPConnection

from oneberth.config import Config
from oneberth.identity import Access, AuthenticationError, Principal, Registry
from oneberth.web._checks import Cookies, bearer_of
from oneberth.web._errors import Refusal

if TYPE_CHECKING:
    from oneberth.providers import Providers

PRINCIPAL_KEY = "oneberth.principal"
"""Where the gate leaves the principal in the request's scope."""


@dataclass
class Backend:
    """The state of one composition, set on ``app.state.oneberth`` of both listeners."""

    name: str
    config: Config
    public_url: str
    cookies: Cookies
    registry: Registry
    max_body: int
    local: bool = False
    """Whether this is the local mode: one user, signed in with a ticket."""
    launch_secret: str | None = None
    """The launch secret of this start, in the local mode. In memory alone."""
    access_or_none: Access | None = None
    providers: Providers | None = None
    health: dict[str, Callable[[], Any]] = field(default_factory=dict)

    @property
    def access(self) -> Access:
        """The ``Access`` of the running backend."""
        if self.access_or_none is None:
            raise Refusal(
                503,
                "Unavailable",
                "the backend is starting or stopping: a component's own requests "
                "to it begin in its serving, once every component has started",
            )
        return self.access_or_none

    async def principal_of(self, connection: HTTPConnection) -> Principal:
        """Who a request names, by its bearer or its session cookie.

        Raises ``AuthenticationError`` when it names nobody.
        """
        bearer = bearer_of(connection.headers.get("authorization"))
        if bearer is not None:
            return await self.access.authenticate(bearer, bearer=True)
        cookie = connection.cookies.get(self.cookies.session)
        if cookie:
            return await self.access.authenticate(cookie, bearer=False)
        raise AuthenticationError(
            "nobody is signed in: send a bearer, or sign in at /ui/"
        )

    async def principal(self, connection: HTTPConnection) -> Principal:
        """The principal of a request, found once and kept in its scope."""
        found = connection.scope.get(PRINCIPAL_KEY)
        if isinstance(found, Principal):
            return found
        principal = await self.principal_of(connection)
        connection.scope[PRINCIPAL_KEY] = principal
        return principal

    def ticket_url(self, ticket: str) -> str:
        """Where a ticket signs the local user in: what the window opens."""
        return f"{self.public_url}/auth/local?{urlencode({'ticket': ticket})}"


def backend_of(connection: HTTPConnection) -> Backend:
    backend: Backend = connection.app.state.oneberth
    return backend
