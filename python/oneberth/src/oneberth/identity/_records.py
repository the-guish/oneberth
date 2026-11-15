# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""What the store keeps: users, credentials, pairings and sign-ins in progress.

A record holds the SHA-256 hex of its secret. Every id and every time in a
record comes from the core, which reads its injected clock. The store reads no
clock: it is given ``now`` wherever an expiry matters.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from oneberth.identity._roles import Grant
from oneberth.identity._secrets import CredentialKind


@dataclass(frozen=True, slots=True)
class Identity:
    """What a provider says about a person at a sign-in.

    ``email`` is an address the provider verified. The provider adapter leaves
    out an address it did not verify.
    """

    provider: str
    """The provider's id in the deployment's configuration."""
    subject: str
    """The provider's stable identifier for the person, never reassigned."""
    name: str | None = None
    email: str | None = None
    hosted_domain: str | None = None
    """Google's ``hd``: the Workspace domain the account belongs to."""
    groups: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class User:
    """A stored person, keyed by provider and subject.

    ``name``, ``email``, ``hosted_domain`` and ``groups`` are what the last
    sign-in said. The allow list is checked against them again on use.
    """

    id: uuid.UUID
    provider: str
    subject: str
    created_at: datetime
    name: str | None = None
    email: str | None = None
    hosted_domain: str | None = None
    groups: frozenset[str] = frozenset()

    @property
    def identity(self) -> Identity:
        """What the last sign-in said, as the allow list reads it."""
        return Identity(
            provider=self.provider,
            subject=self.subject,
            name=self.name,
            email=self.email,
            hosted_domain=self.hosted_domain,
            groups=self.groups,
        )


@dataclass(frozen=True, slots=True)
class Session:
    """A signed-in browser. Its ``created_at`` says how fresh the sign-in is."""

    id: uuid.UUID
    user_id: uuid.UUID
    secret_hash: str
    created_at: datetime
    expires_at: datetime

    kind = CredentialKind.SESSION


@dataclass(frozen=True, slots=True)
class PersonalToken:
    """A person's token for their scripts, minted from their browser session."""

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    secret_hash: str
    created_at: datetime
    expires_at: datetime

    kind = CredentialKind.PERSONAL_TOKEN


@dataclass(frozen=True, slots=True)
class DeviceDescription:
    """What a phone says of itself when it claims a pairing: data for the list."""

    name: str
    platform: str
    app_version: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceSession:
    """A linked phone. Its secret is the claim secret of the pairing that linked it."""

    id: uuid.UUID
    user_id: uuid.UUID
    device: DeviceDescription
    secret_hash: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime

    kind = CredentialKind.DEVICE


@dataclass(frozen=True, slots=True)
class ServiceToken:
    """A program's token: one role and, when the role needs one, one resource."""

    id: uuid.UUID
    name: str
    """The service's name, unique in the store."""
    grant: Grant
    secret_hash: str
    created_at: datetime
    expires_at: datetime | None = None
    """``None`` for a token that lives until it is revoked."""

    kind = CredentialKind.SERVICE_TOKEN


Credential = Session | PersonalToken | DeviceSession | ServiceToken


class PairingState(StrEnum):
    WAITING = "waiting"
    """Minted in the browser; no phone has presented the code."""
    CLAIMED = "claimed"
    """A phone presented the code and shows a number."""
    APPROVED = "approved"
    """The person typed the number; the claim secret is the device's now."""


class Approval(StrEnum):
    """What an approve with a number did."""

    APPROVED = "approved"
    WRONG_NUMBER = "wrong_number"
    NOT_CLAIMED = "not_claimed"
    """Waiting for a phone still, or approved already: nothing to decide."""
    GONE = "gone"
    """Unknown, another's, expired, or ended by this, the last wrong number."""


LAST_USED_EVERY = timedelta(minutes=1)
"""How often a device's ``last_used_at`` is written: by the lookup that finds it,
when the one recorded is this old or older."""

PAIRING_WRONG_TRIES = 3
"""The wrong numbers a pairing takes. The last of them deletes it."""


@dataclass(frozen=True, slots=True)
class Pairing:
    """A phone being linked.

    Minted ``WAITING`` under the hash of the code its QR carries. A claim adds
    the claim secret's hash, the number and the device's description. An
    approve moves the claim hash to a new device session.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    code_hash: str
    state: PairingState
    created_at: datetime
    expires_at: datetime
    claim_hash: str | None = None
    number: str | None = None
    """Six digits, stored as they are: a hash of six digits hides nothing."""
    wrong_tries: int = 0
    device: DeviceDescription | None = None


@dataclass(frozen=True, slots=True)
class PendingSignIn:
    """A sign-in through a provider, begun and not finished, under its state's hash.

    The nonce and the PKCE verifier are kept as they are: the callback needs them.
    """

    state_hash: str
    provider: str
    nonce: str
    """Sent to the provider, and expected back in its ID token."""
    verifier: str
    """The PKCE code verifier. The provider was sent its S256 challenge."""
    return_to: str
    """Where the browser lands after the sign-in, as the web part checked it."""
    created_at: datetime
    expires_at: datetime
