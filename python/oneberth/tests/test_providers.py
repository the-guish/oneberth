# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""Sign-in through a provider, against a stand-in provider at the HTTP boundary.

The stand-in serves discovery and a token endpoint over an ``httpx`` transport.
It checks the client's secret and the PKCE verifier as a real provider does,
and answers with an unsigned ID token holding the claims a test asks for.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import httpx
import pytest

from oneberth.config import ProviderConfig
from oneberth.identity import (
    ONEBERTH_ROLES,
    Access,
    Match,
    Matcher,
    Policy,
    Registry,
)
from oneberth.identity.memory import MemoryIdentityStore
from oneberth.identity.testing import ManualClock
from oneberth.providers import (
    Providers,
    SignInError,
    SignInErrorCode,
    pkce_challenge,
)

OKTA = ProviderConfig(
    id="okta",
    title="Okta",
    issuer="https://example.okta.com/oauth2/default",
    client_id="okta-client",
    client_secret="okta secret:1",
    scopes=("openid", "email", "groups"),
    groups_claim="groups",
)
GOOGLE = ProviderConfig(
    id="google",
    title="Google",
    issuer="https://accounts.google.com",
    client_id="google-client",
    client_secret="g",
)
REDIRECT = "https://app.example.com/auth/callback/okta"
POLICY = Policy(
    allow=(
        Match("okta", Matcher.GROUP, "users"),
        Match("google", Matcher.HOSTED_DOMAIN, "example.com"),
        Match("google", Matcher.EMAIL, "ada@gmail.com"),
    )
)


class StandIn:
    """A provider for one issuer: discovery, and a token endpoint for codes."""

    def __init__(self, config: ProviderConfig, clock: ManualClock) -> None:
        self.config = config
        self.clock = clock
        self.discovery: dict[str, Any] = {
            "issuer": config.issuer + "/",
            "authorization_endpoint": config.issuer + "/authorize?prompt=login",
            "token_endpoint": config.issuer + "/token",
        }
        self.discovery_status = 200
        self.token_answer: tuple[int, Any] | None = None
        self.requests: list[str] = []
        self._codes: dict[str, tuple[str, str, dict[str, Any]]] = {}

    def authorize(self, url: str, **claims: Any) -> str:
        """The person signs in at ``url``; the code the browser brings back."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert query["response_type"] == "code"
        assert query["code_challenge_method"] == "S256"
        assert query["client_id"] == self.config.client_id
        code = secrets.token_urlsafe(8)
        now = int(self.clock().timestamp())
        token = {
            "iss": self.discovery["issuer"],
            "aud": self.config.client_id,
            "sub": "00u1",
            "iat": now,
            "exp": now + 300,
            "nonce": query["nonce"],
            **claims,
        }
        self._codes[code] = (query["code_challenge"], query["redirect_uri"], token)
        return code

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(self.discovery_status, json=self.discovery)
        assert request.url.path.endswith("/token")
        if self.token_answer is not None:
            status, body = self.token_answer
            return httpx.Response(status, json=body)
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        pair = base64.b64decode(request.headers["authorization"].split()[1]).decode()
        # RFC 6749 2.3.1: each half form-encoded before they are joined.
        expected = f"{quote(self.config.client_id)}:{quote(self.config.client_secret)}"
        if pair != expected:
            return httpx.Response(401, json={"error": "invalid_client"})
        found = self._codes.pop(form["code"], None)
        if found is None:
            return httpx.Response(400, json={"error": "invalid_grant"})
        challenge, redirect, claims = found
        verifier_ok = pkce_challenge(form["code_verifier"]) == challenge
        if not verifier_ok or form["redirect_uri"] != redirect:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"id_token": _jwt(claims)})


def _jwt(claims: dict[str, Any]) -> str:
    def part(value: dict[str, Any]) -> str:
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2ln"


class World:
    def __init__(self) -> None:
        self.clock = ManualClock()
        self.store = MemoryIdentityStore()
        self.access = Access(
            self.store, Registry([ONEBERTH_ROLES]), POLICY, clock=self.clock
        )
        self.okta = StandIn(OKTA, self.clock)
        self.google = StandIn(GOOGLE, self.clock)

        def route(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            return (self.google if host == "accounts.google.com" else self.okta).handle(
                request
            )

        self.providers = Providers(
            self.access,
            {"okta": OKTA, "google": GOOGLE},
            transport=httpx.MockTransport(route),
        )

    async def sign_in(
        self, provider: str = "okta", *, return_to: str = "/", **claims: Any
    ) -> Any:
        stand_in = self.okta if provider == "okta" else self.google
        url, state = await self.providers.begin(
            provider, redirect_uri=REDIRECT, return_to=return_to
        )
        code = stand_in.authorize(url, **claims)
        return await self.providers.finish(
            provider, redirect_uri=REDIRECT, state=state, code=code
        )


@pytest.fixture
async def world() -> World:
    created = World()
    await created.store.setup()
    return created


async def test_a_person_signs_in_through_okta_with_their_groups(world: World) -> None:
    url, state = await world.providers.begin(
        "okta", redirect_uri=REDIRECT, return_to="/#/neorc/runs"
    )

    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://example.okta.com/oauth2/default/authorize"
    )
    assert query["prompt"] == ["login"]
    assert query["scope"] == ["openid email groups"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["state"] == [state]
    code = world.okta.authorize(
        url,
        name="Ada",
        email="ada@example.com",
        email_verified=True,
        groups=["users", 7],
        hd="example.com",
    )

    finished = await world.providers.finish(
        "okta", redirect_uri=REDIRECT, state=state, code=code
    )

    user = finished.signed_in.user
    assert finished.return_to == "/#/neorc/runs"
    assert (user.provider, user.subject, user.name, user.email) == (
        "okta",
        "00u1",
        "Ada",
        "ada@example.com",
    )
    assert user.groups == frozenset({"users"})
    assert user.hosted_domain is None
    principal = await world.access.authenticate(finished.signed_in.secret, bearer=False)
    assert principal.user == user
    assert world.okta.requests == [
        "GET /oauth2/default/.well-known/openid-configuration",
        "POST /oauth2/default/token",
    ]


async def test_a_callback_is_used_once(world: World) -> None:
    url, state = await world.providers.begin("okta", redirect_uri=REDIRECT)
    code = world.okta.authorize(url, groups=["users"])
    await world.providers.finish("okta", redirect_uri=REDIRECT, state=state, code=code)

    with pytest.raises(SignInError) as again:
        await world.providers.finish(
            "okta", redirect_uri=REDIRECT, state=state, code=code
        )

    assert again.value.code is SignInErrorCode.EXPIRED


async def test_a_sign_in_older_than_ten_minutes_has_expired(world: World) -> None:
    url, state = await world.providers.begin("okta", redirect_uri=REDIRECT)
    code = world.okta.authorize(url, groups=["users"])
    world.clock.advance(timedelta(minutes=10))

    with pytest.raises(SignInError) as late:
        await world.providers.finish(
            "okta", redirect_uri=REDIRECT, state=state, code=code
        )

    assert late.value.code is SignInErrorCode.EXPIRED


async def test_a_provider_that_refuses_ends_the_sign_in(world: World) -> None:
    _, state = await world.providers.begin("okta", redirect_uri=REDIRECT)

    with pytest.raises(SignInError) as refused:
        await world.providers.finish(
            "okta", redirect_uri=REDIRECT, state=state, error="access_denied"
        )
    with pytest.raises(SignInError) as again:
        await world.providers.finish(
            "okta", redirect_uri=REDIRECT, state=state, code="x"
        )

    assert refused.value.code is SignInErrorCode.PROVIDER_REFUSED
    assert again.value.code is SignInErrorCode.EXPIRED


async def test_a_person_no_entry_admits_is_refused(world: World) -> None:
    with pytest.raises(SignInError) as refused:
        await world.sign_in(groups=["visitors"])

    assert refused.value.code is SignInErrorCode.NOT_ALLOWED
    assert await world.store.user_of("okta", "00u1") is None


@pytest.mark.parametrize(
    ("claims", "email", "admitted"),
    [
        (
            {"hd": "example.com", "email": "a@example.com", "email_verified": True},
            "a@example.com",
            True,
        ),
        ({"email": "Ada@gmail.com", "email_verified": True}, "Ada@gmail.com", True),
        ({"email": "ada@gmail.com", "email_verified": False}, None, False),
        ({"email": "ada@gmail.com", "email_verified": "true"}, "ada@gmail.com", True),
        # A personal account verified at a domain it does not own.
        ({"email": "ada@example.com", "email_verified": True}, None, False),
    ],
)
async def test_google_vouches_for_an_address_in_a_workspace_or_at_gmail(
    world: World, claims: dict[str, Any], email: str | None, admitted: bool
) -> None:
    url, state = await world.providers.begin("google", redirect_uri=REDIRECT)
    code = world.google.authorize(url, **claims)

    try:
        finished = await world.providers.finish(
            "google", redirect_uri=REDIRECT, state=state, code=code
        )
    except SignInError as refused:
        assert not admitted and refused.code is SignInErrorCode.NOT_ALLOWED
        return
    assert admitted
    assert finished.signed_in.user.email == email


async def test_google_s_short_issuer_is_accepted(world: World) -> None:
    finished = await world.sign_in(
        "google", iss="accounts.google.com", hd="example.com"
    )

    assert finished.signed_in.user.hosted_domain == "example.com"


def _shifted(clock: ManualClock, seconds: int) -> int:
    return int(clock().timestamp()) + seconds


@pytest.mark.parametrize(
    ("claims", "detail"),
    [
        (lambda c: {"iss": "https://evil.example.com"}, "iss"),
        (lambda c: {"iss": ["https://example.okta.com/oauth2/default"]}, "iss"),
        (lambda c: {"aud": "someone-else"}, "aud"),
        (lambda c: {"aud": ["okta-client", "other"]}, "azp"),
        (lambda c: {"azp": "other"}, "azp"),
        (lambda c: {"exp": _shifted(c, -61)}, "exp"),
        (lambda c: {"exp": True}, "exp"),
        (lambda c: {"iat": _shifted(c, 61)}, "iat"),
        (lambda c: {"nonce": "another"}, "nonce"),
        (lambda c: {"nonce": "ünïcode"}, "nonce"),
        (lambda c: {"sub": ""}, "sub"),
        (lambda c: {"sub": 12}, "sub"),
    ],
)
async def test_an_id_token_not_for_this_sign_in_is_refused(
    world: World, claims: Callable[[ManualClock], dict[str, Any]], detail: str
) -> None:
    with pytest.raises(SignInError) as refused:
        await world.sign_in(groups=["users"], **claims(world.clock))

    assert refused.value.code is SignInErrorCode.INVALID_ID_TOKEN
    assert detail in refused.value.detail


async def test_an_id_token_within_the_clock_skew_is_accepted(world: World) -> None:
    finished = await world.sign_in(
        groups=["users"],
        exp=_shifted(world.clock, -59),
        iat=_shifted(world.clock, 59),
        aud=["okta-client", "other"],
        azp="okta-client",
    )

    assert finished.signed_in.user.subject == "00u1"


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (400, {"error": "invalid_grant"}, SignInErrorCode.PROVIDER_REFUSED),
        (200, {"error": "access_denied"}, SignInErrorCode.PROVIDER_REFUSED),
        (502, {"error": "bad_gateway"}, SignInErrorCode.PROVIDER_UNAVAILABLE),
        (200, ["not", "an", "object"], SignInErrorCode.PROVIDER_UNAVAILABLE),
        (200, {"access_token": "x"}, SignInErrorCode.INVALID_ID_TOKEN),
        (200, {"id_token": "a.b"}, SignInErrorCode.INVALID_ID_TOKEN),
        (200, {"id_token": "a.!!!.c"}, SignInErrorCode.INVALID_ID_TOKEN),
        (200, {"id_token": "a.WzFd.c"}, SignInErrorCode.INVALID_ID_TOKEN),
    ],
)
async def test_what_the_token_endpoint_answers_wrongly_is_refused(
    world: World, status: int, body: Any, code: SignInErrorCode
) -> None:
    world.okta.token_answer = (status, body)

    with pytest.raises(SignInError) as refused:
        await world.sign_in(groups=["users"])

    assert refused.value.code is code


async def test_a_wrong_client_secret_is_refused_by_the_provider(world: World) -> None:
    world.okta.config = ProviderConfig(**{**_fields(OKTA), "client_secret": "other"})

    with pytest.raises(SignInError) as refused:
        await world.sign_in(groups=["users"])

    assert refused.value.code is SignInErrorCode.PROVIDER_REFUSED


def _fields(config: ProviderConfig) -> dict[str, Any]:
    return {name: getattr(config, name) for name in config.__dataclass_fields__}


async def test_a_failed_discovery_is_tried_again_and_a_success_is_kept(
    world: World,
) -> None:
    world.okta.discovery_status = 503

    with pytest.raises(SignInError) as down:
        await world.providers.begin("okta", redirect_uri=REDIRECT)
    world.okta.discovery_status = 200
    await world.sign_in(groups=["users"])
    await world.sign_in(groups=["users"])

    assert down.value.code is SignInErrorCode.PROVIDER_UNAVAILABLE
    assert (
        world.okta.requests.count(
            "GET /oauth2/default/.well-known/openid-configuration"
        )
        == 2
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("issuer", "https://other.okta.com"),
        ("authorization_endpoint", "http://example.okta.com/authorize"),
        ("token_endpoint", "ftp://example.okta.com/token"),
        ("token_endpoint", None),
    ],
)
async def test_a_discovery_document_that_cannot_be_trusted_is_refused(
    world: World, key: str, value: str | None
) -> None:
    world.okta.discovery[key] = value

    with pytest.raises(SignInError) as refused:
        await world.providers.begin("okta", redirect_uri=REDIRECT)

    assert refused.value.code is SignInErrorCode.PROVIDER_UNAVAILABLE


async def test_an_unreachable_provider_is_unavailable() -> None:
    world = World()

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    providers = Providers(
        world.access, {"okta": OKTA}, transport=httpx.MockTransport(down)
    )

    with pytest.raises(SignInError) as refused:
        await providers.begin("okta", redirect_uri=REDIRECT)

    assert refused.value.code is SignInErrorCode.PROVIDER_UNAVAILABLE


async def test_an_unknown_provider_is_refused(world: World) -> None:
    with pytest.raises(SignInError) as refused:
        await world.providers.begin("azure", redirect_uri=REDIRECT)

    assert refused.value.code is SignInErrorCode.UNKNOWN_PROVIDER


async def test_too_many_sign_ins_at_once_are_busy() -> None:
    world = World()
    world.access = Access(
        world.store,
        Registry([ONEBERTH_ROLES]),
        POLICY,
        clock=world.clock,
        max_pending_sign_ins=1,
    )
    providers = Providers(
        world.access, {"okta": OKTA}, transport=httpx.MockTransport(world.okta.handle)
    )
    await providers.begin("okta", redirect_uri=REDIRECT)

    with pytest.raises(SignInError) as busy:
        await providers.begin("okta", redirect_uri=REDIRECT)

    assert busy.value.code is SignInErrorCode.BUSY


@pytest.mark.parametrize(
    ("verifier", "challenge"),
    [
        # RFC 7636, appendix B.
        (
            "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        ),
    ],
)
def test_the_pkce_challenge_is_s256(verifier: str, challenge: str) -> None:
    assert pkce_challenge(verifier) == challenge
    assert hashlib.sha256(verifier.encode()).digest() == base64.urlsafe_b64decode(
        challenge + "="
    )
