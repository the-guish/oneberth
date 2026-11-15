# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The checks on a request, the session cookie, and where a sign-in may return.

These are pure functions of what a request says (identity.md, "Checks on a
request"). The gate in ``_gate.py`` runs them on every request, before routing,
so a refused write never reaches a handler and its body is never read.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

from oneberth.config import is_loopback
from oneberth.web._errors import Refusal

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_OTHER_SITES = frozenset({"cross-site", "same-site"})

MAX_RETURN_TO = 2048

DEFAULT_RETURN_TO = "/ui/"


def bearer_of(authorization: str | None) -> str | None:
    """The secret of an ``Authorization: Bearer`` header; ``None`` for anything else."""
    if authorization is None:
        return None
    scheme, _, secret = authorization.strip().partition(" ")
    secret = secret.strip()
    if scheme.lower() != "bearer" or not secret:
        return None
    return secret


def media_type(content_type: str | None) -> str:
    return (content_type or "").partition(";")[0].strip().lower()


def check_request(
    method: str,
    *,
    content_type: str | None,
    has_body: bool,
    fetch_site: str | None,
    origin: str | None,
    bearer: bool,
    cookie: bool,
    public_url: str,
) -> Refusal | None:
    """The refusal a request earns before it is routed, or ``None``.

    ``bearer`` says whether it carries ``Authorization: Bearer``, and
    ``cookie`` whether it carries the session cookie.
    """
    if bearer and cookie:
        return Refusal(
            400,
            "TwoCredentials",
            "send a bearer or the session cookie, not both",
        )
    if method.upper() in SAFE_METHODS:
        return None
    if (fetch_site or "").strip().lower() in _OTHER_SITES:
        return Refusal(403, "CrossSite", "a write from a page on another site")
    # A DELETE without a body names what it removes in its path. A page on
    # another site cannot send one without a preflight, which nothing answers.
    exempt = method.upper() == "DELETE" and not has_body
    if not exempt and media_type(content_type) != "application/json":
        return Refusal(415, "UnsupportedMediaType", "a write is application/json")
    if cookie and not bearer and (origin or "").strip().lower() != public_url:
        return Refusal(
            403,
            "CrossOrigin",
            f"a write with the session cookie comes from {public_url}, not "
            f"{origin or 'an unnamed origin'}",
        )
    return None


def is_local_host(values: list[str]) -> bool:
    """Whether the ``Host`` headers of a request name ``localhost`` or an IP
    address, with a port or without: what the local mode answers.

    DNS rebinding needs a name: a page on the internet points its own name at
    this machine, and the browser sends that name as ``Host``. An IP address
    cannot be rebound.
    """
    if len(values) != 1:
        return False
    host = values[0].lower()
    if not host or any(c in host for c in "/?#@\\ ") or not host.isprintable():
        return False
    try:
        parts = urlsplit(f"//{host}")
        _ = parts.port  # a port that is not a number raises
    except ValueError:
        return False
    if parts.hostname == "localhost":
        return True
    try:
        ipaddress.ip_address(parts.hostname or "")
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class Cookies:
    """The names and attributes of the session cookie and the sign-in cookie.

    On ``https`` they are ``__Host-`` prefixed and ``Secure``. A loopback
    origin over ``http`` drops both and ends each name with the port: browsers
    share cookies across the ports of one host.
    """

    session: str
    login: str
    secure: bool

    @classmethod
    def of(cls, public_url: str) -> Cookies:
        parts = urlsplit(public_url)
        if parts.scheme == "http" and is_loopback(parts.hostname or ""):
            port = parts.port or 80
            return cls(f"oneberth_session_{port}", f"oneberth_login_{port}", False)
        return cls("__Host-oneberth_session", "__Host-oneberth_login", True)


def safe_return_to(value: str | None) -> str:
    """Where a sign-in may send the browser back: a path of this origin.

    Anything else, a URL of another site included, returns to the interface.
    """
    if (
        not value
        or len(value) > MAX_RETURN_TO
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or not value.isprintable()
        or any(c.isspace() for c in value)
    ):
        return DEFAULT_RETURN_TO
    return value
