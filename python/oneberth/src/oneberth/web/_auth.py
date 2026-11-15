# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The ``/auth`` routes (identity.md, "Routes").

    GET    /auth/session                    who is asking, their roles, the providers
    GET    /auth/login/{provider}           a sign-in begun: a redirect to the provider
    GET    /auth/callback/{provider}        a sign-in finished: the session cookie
    POST   /auth/tickets                    a ticket, for the launch secret alone
    GET    /auth/local?ticket=…             a ticket swapped for the session cookie
    POST   /auth/logout                     the session, or the device that asks, ends
    GET    /auth/tokens, POST, DELETE /{id} the person's tokens
    POST   /auth/pairings                   a pairing and its QR code
    POST   /auth/pairings/claim             the phone's claim of a code
    GET    /auth/pairings/{id}, DELETE      the browser's poll, and a cancel
    POST   /auth/pairings/{id}/approve      the number the phone shows
    GET    /auth/devices, DELETE /{id}      the person's linked devices
    GET    /auth/services, POST, DELETE     service tokens
    GET    /auth/services/roles             the roles a service token may hold

Each route parses the request, calls one method of ``Access`` and shapes the
answer. The core decides who may do what; its errors answer with the shape of
``_errors.py``. A failed sign-in goes back to the interface's sign-in page with
a code, and the detail goes to the log.
"""

from __future__ import annotations

import hmac
import logging
import uuid
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from oneberth.identity import (
    PENDING_SIGN_IN_LIFE,
    TICKETS_CREATE,
    TOKENS_MANAGE,
    AuthenticationError,
    DeviceDescription,
    DeviceSession,
    InvalidValueError,
    Pairing,
    PersonalToken,
    Principal,
    ServiceToken,
)
from oneberth.web._backend import Backend, backend_of
from oneberth.web._checks import Cookies, safe_return_to
from oneberth.web._component import Asking, Browsing, FreshBrowsing, permit
from oneberth.web._errors import Refusal, identity_refusal
from oneberth.web._qr import qr_svg

log = logging.getLogger("oneberth.web")

SIGN_IN_PAGE = "/ui/#/sign-in"
INTERFACE = "/ui/"
LINK_VERSION = 1


# What the routes answer.


class ProviderView(BaseModel):
    id: str
    title: str


class UserView(BaseModel):
    kind: Literal["user"] = "user"
    id: uuid.UUID
    name: str | None
    email: str | None
    provider: str


class ServiceView(BaseModel):
    kind: Literal["service"] = "service"
    id: uuid.UUID
    name: str


class PairingStateView(BaseModel):
    state: Literal["waiting", "claimed", "approved"]


class SessionView(BaseModel):
    """Who is asking. Never a 401: nobody is an answer."""

    mode: Literal["providers", "local"]
    providers: list[ProviderView]
    principal: UserView | ServiceView | None
    roles: list[str]
    pairing: PairingStateView | None = None
    """For a phone whose claim waits for the browser's approval."""


class TicketView(BaseModel):
    ticket: str
    """Works once, within a minute."""
    url: str
    """Where the window opens: ``/auth/local`` with the ticket."""
    expires_at: datetime


class TokenRequest(BaseModel):
    name: str = Field(max_length=200)


class TokenView(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    expires_at: datetime


class NewTokenView(TokenView):
    secret: str
    """Shown once."""


class TokenList(BaseModel):
    items: list[TokenView]


class DeviceView(BaseModel):
    id: uuid.UUID
    name: str
    platform: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime


class DeviceList(BaseModel):
    items: list[DeviceView]


class MintedPairingView(BaseModel):
    """The code is in the picture alone."""

    id: uuid.UUID
    expires_at: datetime
    qr_svg: str


class DeviceDescriptionView(BaseModel):
    name: str
    platform: str
    app_version: str | None


class PairingView(BaseModel):
    state: Literal["waiting", "claimed", "approved"]
    expires_at: datetime
    device: DeviceDescriptionView | None


class ClaimedDevice(BaseModel):
    """What the phone says of itself: data for the list of devices."""

    name: str = Field(min_length=1, max_length=64)
    platform: Literal["android", "ios", "desktop", "other"]
    app_version: str | None = Field(default=None, max_length=32)


class ClaimRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    device: ClaimedDevice


class ClaimView(BaseModel):
    secret: str
    """Inert until the person approves the number."""
    number: str
    expires_at: datetime


class ApproveRequest(BaseModel):
    number: str = Field(max_length=32)


class ServiceRequest(BaseModel):
    name: str = Field(max_length=200)
    role: str = Field(max_length=200)
    resource: str | None = Field(default=None, max_length=200)
    days: float | None = None
    """Days until it ends; ``None`` for none."""


class ServiceTokenView(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    resource: str | None
    created_at: datetime
    expires_at: datetime | None


class NewServiceTokenView(ServiceTokenView):
    secret: str
    """Shown once."""


class ServiceTokenList(BaseModel):
    items: list[ServiceTokenView]


class ServiceRoleView(BaseModel):
    name: str
    needs_resource: bool


class ServiceRoleList(BaseModel):
    items: list[ServiceRoleView]


def token_view(token: PersonalToken) -> TokenView:
    return TokenView(
        id=token.id,
        name=token.name,
        created_at=token.created_at,
        expires_at=token.expires_at,
    )


def device_view(device: DeviceSession) -> DeviceView:
    return DeviceView(
        id=device.id,
        name=device.device.name,
        platform=device.device.platform,
        created_at=device.created_at,
        last_used_at=device.last_used_at,
        expires_at=device.expires_at,
    )


def pairing_view(pairing: Pairing) -> PairingView:
    described = pairing.device
    return PairingView(
        state=pairing.state.value,
        expires_at=pairing.expires_at,
        device=None
        if described is None
        else DeviceDescriptionView(
            name=described.name,
            platform=described.platform,
            app_version=described.app_version,
        ),
    )


def service_view(token: ServiceToken) -> ServiceTokenView:
    return ServiceTokenView(
        id=token.id,
        name=token.name,
        role=token.grant.role,
        resource=token.grant.resource,
        created_at=token.created_at,
        expires_at=token.expires_at,
    )


def principal_view(principal: Principal) -> UserView | ServiceView:
    if principal.user is None:
        return ServiceView(id=principal.credential.id, name=principal.name)
    user = principal.user
    return UserView(
        id=user.id, name=user.name, email=user.email, provider=user.provider
    )


def link_url(public_url: str, code: str) -> str:
    """What the QR says: an address of the deployment, the code in its fragment,
    which a browser does not send and no server logs."""
    return f"{public_url}/#/link?{urlencode({'v': LINK_VERSION, 'c': code})}"


def set_cookie(
    cookies: Cookies,
    response: Response,
    name: str,
    value: str,
    life: timedelta | None,
) -> None:
    """``life`` ``None`` makes a cookie of the browser's session."""
    response.set_cookie(
        name,
        value,
        max_age=None if life is None else max(1, int(life.total_seconds())),
        path="/",
        secure=cookies.secure,
        httponly=True,
        samesite="lax",
    )


def clear_cookie(cookies: Cookies, response: Response, name: str) -> None:
    response.delete_cookie(
        name, path="/", secure=cookies.secure, httponly=True, samesite="lax"
    )


router = APIRouter(prefix="/auth", tags=["auth"])


# Who is asking, signing in and out.


@router.get("/session")
async def session(request: Request) -> SessionView:
    backend = backend_of(request)
    providers = [] if backend.providers is None else backend.providers.clients.values()
    answer = SessionView(
        mode="local" if backend.local else "providers",
        providers=[
            ProviderView(id=c.config.id, title=c.config.title) for c in providers
        ],
        principal=None,
        roles=[],
    )
    try:
        principal = await backend.principal(request)
    except AuthenticationError:
        bearer = request.headers.get("authorization", "").partition(" ")[2].strip()
        state = await backend.access.pairing_state(bearer) if bearer else None
        if state is not None:
            answer.pairing = PairingStateView(state=state.value)
        return answer
    answer.principal = principal_view(principal)
    answer.roles = sorted(principal.roles)
    return answer


def _signed_out(backend: Backend, code: str, detail: str) -> RedirectResponse:
    log.warning("sign-in refused, %s: %s", code, detail)
    response = RedirectResponse(
        f"{backend.public_url}{SIGN_IN_PAGE}?error={quote(code)}", status_code=303
    )
    clear_cookie(backend.cookies, response, backend.cookies.login)
    return response


# Navigations, not calls: out of the OpenAPI document.


@router.get("/login/{provider}", include_in_schema=False)
async def login(
    request: Request, provider: str, return_to: str | None = None
) -> Response:
    from oneberth.providers import SignInError, SignInErrorCode

    backend = backend_of(request)
    if backend.providers is None:
        return _signed_out(
            backend, SignInErrorCode.UNKNOWN_PROVIDER, "no provider is configured"
        )
    try:
        url, state = await backend.providers.begin(
            provider,
            redirect_uri=backend.config.redirect_uri(backend.name, provider),
            return_to=safe_return_to(return_to),
        )
    except SignInError as refused:
        return _signed_out(backend, refused.code, refused.detail)
    response = RedirectResponse(url, status_code=303)
    set_cookie(
        backend.cookies, response, backend.cookies.login, state, PENDING_SIGN_IN_LIFE
    )
    return response


@router.get("/callback/{provider}", include_in_schema=False)
async def callback(
    request: Request,
    provider: str,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> Response:
    from oneberth.providers import SignInError, SignInErrorCode

    backend = backend_of(request)
    if backend.providers is None:
        return _signed_out(
            backend, SignInErrorCode.UNKNOWN_PROVIDER, "no provider is configured"
        )
    cookie = request.cookies.get(backend.cookies.login)
    # As bytes: compare_digest refuses a str holding anything but ASCII.
    if (
        not state
        or not cookie
        or not hmac.compare_digest(cookie.encode(), state.encode())
    ):
        return _signed_out(
            backend,
            SignInErrorCode.STATE_MISMATCH,
            "the state is not the one this browser began",
        )
    try:
        done = await backend.providers.finish(
            provider,
            redirect_uri=backend.config.redirect_uri(backend.name, provider),
            state=state,
            code=code,
            error=error,
        )
    except SignInError as refused:
        return _signed_out(backend, refused.code, refused.detail)
    signed_in = done.signed_in
    log.info("user %s signed in with %s", signed_in.user.id, provider)
    response = RedirectResponse(
        f"{backend.public_url}{done.return_to}", status_code=303
    )
    clear_cookie(backend.cookies, response, backend.cookies.login)
    session_ = signed_in.session
    set_cookie(
        backend.cookies,
        response,
        backend.cookies.session,
        signed_in.secret,
        session_.expires_at - session_.created_at,
    )
    return response


@router.post("/tickets", status_code=201, dependencies=[permit(TICKETS_CREATE)])
async def create_ticket(request: Request, principal: Asking) -> TicketView:
    backend = backend_of(request)
    ticket, expires_at = await backend.access.create_ticket(principal)
    return TicketView(
        ticket=ticket, url=backend.ticket_url(ticket), expires_at=expires_at
    )


@router.get("/local", include_in_schema=False)
async def local(request: Request, ticket: str | None = None) -> Response:
    """The window's first page: the ticket swapped for the session cookie, and
    the interface. A ticket refused lands on the interface too, which says to
    start again."""
    backend = backend_of(request)
    if not backend.local:
        raise Refusal(404, "NotFound", "the local mode is off")
    response = RedirectResponse(f"{backend.public_url}{INTERFACE}", status_code=303)
    try:
        signed_in = await backend.access.take_ticket(ticket or "")
    except AuthenticationError as refused:
        log.warning("a ticket was refused: %s", refused)
        return response
    log.info("the local user %s signed in with a ticket", signed_in.user.id)
    # A cookie of the browser's session: the local session lasts until the
    # application stops, and the window closing stops it.
    set_cookie(
        backend.cookies, response, backend.cookies.session, signed_in.secret, None
    )
    return response


@router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    backend = backend_of(request)
    response = Response(status_code=204)
    try:
        principal = await backend.principal(request)
    except AuthenticationError as error:
        response = identity_refusal(error).answer()
    else:
        await backend.access.sign_out(principal)
    if backend.cookies.session in request.cookies:
        clear_cookie(backend.cookies, response, backend.cookies.session)
    return response


# Personal tokens.


@router.get("/tokens")
async def list_tokens(request: Request, principal: Asking) -> TokenList:
    tokens = await backend_of(request).access.personal_tokens(principal)
    return TokenList(items=[token_view(t) for t in tokens])


@router.post("/tokens", status_code=201)
async def mint_token(
    request: Request, body: TokenRequest, principal: FreshBrowsing
) -> NewTokenView:
    secret, token = await backend_of(request).access.mint_personal_token(
        principal, body.name.strip()
    )
    return NewTokenView(**token_view(token).model_dump(), secret=secret)


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    request: Request, token_id: uuid.UUID, principal: Browsing
) -> None:
    await backend_of(request).access.revoke_personal_token(principal, token_id)


# Pairing a phone, and the linked devices.


@router.post("/pairings", status_code=201)
async def mint_pairing(request: Request, principal: FreshBrowsing) -> MintedPairingView:
    backend = backend_of(request)
    code, pairing = await backend.access.begin_pairing(principal)
    return MintedPairingView(
        id=pairing.id,
        expires_at=pairing.expires_at,
        qr_svg=qr_svg(link_url(backend.public_url, code)),
    )


@router.post("/pairings/claim")
async def claim_pairing(request: Request, body: ClaimRequest) -> ClaimView:
    device = DeviceDescription(
        body.device.name, body.device.platform, body.device.app_version
    )
    claimed = await backend_of(request).access.claim_pairing(body.code, device)
    return ClaimView(
        secret=claimed.secret, number=claimed.number, expires_at=claimed.expires_at
    )


@router.get("/pairings/{pairing_id}")
async def pairing_state(
    request: Request, pairing_id: uuid.UUID, principal: Browsing
) -> PairingView:
    pairing = await backend_of(request).access.pairing(principal, pairing_id)
    return pairing_view(pairing)


@router.post("/pairings/{pairing_id}/approve")
async def approve_pairing(
    request: Request, pairing_id: uuid.UUID, body: ApproveRequest, principal: Browsing
) -> DeviceView:
    device = await backend_of(request).access.approve_pairing(
        principal, pairing_id, body.number
    )
    log.info("device %s linked to user %s", device.id, device.user_id)
    return device_view(device)


@router.delete("/pairings/{pairing_id}", status_code=204)
async def refuse_pairing(
    request: Request, pairing_id: uuid.UUID, principal: Browsing
) -> None:
    await backend_of(request).access.refuse_pairing(principal, pairing_id)


@router.get("/devices")
async def list_devices(request: Request, principal: Asking) -> DeviceList:
    devices = await backend_of(request).access.devices(principal)
    return DeviceList(items=[device_view(d) for d in devices])


@router.delete("/devices/{device_id}", status_code=204)
async def remove_device(
    request: Request, device_id: uuid.UUID, principal: Browsing
) -> None:
    await backend_of(request).access.remove_device(principal, device_id)


# Service tokens (identity.md, "Service tokens"). The core decides who may:
# a principal with oneberth/tokens:manage lists them, and an admin's browser
# session or the launch secret creates and revokes them. An admin's bearer is
# answered 403.


@router.get("/services")
async def list_services(request: Request, principal: Asking) -> ServiceTokenList:
    tokens = await backend_of(request).access.service_tokens(by=principal)
    return ServiceTokenList(items=[service_view(t) for t in tokens])


@router.get("/services/roles")
async def list_service_roles(request: Request, principal: Asking) -> ServiceRoleList:
    backend = backend_of(request)
    backend.access.authorize(principal, TOKENS_MANAGE)
    return ServiceRoleList(
        items=[
            ServiceRoleView(name=role.name, needs_resource=role.resource is not None)
            for role in backend.registry.service_roles
        ]
    )


@router.post("/services", status_code=201)
async def create_service(
    request: Request, body: ServiceRequest, principal: Asking
) -> NewServiceTokenView:
    try:
        expires_in = None if body.days is None else timedelta(days=body.days)
    except (OverflowError, ValueError):
        raise InvalidValueError(f"days: {body.days} is not a number of days") from None
    secret, token = await backend_of(request).access.create_service_token(
        body.name,
        body.role,
        resource=body.resource or None,
        expires_in=expires_in,
        by=principal,
    )
    return NewServiceTokenView(**service_view(token).model_dump(), secret=secret)


@router.delete("/services/{token_id}", status_code=204)
async def revoke_service(
    request: Request, token_id: uuid.UUID, principal: Asking
) -> None:
    await backend_of(request).access.revoke_service_token(token_id, by=principal)
