# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The identity store, in dictionaries, for tests and for one process.

No operation awaits, so each runs in one step of the event loop: of two callers
taking one sign-in, claiming one pairing or approving it, the second finds what
the first did. It applies the same expiry and the same rules as the stores on
PostgreSQL and SQLite, and passes the same contract suite.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import TypeVar

from oneberth.identity._errors import SchemaVersionError
from oneberth.identity._records import (
    LAST_USED_EVERY,
    PAIRING_WRONG_TRIES,
    Approval,
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
from oneberth.identity._store import SCHEMA_VERSION, IdentityStore

_C = TypeVar("_C", Session, PersonalToken, DeviceSession)


class MemoryIdentityStore(IdentityStore):
    """Users, credentials, pairings and pending sign-ins in dictionaries."""

    def __init__(self, *, schema_version: int | None = None) -> None:
        """``schema_version`` stands for a store found already set up, by this
        release or another; ``None`` is a store nobody set up."""
        self._version = schema_version
        self._users: dict[uuid.UUID, User] = {}
        self._sessions: dict[str, Session] = {}
        self._tokens: dict[str, PersonalToken] = {}
        self._devices: dict[str, DeviceSession] = {}
        self._pairings: dict[uuid.UUID, Pairing] = {}
        self._services: dict[str, ServiceToken] = {}
        """By name."""
        self._pending: dict[str, PendingSignIn] = {}

    # The schema.

    async def setup(self) -> None:
        if self._version is not None and self._version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"the store is at version {self._version}, and this oneberth sets "
                f"up version {SCHEMA_VERSION}"
            )
        self._version = SCHEMA_VERSION

    async def schema_version(self) -> int | None:
        return self._version

    # Users.

    async def upsert_user(
        self, identity: Identity, *, user_id: uuid.UUID, now: datetime
    ) -> User:
        found = self._user_of(identity.provider, identity.subject)
        user = User(
            id=user_id if found is None else found.id,
            provider=identity.provider,
            subject=identity.subject,
            created_at=now if found is None else found.created_at,
            name=identity.name,
            email=identity.email,
            hosted_domain=identity.hosted_domain,
            groups=identity.groups,
        )
        self._users[user.id] = user
        return user

    async def user(self, user_id: uuid.UUID) -> User | None:
        return self._users.get(user_id)

    async def user_of(self, provider: str, subject: str) -> User | None:
        return self._user_of(provider, subject)

    def _user_of(self, provider: str, subject: str) -> User | None:
        return next(
            (
                u
                for u in self._users.values()
                if (u.provider, u.subject) == (provider, subject)
            ),
            None,
        )

    async def users_with_email(self, email: str) -> list[User]:
        found = [
            u
            for u in self._users.values()
            if u.email is not None and u.email.lower() == email.lower()
        ]
        return sorted(found, key=lambda u: (u.created_at, u.id))

    # Sessions.

    async def add_session(self, session: Session) -> None:
        self._sessions[session.secret_hash] = session

    async def session_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, Session] | None:
        return self._with_user(self._sessions.get(secret_hash), now)

    async def delete_session(self, secret_hash: str) -> bool:
        return self._sessions.pop(secret_hash, None) is not None

    async def delete_sessions(self) -> int:
        count = len(self._sessions)
        self._sessions.clear()
        return count

    # Personal tokens.

    async def add_personal_token(self, token: PersonalToken) -> None:
        self._tokens[token.secret_hash] = token

    async def personal_token_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, PersonalToken] | None:
        return self._with_user(self._tokens.get(secret_hash), now)

    async def personal_tokens_of(self, user_id: uuid.UUID) -> list[PersonalToken]:
        mine = [t for t in self._tokens.values() if t.user_id == user_id]
        return sorted(mine, key=lambda t: (t.created_at, t.id))

    async def delete_personal_token(
        self, user_id: uuid.UUID, token_id: uuid.UUID
    ) -> bool:
        return _pop_owned(self._tokens, user_id, token_id)

    # Device sessions.

    async def device_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, DeviceSession] | None:
        found = self._with_user(self._devices.get(secret_hash), now)
        if found is None:
            return None
        user, device = found
        if device.last_used_at <= now - LAST_USED_EVERY:
            device = dataclasses.replace(device, last_used_at=now)
            self._devices[secret_hash] = device
        return user, device

    async def devices_of(self, user_id: uuid.UUID) -> list[DeviceSession]:
        return _oldest_first(d for d in self._devices.values() if d.user_id == user_id)

    async def all_devices(self) -> list[tuple[User, DeviceSession]]:
        return [
            (self._users[d.user_id], d)
            for d in _oldest_first(self._devices.values())
            if d.user_id in self._users
        ]

    async def delete_device(self, user_id: uuid.UUID, device_id: uuid.UUID) -> bool:
        return _pop_owned(self._devices, user_id, device_id)

    async def delete_devices(
        self,
        *,
        user_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        every: bool = False,
    ) -> list[DeviceSession]:
        if [user_id is not None, device_id is not None, every].count(True) != 1:
            raise ValueError("give one of user_id, device_id and every")
        ended = _oldest_first(
            d
            for d in self._devices.values()
            if every or d.user_id == user_id or d.id == device_id
        )
        for device in ended:
            del self._devices[device.secret_hash]
        return ended

    # Pairings.

    async def add_pairing(
        self, pairing: Pairing, now: datetime, *, at_most: int
    ) -> bool:
        mine = [p for p in self._pairings.values() if p.user_id == pairing.user_id]
        for expired in [p for p in mine if p.expires_at <= now]:
            del self._pairings[expired.id]
        if sum(p.expires_at > now for p in mine) >= at_most:
            return False
        self._pairings[pairing.id] = pairing
        return True

    async def claim_pairing(
        self,
        code_hash: str,
        *,
        claim_hash: str,
        number: str,
        device: DeviceDescription,
        now: datetime,
        expires_at: datetime,
    ) -> Pairing | None:
        found = next(
            (p for p in self._pairings.values() if p.code_hash == code_hash), None
        )
        if (
            found is None
            or found.state is not PairingState.WAITING
            or found.expires_at <= now
        ):
            return None
        claimed = dataclasses.replace(
            found,
            state=PairingState.CLAIMED,
            claim_hash=claim_hash,
            number=number,
            device=device,
            expires_at=expires_at,
        )
        self._pairings[found.id] = claimed
        return claimed

    async def pairing_of(
        self, user_id: uuid.UUID, pairing_id: uuid.UUID
    ) -> Pairing | None:
        found = self._pairings.get(pairing_id)
        return found if found is not None and found.user_id == user_id else None

    async def approve_pairing(
        self,
        user_id: uuid.UUID,
        pairing_id: uuid.UUID,
        number: str,
        *,
        device_id: uuid.UUID,
        device_expires_at: datetime,
        now: datetime,
    ) -> tuple[Approval, DeviceSession | None]:
        found = self._pairings.get(pairing_id)
        if found is None or found.user_id != user_id or found.expires_at <= now:
            return Approval.GONE, None
        if found.state is not PairingState.CLAIMED:
            return Approval.NOT_CLAIMED, None
        assert found.claim_hash is not None and found.device is not None
        if found.number != number:
            if found.wrong_tries + 1 >= PAIRING_WRONG_TRIES:
                del self._pairings[found.id]
                return Approval.GONE, None
            self._pairings[found.id] = dataclasses.replace(
                found, wrong_tries=found.wrong_tries + 1
            )
            return Approval.WRONG_NUMBER, None
        device = DeviceSession(
            id=device_id,
            user_id=user_id,
            device=found.device,
            secret_hash=found.claim_hash,
            created_at=now,
            last_used_at=now,
            expires_at=device_expires_at,
        )
        self._devices[device.secret_hash] = device
        self._pairings[found.id] = dataclasses.replace(
            found, state=PairingState.APPROVED, claim_hash=None
        )
        return Approval.APPROVED, device

    async def delete_pairing(self, user_id: uuid.UUID, pairing_id: uuid.UUID) -> bool:
        found = self._pairings.get(pairing_id)
        if found is None or found.user_id != user_id:
            return False
        del self._pairings[pairing_id]
        return True

    async def claim_state(self, claim_hash: str, now: datetime) -> PairingState | None:
        found = next(
            (p for p in self._pairings.values() if p.claim_hash == claim_hash), None
        )
        return None if found is None or found.expires_at <= now else found.state

    # Service tokens.

    async def add_service_token(self, token: ServiceToken) -> bool:
        if token.name in self._services:
            return False
        self._services[token.name] = token
        return True

    async def service_token_by_hash(
        self, secret_hash: str, now: datetime
    ) -> ServiceToken | None:
        found = next(
            (t for t in self._services.values() if t.secret_hash == secret_hash), None
        )
        if found is None or (found.expires_at is not None and found.expires_at <= now):
            return None
        return found

    async def service_tokens(self) -> list[ServiceToken]:
        return [token for _, token in sorted(self._services.items())]

    async def delete_service_token(self, token_id: uuid.UUID) -> bool:
        found = next((t for t in self._services.values() if t.id == token_id), None)
        if found is None:
            return False
        del self._services[found.name]
        return True

    # Sign-ins in progress.

    async def add_pending_sign_in(
        self, pending: PendingSignIn, now: datetime, *, limit: int
    ) -> bool:
        if sum(p.expires_at > now for p in self._pending.values()) >= limit:
            return False
        self._pending[pending.state_hash] = pending
        return True

    async def take_pending_sign_in(
        self, state_hash: str, now: datetime
    ) -> PendingSignIn | None:
        taken = self._pending.pop(state_hash, None)
        return taken if taken is not None and taken.expires_at > now else None

    # Every credential of a person, and the sweep.

    async def delete_credentials_of(self, user_id: uuid.UUID) -> int:
        deleted = 0
        tables: tuple[dict[str, Session], dict[str, PersonalToken]] = (
            self._sessions,
            self._tokens,
        )
        for table in tables:
            for key in [k for k, row in table.items() if row.user_id == user_id]:
                del table[key]
                deleted += 1
        for key in [k for k, d in self._devices.items() if d.user_id == user_id]:
            del self._devices[key]
            deleted += 1
        for pid in [k for k, p in self._pairings.items() if p.user_id == user_id]:
            del self._pairings[pid]
            deleted += 1
        return deleted

    async def delete_credentials_of_identity(self, provider: str, subject: str) -> int:
        user = self._user_of(provider, subject)
        return 0 if user is None else await self.delete_credentials_of(user.id)

    async def delete_expired(self, now: datetime) -> int:
        before = (
            len(self._sessions)
            + len(self._tokens)
            + len(self._devices)
            + len(self._pairings)
            + len(self._pending)
        )
        self._sessions = {k: v for k, v in self._sessions.items() if v.expires_at > now}
        self._tokens = {k: v for k, v in self._tokens.items() if v.expires_at > now}
        self._devices = {k: v for k, v in self._devices.items() if v.expires_at > now}
        self._pairings = {k: v for k, v in self._pairings.items() if v.expires_at > now}
        self._pending = {k: v for k, v in self._pending.items() if v.expires_at > now}
        after = (
            len(self._sessions)
            + len(self._tokens)
            + len(self._devices)
            + len(self._pairings)
            + len(self._pending)
        )
        return before - after

    def _with_user(
        self, credential: _C | None, now: datetime
    ) -> tuple[User, _C] | None:
        if credential is None or credential.expires_at <= now:
            return None
        user = self._users.get(credential.user_id)
        return None if user is None else (user, credential)


def _pop_owned(
    table: dict[str, PersonalToken] | dict[str, DeviceSession],
    user_id: uuid.UUID,
    row_id: uuid.UUID,
) -> bool:
    key = next(
        (k for k, row in table.items() if row.id == row_id and row.user_id == user_id),
        None,
    )
    if key is None:
        return False
    del table[key]
    return True


def _oldest_first(devices: Iterable[DeviceSession]) -> list[DeviceSession]:
    return sorted(devices, key=lambda d: (d.created_at, d.id))
