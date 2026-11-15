# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The port oneberth keeps users, credentials, pairings and sign-ins behind.

A deployment has one store, and every backend of the deployment opens it.

Every method is one atomic operation: PostgreSQL runs it as one transaction,
and the memory store runs it in one step of the event loop. Of two callers at
once, one takes what is taken once. The core never composes several calls into
something that must be atomic.

A secret never reaches the store: it gets the SHA-256 hex, as ``secret_hash``
gives it, and finds rows by that. Every id and every time comes from the
caller. A find given ``now`` never returns a row whose ``expires_at`` is not
after ``now``.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from oneberth.identity._errors import SchemaVersionError
from oneberth.identity._records import (
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

SCHEMA_VERSION = 1
"""The version of the store this release of oneberth reads and writes."""


class IdentityStore(ABC):
    """Durable storage for users, credentials, pairings and pending sign-ins."""

    # The schema.

    @abstractmethod
    async def setup(self) -> None:
        """Create the store's tables and record ``SCHEMA_VERSION``. Safe to repeat.

        Raises ``SchemaVersionError`` for a store another version set up.
        """
        raise NotImplementedError

    @abstractmethod
    async def schema_version(self) -> int | None:
        """The version recorded by ``setup``; ``None`` before any setup."""
        raise NotImplementedError

    # Users.

    @abstractmethod
    async def upsert_user(
        self, identity: Identity, *, user_id: uuid.UUID, now: datetime
    ) -> User:
        """The user of ``identity``'s provider and subject, refreshed from it.

        A first sign-in creates the user with ``user_id``, created at ``now``.
        A later one keeps the id and the creation time, and replaces the name,
        the email, the hosted domain and the groups.
        """
        raise NotImplementedError

    @abstractmethod
    async def user(self, user_id: uuid.UUID) -> User | None:
        raise NotImplementedError

    @abstractmethod
    async def user_of(self, provider: str, subject: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    async def users_with_email(self, email: str) -> list[User]:
        """The users with that email, compared without regard to case, oldest
        first, ties broken by id: how the operator names a person."""
        raise NotImplementedError

    # Sessions.

    @abstractmethod
    async def add_session(self, session: Session) -> None:
        """Its user is one the store has."""
        raise NotImplementedError

    @abstractmethod
    async def session_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, Session] | None:
        raise NotImplementedError

    @abstractmethod
    async def delete_session(self, secret_hash: str) -> bool:
        """Whether there was one."""
        raise NotImplementedError

    @abstractmethod
    async def delete_sessions(self) -> int:
        """Delete every session, expired ones included; how many there were."""
        raise NotImplementedError

    # Personal tokens.

    @abstractmethod
    async def add_personal_token(self, token: PersonalToken) -> None:
        """Its user is one the store has."""
        raise NotImplementedError

    @abstractmethod
    async def personal_token_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, PersonalToken] | None:
        raise NotImplementedError

    @abstractmethod
    async def personal_tokens_of(self, user_id: uuid.UUID) -> list[PersonalToken]:
        """The user's tokens, oldest first, ties broken by id."""
        raise NotImplementedError

    @abstractmethod
    async def delete_personal_token(
        self, user_id: uuid.UUID, token_id: uuid.UUID
    ) -> bool:
        """Only the owner's: whether that user had that token."""
        raise NotImplementedError

    # Device sessions.

    @abstractmethod
    async def device_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, DeviceSession] | None:
        """The device and its user. Its ``last_used_at`` becomes ``now`` when the
        one recorded is ``LAST_USED_EVERY`` old or older, in the same step, and
        the device returned holds what was written."""
        raise NotImplementedError

    @abstractmethod
    async def devices_of(self, user_id: uuid.UUID) -> list[DeviceSession]:
        """The user's devices, oldest first, ties broken by id."""
        raise NotImplementedError

    @abstractmethod
    async def all_devices(self) -> list[tuple[User, DeviceSession]]:
        """Every device with its user, oldest first, ties broken by id."""
        raise NotImplementedError

    @abstractmethod
    async def delete_device(self, user_id: uuid.UUID, device_id: uuid.UUID) -> bool:
        """Only the owner's: whether that user had that device."""
        raise NotImplementedError

    @abstractmethod
    async def delete_devices(
        self,
        *,
        user_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        every: bool = False,
    ) -> list[DeviceSession]:
        """Delete one user's devices, one device whoever's it is, or every device,
        and return what went, oldest first. Exactly one of the three is given,
        else ``ValueError``. The operator's: a person removes by owner."""
        raise NotImplementedError

    # Pairings.

    @abstractmethod
    async def add_pairing(
        self, pairing: Pairing, now: datetime, *, at_most: int
    ) -> bool:
        """Store a waiting pairing, after deleting the user's expired ones.

        Unless the user has ``at_most`` pairings that are not expired: then
        nothing is stored and the answer is ``False``.
        """
        raise NotImplementedError

    @abstractmethod
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
        """The pairing with that code, moved from ``WAITING`` to ``CLAIMED`` with
        the claim hash, the number, the device and the new ``expires_at``.

        ``None`` when there is none, it is not waiting, or it has expired.
        Of two claims at once, one gets it.
        """
        raise NotImplementedError

    @abstractmethod
    async def pairing_of(
        self, user_id: uuid.UUID, pairing_id: uuid.UUID
    ) -> Pairing | None:
        """Only the owner's, expired or not: the caller judges the expiry."""
        raise NotImplementedError

    @abstractmethod
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
        """Decide the owner's claimed pairing by the number its phone shows.

        The right number, on a claimed pairing that has not expired, adds a
        device session with that id, created and last used at ``now``, expiring
        at ``device_expires_at``, with the pairing's device and its claim hash
        as the secret hash. It clears the claim hash, marks the pairing
        approved, and returns the device.

        A wrong number counts a wrong try. The ``PAIRING_WRONG_TRIES``-th
        deletes the pairing and answers ``GONE``. A waiting or approved pairing
        is ``NOT_CLAIMED``. An unknown, another's or expired one is ``GONE``.
        Of two approves at once, one decides first and the other sees it.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete_pairing(self, user_id: uuid.UUID, pairing_id: uuid.UUID) -> bool:
        """Only the owner's: whether that user had it. A device it linked stays."""
        raise NotImplementedError

    @abstractmethod
    async def claim_state(self, claim_hash: str, now: datetime) -> PairingState | None:
        """The state of the pairing whose claim has that hash, for the phone's poll.

        ``None`` when there is none, as after the approve moved the hash, or it
        has expired.
        """
        raise NotImplementedError

    # Service tokens.

    @abstractmethod
    async def add_service_token(self, token: ServiceToken) -> bool:
        """Store it; ``False`` and nothing stored when its name is taken, by a
        token expired or not."""
        raise NotImplementedError

    @abstractmethod
    async def service_token_by_hash(
        self, secret_hash: str, now: datetime
    ) -> ServiceToken | None:
        raise NotImplementedError

    @abstractmethod
    async def service_tokens(self) -> list[ServiceToken]:
        """Every service token, expired ones included, by name."""
        raise NotImplementedError

    @abstractmethod
    async def delete_service_token(self, token_id: uuid.UUID) -> bool:
        """Whether there was one."""
        raise NotImplementedError

    # Sign-ins in progress.

    @abstractmethod
    async def add_pending_sign_in(
        self, pending: PendingSignIn, now: datetime, *, limit: int
    ) -> bool:
        """Store it, unless ``limit`` sign-ins that have not expired are in progress.

        Then nothing is stored and the answer is ``False``.
        """
        raise NotImplementedError

    @abstractmethod
    async def take_pending_sign_in(
        self, state_hash: str, now: datetime
    ) -> PendingSignIn | None:
        """Delete it and return it, once; ``None`` when it is gone or expired.

        An expired one is deleted either way. Of two takes at once, one gets it.
        """
        raise NotImplementedError

    # Every credential of a person, and the sweep.

    @abstractmethod
    async def delete_credentials_of(self, user_id: uuid.UUID) -> int:
        """Delete the user's sessions, personal tokens, devices and pairings at
        once; how many rows went. The user stays."""
        raise NotImplementedError

    @abstractmethod
    async def delete_credentials_of_identity(self, provider: str, subject: str) -> int:
        """As ``delete_credentials_of``, for the user of that identity, if any."""
        raise NotImplementedError

    @abstractmethod
    async def delete_expired(self, now: datetime) -> int:
        """Delete every session, personal token, device, pairing and pending
        sign-in that has expired; how many rows went.

        Expired service tokens stay, so the operator still sees them listed
        until they are revoked.
        """
        raise NotImplementedError


async def check_schema(store: IdentityStore) -> None:
    """Raise ``SchemaVersionError`` unless ``store`` is at ``SCHEMA_VERSION``.

    A backend calls it when it starts, and refuses to start on a failure.
    """
    version = await store.schema_version()
    if version is None:
        raise SchemaVersionError("the store is not set up: run `oneberth store init`")
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"the store is at version {version}, and this oneberth reads version "
            f"{SCHEMA_VERSION}"
        )
