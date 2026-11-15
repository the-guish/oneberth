# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The web part of oneberth: the ``web`` extra, on FastAPI, Starlette and uvicorn.

An application builds a ``Component`` around a FastAPI router whose routes
each declare a permission with ``permit``, and take the principal with
``Asking``, ``Browsing``, ``FreshBrowsing`` or ``Device``. A backend composes
components with ``compose_app`` and serves the result with ``serve`` or
``run``. In the local mode, ``run`` takes the launch secret from standard
input, or makes one and prints the address that signs the person in.
``oneberth.web.testing`` helps an application's tests do the same.
"""

from oneberth.web._checks import (
    Cookies,
    bearer_of,
    check_request,
    is_local_host,
    safe_return_to,
)
from oneberth.web._component import (
    Asking,
    Browsing,
    Component,
    Context,
    Device,
    FreshBrowsing,
    Health,
    Lifespan,
    Permit,
    asking,
    browsing,
    browsing_fresh,
    device,
    permit,
    while_connected,
)
from oneberth.web._compose import (
    MAX_BODY_BYTES,
    RESERVED_NAMES,
    Composition,
    CompositionError,
    StoreSource,
    compose_app,
)
from oneberth.web._errors import ErrorBody, Refusal
from oneberth.web._gate import CONTENT_SECURITY_POLICY, SECURITY_HEADERS
from oneberth.web._qr import qr_svg
from oneberth.web._server import (
    READY,
    Listen,
    ServerError,
    Where,
    read_launch_secret,
    run,
    serve,
)

__all__ = [
    "CONTENT_SECURITY_POLICY",
    "MAX_BODY_BYTES",
    "READY",
    "RESERVED_NAMES",
    "SECURITY_HEADERS",
    "Asking",
    "Browsing",
    "Component",
    "Composition",
    "CompositionError",
    "Context",
    "Cookies",
    "Device",
    "ErrorBody",
    "FreshBrowsing",
    "Health",
    "Lifespan",
    "Listen",
    "Permit",
    "Refusal",
    "ServerError",
    "StoreSource",
    "Where",
    "asking",
    "bearer_of",
    "browsing",
    "browsing_fresh",
    "check_request",
    "compose_app",
    "device",
    "is_local_host",
    "permit",
    "qr_svg",
    "read_launch_secret",
    "run",
    "safe_return_to",
    "serve",
    "while_connected",
]
