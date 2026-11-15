# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The exceptions the identity core raises. Adapters translate their own failures
to these, and the web part answers each with one status."""


class IdentityError(Exception):
    """Base class for every error the identity core raises."""


class InvalidValueError(IdentityError, ValueError):
    """A value the core refuses: a name, a role, a resource or a life out of bounds."""


class AuthenticationError(IdentityError):
    """A secret that names nobody: unknown, malformed, ended or expired. A 401."""


class SignInRefusedError(IdentityError):
    """A provider vouched for a person whom no allow entry lets in."""


class PermissionDeniedError(IdentityError):
    """The principal is known, and may not do what it asks. A 403."""


class BearerRefusedError(PermissionDeniedError):
    """A bearer asked to mint or remove a person's credential.

    Only the person's browser session does that, and a forwarded session
    counts as a bearer.
    """


class FreshSignInRequiredError(PermissionDeniedError):
    """A browser session too old to mint a person's credential."""


class NotFoundError(IdentityError):
    """No such token, device or pairing, or one that belongs to someone else."""


class BusyError(IdentityError):
    """Too many sign-ins or pairings in progress already. Try again later."""


class WrongNumberError(IdentityError):
    """The number typed is not the one the phone shows."""


class NotClaimedError(IdentityError):
    """No phone waits on the pairing for a number: not claimed yet, or approved."""


class SchemaVersionError(IdentityError):
    """The store was set up by another release of oneberth, or not at all."""
