# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""Sign-in through an OpenID Connect provider, on ``httpx``: the ``providers`` extra.

One generic client serves Google and Okta. The flow is the authorization code
flow with ``state``, ``nonce`` and PKCE (S256). Discovery happens at a
provider's first sign-in, not at start-up. A success is kept for the life of
the client, and a failure is tried again at the next sign-in.

The ID token arrives from the token endpoint over TLS. Its claims are checked:
``iss``, ``aud``, ``azp``, ``exp``, ``iat``, ``nonce`` and ``sub``. Its
signature is left unverified, as OpenID Connect Core 3.1.3.7 allows for this
flow. That is sound only over TLS, so the endpoints that discovery names must
be ``https``, loopback excepted.

``Providers`` drives a sign-in for the web part: ``begin`` gives the URL to send
the browser to, and ``finish`` turns the callback into a session. Every failure
is a ``SignInError`` with a fixed code, which is all a browser is told. The
detail is for the log.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx

from oneberth.config import GOOGLE_ISSUER, ProviderConfig, is_loopback, normalise_issuer
from oneberth.identity import (
    Access,
    AuthenticationError,
    BusyError,
    Clock,
    Identity,
    SignedIn,
    SignInRefusedError,
    system_clock,
)

CLOCK_SKEW_SECONDS = 60.0
"""How far ``exp`` and ``iat`` may be off this machine's clock."""

GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})

DISCOVERY_PATH = "/.well-known/openid-configuration"

TOTAL_SECONDS = 20.0
"""The bound on one request, its body included."""

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class SignInErrorCode(StrEnum):
    """Why a sign-in did not complete, as the browser is told it."""

    EXPIRED = "expired"
    """The sign-in is unknown, used already, or older than ten minutes."""
    STATE_MISMATCH = "state_mismatch"
    """The callback's state is not the one this browser began. The web part's check."""
    NOT_ALLOWED = "not_allowed"
    """No allow entry admits the person."""
    UNKNOWN_PROVIDER = "unknown_provider"
    BUSY = "busy"
    """Too many sign-ins are in progress."""
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    """Discovery or the token endpoint could not be reached, or answered wrongly."""
    PROVIDER_REFUSED = "provider_refused"
    """The provider refused the sign-in, or the code."""
    INVALID_ID_TOKEN = "invalid_id_token"
    """The ID token is not one for this sign-in."""


class SignInError(Exception):
    """A sign-in that cannot complete. ``code`` is what the browser is told."""

    def __init__(self, code: SignInErrorCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


def pkce_challenge(verifier: str) -> str:
    """The S256 code challenge of a PKCE verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OidcClient:
    """One configured provider, reached over ``httpx``.

    ``transport`` replaces the network, for a stand-in provider in tests.
    """

    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock = system_clock,
    ) -> None:
        self.config = config
        self._transport = transport
        self._clock = clock
        self._discovery: Mapping[str, Any] | None = None
        self._published_issuer: str | None = None
        self._discovering = asyncio.Lock()

    async def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, verifier: str
    ) -> str:
        """Where to send the browser to sign in."""
        endpoint: str = (await self._discovered())["authorization_endpoint"]
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.config.client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(self.config.scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": pkce_challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
        separator = "&" if urlsplit(endpoint).query else "?"
        return f"{endpoint}{separator}{query}"

    async def identity(
        self, *, redirect_uri: str, code: str, nonce: str, verifier: str
    ) -> Identity:
        """Swap ``code`` for an ID token, check it, and say who signed in."""
        endpoint: str = (await self._discovered())["token_endpoint"]
        # RFC 6749 2.3.1: each half form-encoded before they are joined.
        pair = (
            f"{quote(self.config.client_id, safe='')}:"
            f"{quote(self.config.client_secret, safe='')}"
        )
        basic = base64.b64encode(pair.encode("utf-8")).decode("ascii")
        response = await self._send(
            "POST",
            endpoint,
            f"the token endpoint of {self.config.id}",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
            headers={"accept": "application/json", "authorization": f"Basic {basic}"},
        )
        body = _json_object(response)
        status = response.status_code
        if status >= 500:
            raise SignInError(
                SignInErrorCode.PROVIDER_UNAVAILABLE,
                f"the token endpoint answered {status}",
            )
        if status >= 400 or (body is not None and "error" in body):
            said = body or {}
            raise SignInError(
                SignInErrorCode.PROVIDER_REFUSED,
                f"the token endpoint answered {status}: error={said.get('error')!r}"
                f" error_description={said.get('error_description')!r}",
            )
        if status != 200 or body is None:
            raise SignInError(
                SignInErrorCode.PROVIDER_UNAVAILABLE,
                f"the token endpoint answered {status} with no JSON object",
            )
        claims = self._checked(_claims(body.get("id_token")), nonce)
        return self._identity(claims)

    def _checked(self, claims: Mapping[str, Any], nonce: str) -> Mapping[str, Any]:
        # iss is compared exactly with the issuer the provider publishes, which
        # may differ from the configured form by a trailing slash or case.
        issuers = {self.config.issuer}
        if self._published_issuer is not None:
            issuers.add(self._published_issuer)
        if self.config.issuer == GOOGLE_ISSUER:
            issuers.add("accounts.google.com")  # Google documents both forms
        issuer = claims.get("iss")
        if not isinstance(issuer, str) or issuer not in issuers:
            raise _invalid(f"iss {issuer!r}")
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience
        if not isinstance(audiences, list) or self.config.client_id not in audiences:
            raise _invalid(f"aud {audience!r}")
        azp = claims.get("azp")
        if (len(audiences) > 1 or azp is not None) and azp != self.config.client_id:
            raise _invalid(f"azp {azp!r}")
        now = self._clock().timestamp()
        expires, issued = _number(claims.get("exp")), _number(claims.get("iat"))
        if expires is None or expires + CLOCK_SKEW_SECONDS <= now:
            raise _invalid(f"exp {claims.get('exp')!r}, now {now}")
        if issued is None or issued - CLOCK_SKEW_SECONDS > now:
            raise _invalid(f"iat {claims.get('iat')!r}, now {now}")
        got = claims.get("nonce")
        # As bytes: compare_digest refuses a str holding anything but ASCII.
        if not isinstance(got, str) or not hmac.compare_digest(
            got.encode(), nonce.encode()
        ):
            raise _invalid("the nonce is not this sign-in's")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise _invalid(f"sub {subject!r}")
        return claims

    def _identity(self, claims: Mapping[str, Any]) -> Identity:
        email = _text(claims.get("email"))
        verified = claims.get("email_verified") in (True, "true")
        # hd is Google's, and names a Workspace there alone. Another provider
        # may send a claim of that name holding anything.
        hosted_domain = _text(claims.get("hd")) if self.config.is_google else None
        if self.config.is_google and email is not None:
            # Google verifies a personal account's address at any domain. An
            # address is the account's own only in a Workspace, whose domains
            # were proved, or at Gmail, which never hands one over.
            domain = email.rpartition("@")[2].lower()
            verified = verified and (
                hosted_domain is not None or domain in GMAIL_DOMAINS
            )
        groups: frozenset[str] = frozenset()
        if self.config.groups_claim is not None:
            raw = claims.get(self.config.groups_claim)
            if isinstance(raw, str):
                groups = frozenset({raw})
            elif isinstance(raw, list):
                groups = frozenset(g for g in raw if isinstance(g, str))
        return Identity(
            provider=self.config.id,
            subject=claims["sub"],
            name=_text(claims.get("name")),
            email=email if verified else None,
            hosted_domain=hosted_domain,
            groups=groups,
        )

    async def _discovered(self) -> Mapping[str, Any]:
        if self._discovery is not None:
            return self._discovery
        async with self._discovering:
            if self._discovery is None:
                self._discovery = await self._discover()
            return self._discovery

    async def _discover(self) -> Mapping[str, Any]:
        what = f"discovery of {self.config.id}"
        url = self.config.issuer + DISCOVERY_PATH
        response = await self._send(
            "GET", url, what, headers={"accept": "application/json"}
        )
        document = _json_object(response)
        if response.status_code != 200 or document is None:
            raise SignInError(
                SignInErrorCode.PROVIDER_UNAVAILABLE,
                f"{what} answered {response.status_code} with no JSON object",
            )
        issuer = document.get("issuer")
        if not isinstance(issuer, str) or _normalised(issuer) != self.config.issuer:
            raise SignInError(
                SignInErrorCode.PROVIDER_UNAVAILABLE,
                f"{what} names the issuer {issuer!r}, not {self.config.issuer!r}",
            )
        for key in ("authorization_endpoint", "token_endpoint"):
            endpoint = document.get(key)
            if not isinstance(endpoint, str) or not _protected(endpoint):
                raise SignInError(
                    SignInErrorCode.PROVIDER_UNAVAILABLE,
                    f"{what} names {key} {endpoint!r}: neither https nor loopback",
                )
        self._published_issuer = issuer
        return document

    async def _send(
        self, method: str, url: str, what: str, **request: Any
    ) -> httpx.Response:
        try:
            async with (
                asyncio.timeout(TOTAL_SECONDS),
                httpx.AsyncClient(
                    transport=self._transport, timeout=_TIMEOUT, follow_redirects=False
                ) as http,
            ):
                return await http.request(method, url, **request)
        except (httpx.HTTPError, httpx.InvalidURL, TimeoutError) as error:
            raise SignInError(
                SignInErrorCode.PROVIDER_UNAVAILABLE,
                f"{what} could not be reached: {error!r}",
            ) from None


@dataclass(frozen=True, slots=True)
class Finished:
    """A sign-in through a provider, done: the session, and where to go now."""

    signed_in: SignedIn
    return_to: str
    """As the web part gave it to ``begin``."""


class Providers:
    """The configured providers of a backend, and the sign-in through them.

    The web part calls ``begin`` from ``GET /auth/login/{provider}`` and
    ``finish`` from ``GET /auth/callback/{provider}``.
    """

    def __init__(
        self,
        access: Access,
        providers: Mapping[str, ProviderConfig],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._access = access
        self._clients = {
            provider_id: OidcClient(config, transport=transport, clock=access.now)
            for provider_id, config in providers.items()
        }

    @property
    def clients(self) -> Mapping[str, OidcClient]:
        return self._clients

    def client(self, provider: str) -> OidcClient:
        found = self._clients.get(provider)
        if found is None:
            raise SignInError(
                SignInErrorCode.UNKNOWN_PROVIDER,
                f"no provider {provider!r} is configured",
            )
        return found

    async def begin(
        self, provider: str, *, redirect_uri: str, return_to: str = "/"
    ) -> tuple[str, str]:
        """Begin a sign-in: the provider's URL to send the browser to, and the
        ``state``, which the web part may bind to the browser."""
        client = self.client(provider)
        try:
            state, pending = await self._access.begin_sign_in(
                provider, return_to=return_to
            )
        except BusyError as error:
            raise SignInError(SignInErrorCode.BUSY, str(error)) from None
        url = await client.authorization_url(
            redirect_uri=redirect_uri,
            state=state,
            nonce=pending.nonce,
            verifier=pending.verifier,
        )
        return url, state

    async def finish(
        self,
        provider: str,
        *,
        redirect_uri: str,
        state: str,
        code: str | None = None,
        error: str | None = None,
    ) -> Finished:
        """Turn the provider's callback into a session.

        ``state``, ``code`` and ``error`` are the callback's query parameters.
        The sign-in is taken first, so a callback is used once whatever it says.
        """
        client = self.client(provider)
        try:
            pending = await self._access.take_sign_in(provider, state)
        except AuthenticationError as failure:
            raise SignInError(SignInErrorCode.EXPIRED, str(failure)) from None
        if error is not None or not code:
            raise SignInError(
                SignInErrorCode.PROVIDER_REFUSED,
                f"the provider sent back error={error!r} and no code",
            )
        identity = await client.identity(
            redirect_uri=redirect_uri,
            code=code,
            nonce=pending.nonce,
            verifier=pending.verifier,
        )
        try:
            signed_in = await self._access.sign_in(identity)
        except SignInRefusedError as refused:
            raise SignInError(SignInErrorCode.NOT_ALLOWED, str(refused)) from None
        return Finished(signed_in, pending.return_to)


def _invalid(detail: str) -> SignInError:
    return SignInError(SignInErrorCode.INVALID_ID_TOKEN, detail)


def _normalised(issuer: str) -> str | None:
    try:
        return normalise_issuer(issuer)
    except ValueError:
        return None


def _protected(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme == "https":
        return bool(parts.hostname)
    return parts.scheme == "http" and is_loopback(parts.hostname or "")


def _claims(id_token: object) -> Mapping[str, Any]:
    """The claims of an ID token, its signature unverified."""
    if not isinstance(id_token, str):
        raise _invalid("the token response has no id_token")
    pieces = id_token.split(".")
    if len(pieces) != 3:
        raise _invalid("the id_token is not a JWT")
    try:
        payload = base64.urlsafe_b64decode(pieces[1] + "=" * (-len(pieces[1]) % 4))
        claims = json.loads(payload)
    except (binascii.Error, ValueError, RecursionError) as error:
        raise _invalid(f"the id_token cannot be read: {error}") from None
    if not isinstance(claims, dict):
        raise _invalid("the id_token's claims are not an object")
    return claims


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        body = json.loads(response.content)
    except (ValueError, RecursionError):
        return None
    return body if isinstance(body, dict) else None


def _number(value: object) -> float | None:
    """A time claim as a number: not a bool, a NaN or an infinity."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
