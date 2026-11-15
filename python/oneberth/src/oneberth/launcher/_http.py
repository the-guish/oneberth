# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The backend's routes the launcher calls, over HTTP with the standard library.

The launcher's requests go to a loopback address. They skip every proxy the
environment names.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any

from oneberth.launcher._describe import LauncherError

TIMEOUT_SECONDS = 10.0
"""How long the launcher waits for one answer of the backend."""

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class HttpBackendApi:
    """``POST /auth/services`` and ``POST /auth/tickets``, with the launch secret."""

    def __init__(self, front_url: str, secret: str) -> None:
        self._front_url = front_url
        self._secret = secret

    async def service_token(self, name: str, role: str, resource: str | None) -> str:
        made = await self._post(
            "/auth/services", {"name": name, "role": role, "resource": resource}
        )
        return str(made["secret"])

    async def ticket_url(self) -> str:
        made = await self._post("/auth/tickets", {})
        return str(made["url"])

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._posted, path, body)

    def _posted(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self._front_url + path,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "authorization": f"Bearer {self._secret}",
                "content-type": "application/json",
                "accept": "application/json",
            },
        )
        try:
            with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as answer:
                found: dict[str, Any] = json.load(answer)
                return found
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise LauncherError(
                f"the backend answered {error.code} to {path}: {detail}"
            ) from None
        except (OSError, ValueError) as error:
            raise LauncherError(f"the backend did not answer {path}: {error}") from None
