# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""Who is asking, and may that principal do this.

``Access`` holds the rules of identity.md on a store, a registry of roles and a
policy: signing in, the check of every credential at every use, minting and
removing credentials, pairing a phone, service tokens and the sweep. It reads
the time from its injected clock, and hands the store every id and every time.
"""

from __future__ import annotations

import math
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from oneberth.identity._allow import Policy, roles_of
from oneberth.identity._clock import Clock, system_clock
from oneberth.identity._errors import (
    AuthenticationError,
    BearerRefusedError,
    BusyError,
    FreshSignInRequiredError,
    InvalidValueError,
    NotClaimedError,
    NotFoundError,
    PermissionDeniedError,
    SignInRefusedError,
    WrongNumberError,
)
from oneberth.identity._records import (
    Approval,
    Credential,
    DeviceDescription,
    DeviceSession,
    Identity,
    Pairing,
    PairingState,
    PendingSignIn,
    PersonalToken,
    ServiceToken,
    Session,
    User,
)
from oneberth.identity._roles import TOKENS_MANAGE, Grant, Registry
from oneberth.identity._secrets import (
    MAX_SECRET_LENGTH,
    CredentialKind,
    kind_of,
    new_secret,
    random_secret,
    secret_hash,
)
from oneberth.identity._store import IdentityStore

DEFAULT_SESSION_HOURS = 12.0
DEFAULT_DEVICE_DAYS = 30.0
PERSONAL_TOKEN_LIFE = timedelta(days=90)
FRESH_SIGN_IN = timedelta(minutes=10)
"""How young a browser session must be to mint a person's credential."""
PENDING_SIGN_IN_LIFE = timedelta(minutes=10)
MAX_PENDING_SIGN_INS = 10_000
"""How many sign-ins may be in progress at once. Anyone may begin one, so this
keeps a flood of them from growing the store without end."""
PAIRING_LIFE = timedelta(minutes=2)
"""From the mint, and again from the claim, so there is time to type the number."""
PAIRINGS_PER_USER = 3
NUMBER_DIGITS = 6
ALLOW_CHECK_EVERY = timedelta(minutes=1)
"""How long a user's pass of the allow list is believed before it is checked again."""
RECENT_CHECKS_KEPT = 4096
"""How many passes are kept before the stale ones are dropped."""
SWEEP_EVERY = timedelta(minutes=1)
"""How often, at most, a sign-in begun sweeps the expired rows."""
MAX_LIFE = timedelta(days=5 * 366)
"""The longest life a credential may be given."""

LOCAL_PROVIDER = "!local"
"""The provider of the local user. No configured provider is spelt so."""

_SERVICE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
_MAX_TOKEN_NAME = 100


class Operator:
    """The operator at the command line, who acts on the store directly.
    ``OPERATOR`` is its one instance."""

    def __repr__(self) -> str:
        return "OPERATOR"


OPERATOR = Operator()


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is asking: a user, through one credential, or a service."""

    credential: Credential
    grants: frozenset[Grant]
    bearer: bool
    """Whether the credential came as a bearer. A forwarded session is a bearer."""
    user: User | None = None
    """The user; ``None`` for a service."""

    @property
    def kind(self) -> CredentialKind:
        return self.credential.kind

    @property
    def is_service(self) -> bool:
        return self.user is None

    @property
    def is_browser_session(self) -> bool:
        """A session sent as a cookie: what mints and removes a person's credentials."""
        return self.credential.kind is CredentialKind.SESSION and not self.bearer

    @property
    def name(self) -> str:
        """A person's name, email or subject, or a service token's name."""
        if isinstance(self.credential, ServiceToken):
            return self.credential.name
        assert self.user is not None
        return self.user.name or self.user.email or self.user.subject

    @property
    def roles(self) -> frozenset[str]:
        return frozenset(grant.role for grant in self.grants)


@dataclass(frozen=True, slots=True)
class SignedIn:
    """A sign-in done: the session's secret for the cookie, and who it names."""

    secret: str
    principal: Principal

    @property
    def session(self) -> Session:
        assert isinstance(self.principal.credential, Session)
        return self.principal.credential

    @property
    def user(self) -> User:
        assert self.principal.user is not None
        return self.principal.user


@dataclass(frozen=True, slots=True)
class Claimed:
    """What a phone gets for a code: the claim secret, inert until approved, and
    the number to show."""

    secret: str
    number: str
    expires_at: datetime


def is_fresh(signed_in_at: datetime, now: datetime) -> bool:
    """Whether a session signed in at ``signed_in_at`` may mint at ``now``."""
    return timedelta(0) <= now - signed_in_at < FRESH_SIGN_IN


def typed_number(typed: str) -> str | None:
    """The six digits a person typed, with or without spaces; ``None`` otherwise."""
    digits = typed.replace(" ", "")
    if len(digits) == NUMBER_DIGITS and digits.isascii() and digits.isdigit():
        return digits
    return None


def is_service_name(text: str) -> bool:
    """Whether ``text`` may name a service token: letters, digits, ``_ . -``."""
    return _SERVICE_NAME.fullmatch(text) is not None


def is_token_name(text: str) -> bool:
    """Whether ``text`` may name a personal token: printable, up to 100 characters."""
    return (
        0 < len(text) <= _MAX_TOKEN_NAME and text.isprintable() and not text.isspace()
    )


def life(value: float, unit: str, what: str) -> timedelta:
    """``value`` hours or days as a life to give ``what``; ``InvalidValueError``
    unless it is over 0 and at most ``MAX_LIFE``."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise InvalidValueError(f"{what} must be a number of {unit} over 0")
    span = timedelta(hours=value) if unit == "hours" else timedelta(days=value)
    return check_life(span, what)


def check_life(span: timedelta, what: str) -> timedelta:
    if not timedelta(0) < span <= MAX_LIFE:
        raise InvalidValueError(
            f"{what} must be over 0 and at most {MAX_LIFE.days} days"
        )
    return span


class Access:
    """Users, credentials and roles, on one store, under one policy."""

    def __init__(
        self,
        store: IdentityStore,
        registry: Registry,
        policy: Policy | None = None,
        *,
        clock: Clock = system_clock,
        session_hours: float = DEFAULT_SESSION_HOURS,
        device_days: float = DEFAULT_DEVICE_DAYS,
        max_pending_sign_ins: int = MAX_PENDING_SIGN_INS,
    ) -> None:
        policy = Policy() if policy is None else policy
        policy.check(registry)
        if max_pending_sign_ins < 1:
            raise InvalidValueError("at least one sign-in must be allowed at once")
        self._store = store
        self._registry = registry
        self._policy = policy
        self._clock = clock
        self._session_life = life(session_hours, "hours", "session_hours")
        self._device_life = life(device_days, "days", "device_days")
        self._max_pending = max_pending_sign_ins
        self._checks: dict[uuid.UUID, tuple[frozenset[Grant], datetime]] = {}
        self._swept_at: datetime | None = None

    @property
    def store(self) -> IdentityStore:
        return self._store

    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def policy(self) -> Policy:
        return self._policy

    @property
    def session_life(self) -> timedelta:
        return self._session_life

    @property
    def device_life(self) -> timedelta:
        return self._device_life

    def now(self) -> datetime:
        return self._clock()

    # Signing in through a provider.

    async def begin_sign_in(
        self, provider: str, *, return_to: str = "/"
    ) -> tuple[str, PendingSignIn]:
        """Start a sign-in with ``provider``: its ``state``, and what is kept for it.

        The ``state`` goes to the provider and comes back to the callback, which
        hands it to ``take_sign_in``. Raises ``BusyError`` when too many
        sign-ins are in progress. Expired rows go as people sign in, at most
        once every ``SWEEP_EVERY``, so the store needs no job of its own.
        """
        now = self.now()
        if self._swept_at is None or now - self._swept_at >= SWEEP_EVERY:
            await self.sweep()
        state = random_secret()
        pending = PendingSignIn(
            state_hash=secret_hash(state),
            provider=provider,
            nonce=random_secret(),
            # 64 characters, within the 43 to 128 that PKCE allows.
            verifier=secrets.token_urlsafe(48),
            return_to=return_to,
            created_at=now,
            expires_at=now + PENDING_SIGN_IN_LIFE,
        )
        if not await self._store.add_pending_sign_in(
            pending, now, limit=self._max_pending
        ):
            raise BusyError("too many sign-ins are in progress; try again in a minute")
        return state, pending

    async def take_sign_in(self, provider: str, state: str) -> PendingSignIn:
        """The sign-in ``state`` began, once. A second take is refused."""
        if not state or len(state) > MAX_SECRET_LENGTH:
            raise AuthenticationError("the sign-in is not one this deployment began")
        pending = await self._store.take_pending_sign_in(secret_hash(state), self.now())
        if pending is None:
            raise AuthenticationError("the sign-in is unknown, used already or expired")
        if pending.provider != provider:
            raise AuthenticationError(
                f"the sign-in was begun with another provider than {provider!r}"
            )
        return pending

    async def sign_in(self, identity: Identity) -> SignedIn:
        """A session for ``identity``, if an allow entry admits it.

        The first sign-in creates the user, and a later one refreshes it.
        A refusal ends every credential of that identity, and raises
        ``SignInRefusedError``.
        """
        if identity.provider == LOCAL_PROVIDER:
            raise InvalidValueError(f"no provider signs anyone in as {LOCAL_PROVIDER}")
        now = self.now()
        roles = roles_of(identity, self._policy, self._registry.default_roles)
        if roles is None:
            await self._store.delete_credentials_of_identity(
                identity.provider, identity.subject
            )
            who = identity.email or identity.subject
            raise SignInRefusedError(
                f"no allow entry of {identity.provider!r} admits {who!r}"
            )
        user = await self._store.upsert_user(identity, user_id=uuid.uuid4(), now=now)
        secret = new_secret(CredentialKind.SESSION)
        session = Session(
            id=uuid.uuid4(),
            user_id=user.id,
            secret_hash=secret_hash(secret),
            created_at=now,
            expires_at=now + self._session_life,
        )
        await self._store.add_session(session)
        grants = _grants(roles)
        self._passed(user.id, grants, now)
        return SignedIn(secret, Principal(session, grants, bearer=False, user=user))

    # Who is asking.

    async def authenticate(self, secret: str, *, bearer: bool) -> Principal:
        """The principal a secret names, sent as a bearer or as the session cookie.

        The prefix picks where the secret is looked up. A credential of a user
        the allow list no longer admits is refused, and every credential of
        that user ends. Raises ``AuthenticationError`` for any refusal.
        """
        kind = kind_of(secret)
        if kind is None:
            raise AuthenticationError("the credential is not one oneberth issues")
        if not bearer and kind is not CredentialKind.SESSION:
            raise AuthenticationError("the session cookie holds a session alone")
        now = self.now()
        hashed = secret_hash(secret)
        found: tuple[User, Session | PersonalToken | DeviceSession] | None
        match kind:
            case CredentialKind.SERVICE_TOKEN:
                token = await self._store.service_token_by_hash(hashed, now)
                if token is None:
                    raise AuthenticationError(
                        "the service token is unknown, revoked or expired"
                    )
                return Principal(token, frozenset({token.grant}), bearer=True)
            case CredentialKind.SESSION:
                found = await self._store.session_by_hash(hashed, now)
            case CredentialKind.PERSONAL_TOKEN:
                found = await self._store.personal_token_by_hash(hashed, now)
            case CredentialKind.DEVICE:
                found = await self._store.device_by_hash(hashed, now)
        if found is None:
            raise AuthenticationError(
                f"the {kind.value.replace('_', ' ')} is unknown, ended or expired"
            )
        user, credential = found
        grants = await self._grants_of(user, now)
        return Principal(credential, grants, bearer=bearer, user=user)

    async def _grants_of(self, user: User, now: datetime) -> frozenset[Grant]:
        """The user's grants under the policy as it is now, believed for a minute.

        A user the allow list refuses loses every credential, so an entry put
        back revives none.
        """
        checked = self._checks.get(user.id)
        if checked is not None and timedelta(0) <= now - checked[1] < ALLOW_CHECK_EVERY:
            return checked[0]
        roles = roles_of(user.identity, self._policy, self._registry.default_roles)
        if roles is None:
            self._checks.pop(user.id, None)
            await self._store.delete_credentials_of(user.id)
            raise AuthenticationError("the allow list no longer admits this person")
        grants = _grants(roles)
        self._passed(user.id, grants, now)
        return grants

    def _passed(
        self, user_id: uuid.UUID, grants: frozenset[Grant], now: datetime
    ) -> None:
        self._checks[user_id] = (grants, now)
        if len(self._checks) > RECENT_CHECKS_KEPT:
            for stale in [
                key
                for key, (_, at) in self._checks.items()
                if not timedelta(0) <= now - at < ALLOW_CHECK_EVERY
            ]:
                del self._checks[stale]

    def allows(
        self, principal: Principal, permission: str, resource: str | None = None
    ) -> bool:
        """Whether ``principal`` holds ``permission`` on ``resource``.

        ``resource`` is ``None`` for a request that names none
        (``Registry.allows``).
        """
        return self._registry.allows(principal.grants, permission, resource)

    def authorize(
        self, principal: Principal, permission: str, resource: str | None = None
    ) -> None:
        """Raise ``PermissionDeniedError`` unless ``principal`` holds ``permission``."""
        if not self.allows(principal, permission, resource):
            on = "" if resource is None else f" on {resource!r}"
            raise PermissionDeniedError(f"{principal.name} may not {permission}{on}")

    async def sign_out(self, principal: Principal) -> None:
        """End the browser's session, or the device that asks. Nothing else ends:
        a token is revoked in the browser, and a forwarded session removes nothing."""
        credential = principal.credential
        if isinstance(credential, Session) and not principal.bearer:
            await self._store.delete_session(credential.secret_hash)
        elif isinstance(credential, DeviceSession):
            await self._store.delete_device(credential.user_id, credential.id)

    async def end_sessions(self) -> int:
        """Sign everyone out; how many sessions there were. The operator's."""
        return await self._store.delete_sessions()

    def _browsing(self, principal: Principal, *, fresh: bool = False) -> User:
        """The user of a browser session; ``fresh`` asks for a young one too."""
        if principal.user is None or not principal.is_browser_session:
            raise BearerRefusedError(
                "a person's credentials are minted and removed from their browser"
            )
        if fresh and not is_fresh(principal.credential.created_at, self.now()):
            raise FreshSignInRequiredError(
                "sign in again: the session must be younger than "
                f"{FRESH_SIGN_IN.seconds // 60} minutes"
            )
        return principal.user

    @staticmethod
    def _person(principal: Principal) -> User:
        if principal.user is None:
            raise PermissionDeniedError("a service has no personal credentials")
        return principal.user

    # Personal tokens.

    async def mint_personal_token(
        self, principal: Principal, name: str
    ) -> tuple[str, PersonalToken]:
        """A new personal token and its secret, which is shown once."""
        user = self._browsing(principal, fresh=True)
        if not is_token_name(name):
            raise InvalidValueError(
                f"{name!r} is not a token name: up to {_MAX_TOKEN_NAME} printable "
                "characters"
            )
        now = self.now()
        secret = new_secret(CredentialKind.PERSONAL_TOKEN)
        token = PersonalToken(
            id=uuid.uuid4(),
            user_id=user.id,
            name=name,
            secret_hash=secret_hash(secret),
            created_at=now,
            expires_at=now + PERSONAL_TOKEN_LIFE,
        )
        await self._store.add_personal_token(token)
        return secret, token

    async def personal_tokens(self, principal: Principal) -> list[PersonalToken]:
        return await self._store.personal_tokens_of(self._person(principal).id)

    async def revoke_personal_token(
        self, principal: Principal, token_id: uuid.UUID
    ) -> None:
        user = self._browsing(principal)
        if not await self._store.delete_personal_token(user.id, token_id):
            raise NotFoundError("you have no such token")

    # Device pairing.

    async def begin_pairing(self, principal: Principal) -> tuple[str, Pairing]:
        """A waiting pairing of the person, and its code, for the browser's QR."""
        user = self._browsing(principal, fresh=True)
        now = self.now()
        code = random_secret()
        pairing = Pairing(
            id=uuid.uuid4(),
            user_id=user.id,
            code_hash=secret_hash(code),
            state=PairingState.WAITING,
            created_at=now,
            expires_at=now + PAIRING_LIFE,
        )
        if not await self._store.add_pairing(pairing, now, at_most=PAIRINGS_PER_USER):
            raise BusyError(
                f"{PAIRINGS_PER_USER} codes are waiting already: use one, or let "
                "them expire"
            )
        return code, pairing

    async def claim_pairing(self, code: str, device: DeviceDescription) -> Claimed:
        """The phone's claim. An unknown, used or expired code is one refusal."""
        if not code or len(code) > MAX_SECRET_LENGTH:
            raise NotFoundError("the code is unknown, used or expired")
        now = self.now()
        secret = new_secret(CredentialKind.DEVICE)
        number = f"{secrets.randbelow(10**NUMBER_DIGITS):0{NUMBER_DIGITS}d}"
        expires_at = now + PAIRING_LIFE
        claimed = await self._store.claim_pairing(
            secret_hash(code),
            claim_hash=secret_hash(secret),
            number=number,
            device=device,
            now=now,
            expires_at=expires_at,
        )
        if claimed is None:
            raise NotFoundError("the code is unknown, used or expired")
        return Claimed(secret, number, expires_at)

    async def pairing(self, principal: Principal, pairing_id: uuid.UUID) -> Pairing:
        """The person's pairing, for the browser's poll."""
        user = self._browsing(principal)
        pairing = await self._store.pairing_of(user.id, pairing_id)
        if pairing is None or pairing.expires_at <= self.now():
            raise NotFoundError("you have no such pairing waiting")
        return pairing

    async def approve_pairing(
        self, principal: Principal, pairing_id: uuid.UUID, typed: str
    ) -> DeviceSession:
        """Link the phone that claimed the pairing, if ``typed`` is its number."""
        user = self._browsing(principal)
        now = self.now()
        outcome, device = await self._store.approve_pairing(
            user.id,
            pairing_id,
            # Not six digits is a wrong number too, and counts as one.
            typed_number(typed) or "-",
            device_id=uuid.uuid4(),
            device_expires_at=now + self._device_life,
            now=now,
        )
        match outcome:
            case Approval.APPROVED:
                assert device is not None
                return device
            case Approval.WRONG_NUMBER:
                raise WrongNumberError("that is not the number the phone shows")
            case Approval.NOT_CLAIMED:
                raise NotClaimedError("no phone waits on this code for a number")
            case Approval.GONE:
                raise NotFoundError("you have no such pairing waiting")

    async def refuse_pairing(self, principal: Principal, pairing_id: uuid.UUID) -> None:
        """A code cancelled, or a phone refused: the pairing goes."""
        user = self._browsing(principal)
        if not await self._store.delete_pairing(user.id, pairing_id):
            raise NotFoundError("you have no such pairing waiting")

    async def pairing_state(self, secret: str) -> PairingState | None:
        """The state of the pairing a claim secret belongs to, for the phone's
        poll; ``None`` once it is approved, refused or expired."""
        if kind_of(secret) is not CredentialKind.DEVICE:
            return None
        return await self._store.claim_state(secret_hash(secret), self.now())

    async def devices(self, principal: Principal) -> list[DeviceSession]:
        return await self._store.devices_of(self._person(principal).id)

    async def remove_device(self, principal: Principal, device_id: uuid.UUID) -> None:
        user = self._browsing(principal)
        if not await self._store.delete_device(user.id, device_id):
            raise NotFoundError("you have no such device")

    # Service tokens.

    def _managing(self, by: Principal | Operator) -> None:
        if isinstance(by, Operator):
            return
        if not self.allows(by, TOKENS_MANAGE):
            raise PermissionDeniedError(f"{by.name} may not manage service tokens")

    async def create_service_token(
        self,
        name: str,
        role: str,
        *,
        resource: str | None = None,
        expires_in: timedelta | None = None,
        by: Principal | Operator,
    ) -> tuple[str, ServiceToken]:
        """A new service token and its secret, which is shown once.

        ``by`` holds ``oneberth/tokens:manage``, or is the ``OPERATOR``.
        """
        self._managing(by)
        if not is_service_name(name):
            raise InvalidValueError(
                f"{name!r} is not a service token name: up to 100 letters, digits, "
                "_, . and -, starting with a letter or digit"
            )
        grant = Grant(role, resource)
        self._registry.check_grant(grant)
        if expires_in is not None:
            check_life(expires_in, "a service token's life")
        now = self.now()
        secret = new_secret(CredentialKind.SERVICE_TOKEN)
        token = ServiceToken(
            id=uuid.uuid4(),
            name=name,
            grant=grant,
            secret_hash=secret_hash(secret),
            created_at=now,
            expires_at=None if expires_in is None else now + expires_in,
        )
        if not await self._store.add_service_token(token):
            raise InvalidValueError(f"a service token called {name!r} exists")
        return secret, token

    async def service_tokens(self, *, by: Principal | Operator) -> list[ServiceToken]:
        self._managing(by)
        return await self._store.service_tokens()

    async def revoke_service_token(
        self, token_id: uuid.UUID, *, by: Principal | Operator
    ) -> None:
        self._managing(by)
        if not await self._store.delete_service_token(token_id):
            raise NotFoundError("there is no such service token")

    # The sweep.

    async def sweep(self) -> int:
        """Delete every expired row but service tokens; how many went."""
        now = self.now()
        self._swept_at = now
        return await self._store.delete_expired(now)


def _grants(roles: frozenset[str]) -> frozenset[Grant]:
    return frozenset(Grant(role) for role in roles)
