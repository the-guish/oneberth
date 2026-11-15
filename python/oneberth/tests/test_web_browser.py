# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The journey of a person in a real browser, on a real backend.

A composed backend on uvicorn serves the development page of ``@oneberth/ui``,
built by ``npm run build:page``, under ``/ui/``. Chromium, driven by
Playwright, signs a person in through the stand-in provider on a port of its
own. The person makes a personal token that a script then uses, links a phone
from its QR code and the number the phone shows, and signs out.

It skips without the built page or a browser. CI builds both for one Python.
``ONEBERTH_TEST_CHROMIUM`` names a Chromium to use when Playwright's own build
is not installed.
"""

from __future__ import annotations

import asyncio
import base64
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import uvicorn
from fastapi import APIRouter

from oneberth.identity import Role, RoleTable
from oneberth.identity.memory import MemoryIdentityStore
from oneberth.web import Asking, Component, compose_app, permit, serve
from oneberth.web.testing import StandInProvider, bearer, config_for, read_qr

PAGE = Path(__file__).parents[3] / "ts" / "oneberth-ui" / "dist-page"
CHROMIUM_ENV = "ONEBERTH_TEST_CHROMIUM"
TIMEOUT_MS = 15_000

NOTES = RoleTable(
    app="notes",
    permissions=frozenset({"notes/items:read"}),
    roles=(Role("notes/user", frozenset({"notes/items:read"}), people=True),),
    default="notes/user",
)


def _notes() -> Component:
    router = APIRouter()

    @router.get("/items", dependencies=[permit("notes/items:read")])
    async def items(principal: Asking) -> dict[str, str]:
        return {"for": principal.name}

    return Component("notes", NOTES, router)


def _bound() -> socket.socket:
    return socket.create_server(("127.0.0.1", 0))


@asynccontextmanager
async def _on_uvicorn(app: Any, sock: socket.socket) -> AsyncIterator[None]:
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:
            await asyncio.wait({task}, timeout=0.02)
        yield
    finally:
        server.should_exit = True
        await task


@asynccontextmanager
async def _backend() -> AsyncIterator[tuple[str, StandInProvider]]:
    """The stand-in provider and a composed backend, each on a port of its own."""
    provider_socket, backend_socket = _bound(), _bound()
    stand_in = StandInProvider(f"http://127.0.0.1:{provider_socket.getsockname()[1]}")
    address = f"http://127.0.0.1:{backend_socket.getsockname()[1]}"
    store = MemoryIdentityStore()
    await store.setup()
    composition = compose_app(
        [_notes()],
        config=config_for(
            "notes", public_url=address, providers={"stand-in": stand_in.config}
        ),
        store=store,
        interface=PAGE,
    )
    ready, stop = asyncio.Event(), asyncio.Event()
    serving = asyncio.create_task(
        serve(
            composition, backend_socket, ready=ready.set, log_level="warning", stop=stop
        )
    )
    async with _on_uvicorn(stand_in.app, provider_socket):
        await asyncio.wait(
            {serving, asyncio.create_task(ready.wait())}, return_when="FIRST_COMPLETED"
        )
        try:
            yield address, stand_in
        finally:
            stop.set()
            await serving


@pytest.fixture
async def page() -> AsyncIterator[Any]:
    if not (PAGE / "index.html").is_file():
        pytest.skip("no built page: run `npm run build:page` in ts/oneberth-ui")
    playwright_api = pytest.importorskip("playwright.async_api")
    async with playwright_api.async_playwright() as playwright:
        executable = os.environ.get(CHROMIUM_ENV) or None
        try:
            browser = await playwright.chromium.launch(executable_path=executable)
        except playwright_api.Error as error:
            pytest.skip(f"no browser: {str(error).splitlines()[0]}; set {CHROMIUM_ENV}")
        context = await browser.new_context()
        context.set_default_timeout(TIMEOUT_MS)
        yield await context.new_page()
        await browser.close()


async def test_a_person_signs_in_makes_a_token_links_a_phone_and_signs_out(
    page: Any,
) -> None:
    from playwright.async_api import expect

    async with _backend() as (address, _), httpx.AsyncClient(base_url=address) as phone:
        # Signed out, the sign-in page stands in place of every page.
        await page.goto(f"{address}/ui/#/account/tokens")
        await page.get_by_role("link", name="Sign in with Stand-in").click()

        # Back from the provider, on the page the person asked for.
        await expect(page.get_by_text("No personal tokens.")).to_be_visible()
        assert page.url == f"{address}/ui/#/account/tokens"

        # A personal token, shown once, works for a script.
        await page.get_by_role("button", name="New token").click()
        await page.get_by_label("Name of the token").fill("laptop")
        await page.get_by_role("button", name="Create").click()
        shown = page.get_by_role("region", name="The new token")
        secret = (await shown.get_by_text("ob_pat_").inner_text()).strip()
        listed = page.get_by_role("list", name="Personal tokens")
        await expect(listed.get_by_text("laptop")).to_be_visible()
        script = await phone.get("/notes/items", headers=bearer(secret))
        assert script.json() == {"for": "Ada Lovelace"}

        # A phone reads the QR code, claims it, and the person types its number.
        await page.goto(f"{address}/ui/#/account/devices")
        await expect(page.get_by_text("No device is linked.")).to_be_visible()
        await page.get_by_role("button", name="Link a phone").click()
        dialog = page.get_by_role("dialog", name="Link a phone")
        picture = dialog.get_by_role(
            "img", name="QR code to scan with the app on your phone"
        )
        source = await picture.get_attribute("src")
        assert source is not None and source.startswith("data:image/svg+xml;base64,")
        link = read_qr(base64.b64decode(source.partition(",")[2]).decode())
        assert link.startswith(f"{address}/#/link?v=1&c=")
        code = parse_qs(urlsplit(link).fragment.partition("?")[2])["c"][0]
        claimed = await phone.post(
            "/auth/pairings/claim",
            json={"code": code, "device": {"name": "Pixel 9", "platform": "android"}},
        )
        number = claimed.json()["number"]
        await expect(
            dialog.get_by_text("A phone scanned your code. Type the number it shows.")
        ).to_be_visible()
        await dialog.get_by_label("The number on the phone").fill(number)
        await dialog.get_by_role("button", name="Link").click()
        await expect(dialog.get_by_text("Linked.")).to_be_visible()
        await dialog.get_by_role("button", name="Done").click()
        devices = page.get_by_role("list", name="Linked devices")
        await expect(devices.get_by_text("Pixel 9")).to_be_visible()
        as_phone = await phone.get(
            "/notes/items", headers=bearer(claimed.json()["secret"])
        )
        assert as_phone.status_code == 200

        # Signing out brings the sign-in page back, and the session is gone.
        await page.get_by_role("button", name="Account").click()
        await page.get_by_role("button", name="Sign out").click()
        await expect(
            page.get_by_role("link", name="Sign in with Stand-in")
        ).to_be_visible()
        session = await page.evaluate(
            "fetch('/auth/session').then((answer) => answer.json())"
        )
        assert session["principal"] is None
