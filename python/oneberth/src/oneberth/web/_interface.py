# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The built interface, served under ``/ui/``.

The bundle uses hash routing, so ``index.html`` is the only page. A hashed
asset never changes under its name and is kept for a year. ``index.html``
names the current hashes, and a browser asks for it each time. The security
headers come from ``Shield``, like every other answer's.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_IMMUTABLE = b"public, max-age=31536000, immutable"
_NO_CACHE = b"no-cache"

NOT_BUILT = (
    "<!doctype html><meta charset=utf-8><title>Not built</title>"
    "<p>The interface is not built: this backend was started without one.</p>"
)


def interface_app(directory: Path) -> ASGIApp:
    """The files of a built interface, with their cache headers."""
    if not (directory / "index.html").is_file():
        raise FileNotFoundError(f"{directory} holds no index.html to serve")
    return _Cached(StaticFiles(directory=directory, html=True))


def not_built() -> HTMLResponse:
    return HTMLResponse(NOT_BUILT, status_code=404)


class _Cached:
    def __init__(self, files: ASGIApp) -> None:
        self._files = files

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._files(scope, receive, send)
            return
        below = scope["path"].removeprefix(scope.get("root_path", ""))
        hashed = below.startswith("/assets/")

        async def with_cache(message: Message) -> None:
            if message["type"] == "http.response.start":
                # A 404 kept for a year would outlive the deploy that adds the file.
                keep = hashed and message["status"] in (200, 304)
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", _IMMUTABLE if keep else _NO_CACHE))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self._files(scope, receive, with_cache)
        except HTTPException as missing:
            answer = PlainTextResponse(
                str(missing.detail), status_code=missing.status_code
            )
            await answer(scope, receive, with_cache)
