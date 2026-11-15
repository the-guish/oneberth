# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The identity core: who is asking, and may that principal do this.

It holds identities, users, the four kinds of credential, device pairing, the
allow list and roles, as logic behind the ``IdentityStore`` port. It imports no
third-party code. ``oneberth.identity.memory`` holds the store in memory, and
``oneberth.identity.testing.contracts`` the suite every store passes.
"""

from oneberth.identity._allow import (
    REFUSED_FOR_GOOGLE,
    GrantEntry,
    Match,
    Matcher,
    Policy,
    allowed,
    roles_of,
)
from oneberth.identity._clock import Clock, system_clock
from oneberth.identity._errors import (
    AuthenticationError,
    BearerRefusedError,
    BusyError,
    FreshSignInRequiredError,
    IdentityError,
    InvalidValueError,
    NotClaimedError,
    NotFoundError,
    PermissionDeniedError,
    SchemaVersionError,
    SignInRefusedError,
    WrongNumberError,
)
from oneberth.identity._records import (
    LAST_USED_EVERY,
    PAIRING_WRONG_TRIES,
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
from oneberth.identity._roles import (
    ONEBERTH_ROLES,
    TICKETS_CREATE,
    TOKENS_MANAGE,
    Grant,
    Registry,
    Role,
    RoleTable,
    is_permission_name,
    is_resource_name,
    is_role_name,
)
from oneberth.identity._secrets import (
    PREFIXES,
    CredentialKind,
    kind_of,
    new_secret,
    random_secret,
    secret_hash,
)

__all__ = [
    "LAST_USED_EVERY",
    "ONEBERTH_ROLES",
    "PAIRING_WRONG_TRIES",
    "PREFIXES",
    "REFUSED_FOR_GOOGLE",
    "TICKETS_CREATE",
    "TOKENS_MANAGE",
    "Approval",
    "AuthenticationError",
    "BearerRefusedError",
    "BusyError",
    "Clock",
    "Credential",
    "CredentialKind",
    "DeviceDescription",
    "DeviceSession",
    "FreshSignInRequiredError",
    "Grant",
    "GrantEntry",
    "Identity",
    "IdentityError",
    "InvalidValueError",
    "Match",
    "Matcher",
    "NotClaimedError",
    "NotFoundError",
    "Pairing",
    "PairingState",
    "PendingSignIn",
    "PermissionDeniedError",
    "PersonalToken",
    "Policy",
    "Registry",
    "Role",
    "RoleTable",
    "SchemaVersionError",
    "ServiceToken",
    "Session",
    "SignInRefusedError",
    "User",
    "WrongNumberError",
    "allowed",
    "is_permission_name",
    "is_resource_name",
    "is_role_name",
    "kind_of",
    "new_secret",
    "random_secret",
    "roles_of",
    "secret_hash",
    "system_clock",
]
