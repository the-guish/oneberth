# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""What an application's tests need to drive a composition.

- ``config_for`` gives a configuration where any person of the provider
  ``test`` may sign in.
- ``running`` starts a composition and gives an ``httpx`` client on it, in
  process, which sends ``Origin`` as a browser does.
- ``signed_in`` signs a person in and puts the session cookie on a client.
  ``service_token`` makes a service token.
- ``StandInProvider`` is an OpenID Connect provider for a sign-in from start to
  end: in process through ``transport()``, or on a port for a browser.
- ``read_qr`` reads the text of the QR code the pairing page shows, as a phone
  would.

Each stands at the edge of oneberth: a test drives the real composition, its
real store and its real routes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, quote, urlencode

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from oneberth.config import AppConfig, Config, ProviderConfig
from oneberth.identity import (
    OPERATOR,
    Clock,
    GrantEntry,
    Identity,
    Match,
    Matcher,
    Policy,
    system_clock,
)
from oneberth.web._compose import Composition
from oneberth.web._qr import QUIET_MODULES, Ecc, QrCode, _masked

TEST_PROVIDER = "test"
"""The provider of the people ``config_for`` lets in. Nothing serves it:
``signed_in`` signs people in through the store directly."""

ADA = Identity(TEST_PROVIDER, "ada", name="Ada Lovelace", email="ada@example.com")


def config_for(
    *names: str,
    public_url: str = "http://127.0.0.1:8000",
    admins: Sequence[str] = (),
    providers: Mapping[str, ProviderConfig] | None = None,
) -> Config:
    """A configuration for ``names``, each at ``public_url``.

    Everyone of the provider ``test``, and of each provider in ``providers``,
    may sign in. The subjects in ``admins`` hold ``oneberth/admin`` too.
    """
    allowed = [TEST_PROVIDER, *(providers or {})]
    return Config(
        apps={name: AppConfig(name, public_url) for name in names},
        providers=dict(providers or {}),
        policy=Policy(
            allow=tuple(Match(p, Matcher.EVERYONE) for p in allowed),
            grants=tuple(
                GrantEntry(
                    Match(p, Matcher.SUBJECT, subject), frozenset({"oneberth/admin"})
                )
                for p in allowed
                for subject in admins
            ),
        ),
    )


@asynccontextmanager
async def running(composition: Composition) -> AsyncIterator[httpx.AsyncClient]:
    """``composition`` started, and a client on its front listener.

    The client sends ``Origin`` with every request, as a browser does with a
    write, and keeps the cookies the backend sets.
    """
    async with (
        composition.lifespan(),
        client_of(composition) as client,
    ):
        yield client


def client_of(composition: Composition, *, worker: bool = False) -> httpx.AsyncClient:
    """A client on one listener of a started composition."""
    app = composition.worker if worker else composition.front
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=composition.public_url,
        headers={"origin": composition.public_url},
    )


async def signed_in(
    composition: Composition,
    client: httpx.AsyncClient,
    identity: Identity = ADA,
) -> str:
    """Sign ``identity`` in and give ``client`` the session cookie; the secret."""
    done = await composition.access.sign_in(identity)
    client.cookies.set(composition.cookies.session, done.secret)
    return done.secret


async def service_token(
    composition: Composition,
    role: str,
    resource: str | None = None,
    *,
    name: str | None = None,
) -> str:
    """A service token of ``role``, made as the operator makes one; its secret."""
    secret, _ = await composition.access.create_service_token(
        name or f"test-{uuid.uuid4().hex[:8]}", role, resource=resource, by=OPERATOR
    )
    return secret


def bearer(secret: str) -> dict[str, str]:
    """The header that sends ``secret`` as a bearer."""
    return {"authorization": f"Bearer {secret}"}


class StandInProvider:
    """An OpenID Connect provider for tests: discovery, an authorization page
    that signs ``person`` in at once, and a token endpoint.

    It checks the client's secret and the PKCE verifier as a real provider does,
    and answers with an unsigned ID token. ``issuer`` is where it is served:
    ``transport()`` serves it in process, and uvicorn on that address serves it
    to a browser.
    """

    def __init__(
        self,
        issuer: str = "http://127.0.0.1:9999",
        *,
        provider_id: str = "stand-in",
        client_id: str = "oneberth-test",
        client_secret: str = "stand-in secret",
        clock: Clock = system_clock,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.clock = clock
        self.provider_id = provider_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.person: dict[str, Any] = {
            "sub": "ada",
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "email_verified": True,
        }
        self._codes: dict[str, dict[str, str]] = {}
        self.app = self._build()

    @property
    def config(self) -> ProviderConfig:
        return ProviderConfig(
            id=self.provider_id,
            title="Stand-in",
            issuer=self.issuer,
            client_id=self.client_id,
            client_secret=self.client_secret,
        )

    def transport(self) -> httpx.AsyncBaseTransport:
        """The provider in process, for the backend's client to reach."""
        return httpx.ASGITransport(app=self.app)

    async def authorize(self, location: str) -> str:
        """What a browser does at the provider: the URL it is sent back to."""
        async with httpx.AsyncClient(
            transport=self.transport(), base_url=self.issuer
        ) as http:
            answer = await http.get(location)
        assert answer.status_code == 303, answer.text
        return answer.headers["location"]

    def _build(self) -> FastAPI:
        app = FastAPI(openapi_url=None)

        @app.get("/.well-known/openid-configuration")
        async def discovery() -> JSONResponse:
            return JSONResponse(
                {
                    "issuer": self.issuer,
                    "authorization_endpoint": f"{self.issuer}/authorize",
                    "token_endpoint": f"{self.issuer}/token",
                }
            )

        @app.get("/authorize")
        async def authorize(request: Request) -> RedirectResponse:
            asked = dict(request.query_params)
            code = secrets.token_urlsafe(16)
            self._codes[code] = asked
            query = urlencode({"code": code, "state": asked["state"]})
            return RedirectResponse(f"{asked['redirect_uri']}?{query}", status_code=303)

        @app.post("/token")
        async def token(request: Request) -> JSONResponse:
            form = {
                k: v[0] for k, v in parse_qs((await request.body()).decode()).items()
            }
            asked = self._codes.pop(form.get("code", ""), None)
            if asked is None:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            scheme, _, pair = request.headers.get("authorization", "").partition(" ")
            expected = (
                f"{quote(self.client_id, safe='')}:{quote(self.client_secret, safe='')}"
            )
            if scheme != "Basic" or base64.b64decode(pair).decode() != expected:
                return JSONResponse({"error": "invalid_client"}, status_code=401)
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(form.get("code_verifier", "").encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            if (
                challenge != asked["code_challenge"]
                or form.get("redirect_uri") != asked["redirect_uri"]
            ):
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            now = int(self.clock().timestamp())
            claims = {
                "iss": self.issuer,
                "aud": self.client_id,
                "iat": now,
                "exp": now + 300,
                "nonce": asked["nonce"],
                **self.person,
            }
            return JSONResponse({"id_token": _unsigned_jwt(claims)})

        return app


def _unsigned_jwt(claims: Mapping[str, Any]) -> str:
    def part(value: Mapping[str, Any]) -> str:
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2lnbmF0dXJl"


_MODULE = re.compile(r"M(\d+) (\d+)h1v1h-1z")
_VIEW_BOX = re.compile(r'viewBox="0 0 (\d+) \d+"')
_ECC_OF_FORMAT = {1: Ecc.LOW, 0: Ecc.MEDIUM, 3: Ecc.QUARTILE, 2: Ecc.HIGH}


def read_qr(svg: str) -> str:
    """The text of a QR code that ``qr_svg`` drew, read as a phone reads it.

    It reads the modules, the format, the mask and the codewords, and takes
    the data of byte mode. It corrects no error: the picture is exact.
    """
    found = _VIEW_BOX.search(svg)
    assert found is not None, "not an SVG of qr_svg"
    size = int(found.group(1)) - 2 * QUIET_MODULES
    modules = [[False] * size for _ in range(size)]
    for x, y in _MODULE.findall(svg):
        modules[int(y) - QUIET_MODULES][int(x) - QUIET_MODULES] = True
    version = (size - 17) // 4
    bits = 0
    for i, (x, y) in enumerate(
        [(8, i) for i in range(6)]
        + [(8, 7), (8, 8), (7, 8)]
        + [(14 - i, 8) for i in range(9, 15)]
    ):
        bits |= int(modules[y][x]) << i
    data = (bits ^ 0x5412) >> 10
    ecc, mask = _ECC_OF_FORMAT[data >> 3], data & 7
    # The function patterns of this version, from an encoder of the same size.
    template = QrCode.__new__(QrCode)
    template.version, template.ecc, template.size = version, ecc, size
    template.modules = [[False] * size for _ in range(size)]
    template._function = [[False] * size for _ in range(size)]
    template._draw_function_patterns()
    function = template._function
    stream: list[int] = []
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = (right + 1) & 2 == 0
        for vertical in range(size):
            y = size - 1 - vertical if upward else vertical
            for x in (right, right - 1):
                if not function[y][x]:
                    stream.append(int(modules[y][x] != _masked(mask, x, y)))
        right -= 2
    codewords = [
        int("".join(map(str, stream[i : i + 8])), 2)
        for i in range(0, len(stream) - 7, 8)
    ]
    data_words = _deinterleaved(codewords, version, ecc)
    bitstring = "".join(f"{w:08b}" for w in data_words)
    assert bitstring[:4] == "0100", "not byte mode"
    count_bits = 8 if version <= 9 else 16
    length = int(bitstring[4 : 4 + count_bits], 2)
    start = 4 + count_bits
    raw = bytes(
        int(bitstring[start + 8 * i : start + 8 * i + 8], 2) for i in range(length)
    )
    return raw.decode("utf-8")


def _deinterleaved(codewords: list[int], version: int, ecc: Ecc) -> list[int]:
    from oneberth.web._qr import (
        _ECC_CODEWORDS_PER_BLOCK,
        _ERROR_CORRECTION_BLOCKS,
        _raw_modules,
    )

    blocks = _ERROR_CORRECTION_BLOCKS[ecc][version]
    ecc_length = _ECC_CODEWORDS_PER_BLOCK[ecc][version]
    raw = _raw_modules(version) // 8
    short_blocks = blocks - raw % blocks
    short_length = raw // blocks
    lengths = [
        short_length - ecc_length + (0 if i < short_blocks else 1)
        for i in range(blocks)
    ]
    data: list[list[int]] = [[] for _ in range(blocks)]
    words = iter(codewords)
    for i in range(max(lengths)):
        for j in range(blocks):
            if i < lengths[j]:
                data[j].append(next(words))
    return [word for block in data for word in block]
