# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""Who may sign in, and with which roles.

An allow entry names a provider and one matcher. It admits the people it
matches and gives them the default role of each application. A grant entry
uses the same matchers and gives one or more roles beyond those, to people an
allow entry admits. The configuration reader builds a ``Policy`` from the
``[[allow]]`` and ``[[grant]]`` tables. Here they are plain values.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from oneberth.identity._errors import InvalidValueError
from oneberth.identity._records import Identity
from oneberth.identity._roles import Registry


class Matcher(StrEnum):
    """What an entry looks at in an identity."""

    EVERYONE = "everyone"
    SUBJECT = "subject"
    EMAIL = "email"
    """A verified email address, compared without regard to case."""
    EMAIL_DOMAIN = "email_domain"
    """The domain of a verified email address, compared without regard to case."""
    HOSTED_DOMAIN = "hosted_domain"
    """Google's ``hd`` claim, compared without regard to case."""
    GROUP = "group"
    """A value of the provider's groups claim, compared exactly."""


REFUSED_FOR_GOOGLE = frozenset({Matcher.EVERYONE, Matcher.EMAIL_DOMAIN})
"""The matchers a Google provider refuses. Anybody may open a Google account,
and verify an address at any domain with it: ``hosted_domain`` names a
Workspace, and ``email`` one person."""


@dataclass(frozen=True, slots=True)
class Match:
    """The people of one provider that one matcher accepts."""

    provider: str
    matcher: Matcher
    value: str | None = None
    """What the matcher compares with; ``None`` for ``EVERYONE`` alone."""

    def __post_init__(self) -> None:
        if not self.provider:
            raise InvalidValueError("an entry names its provider")
        if self.matcher is Matcher.EVERYONE:
            if self.value is not None:
                raise InvalidValueError("an entry for everyone compares with nothing")
        elif not self.value:
            raise InvalidValueError(f"an entry by {self.matcher.value} needs a value")

    def matches(self, identity: Identity) -> bool:
        """Whether this entry accepts ``identity``."""
        if identity.provider != self.provider:
            return False
        value = self.value or ""
        match self.matcher:
            case Matcher.EVERYONE:
                return True
            case Matcher.SUBJECT:
                return identity.subject == value
            case Matcher.EMAIL:
                email = _email(identity)
                return email is not None and email == value.lower()
            case Matcher.EMAIL_DOMAIN:
                email = _email(identity)
                return email is not None and email.rpartition("@")[2] == value.lower()
            case Matcher.HOSTED_DOMAIN:
                domain = identity.hosted_domain
                return domain is not None and domain.lower() == value.lower()
            case Matcher.GROUP:
                return value in identity.groups


def _email(identity: Identity) -> str | None:
    """The identity's verified email, lower-cased, when it has a usable one."""
    email = identity.email
    if not email or "@" not in email:
        return None
    return email.lower()


@dataclass(frozen=True, slots=True)
class GrantEntry:
    """More roles for the people one matcher accepts."""

    match: Match
    roles: frozenset[str]

    def __post_init__(self) -> None:
        if not self.roles:
            raise InvalidValueError("a grant entry names at least one role")


@dataclass(frozen=True, slots=True)
class Policy:
    """The allow list and the grant entries of a deployment."""

    allow: tuple[Match, ...] = ()
    grants: tuple[GrantEntry, ...] = ()

    def check(self, registry: Registry) -> None:
        """Raise ``InvalidValueError`` unless every grant entry names roles that are
        registered, that a person may hold, and that need no resource."""
        problems: list[str] = []
        for number, entry in enumerate(self.grants, start=1):
            for name in sorted(entry.roles):
                try:
                    role = registry.role(name)
                except InvalidValueError as error:
                    problems.append(f"grant {number}: {error}")
                    continue
                if not role.people:
                    problems.append(
                        f"grant {number}: {name!r} is not a role for people"
                    )
        if problems:
            raise InvalidValueError("; ".join(problems))


def allowed(identity: Identity, allow: Iterable[Match]) -> bool:
    """Whether any allow entry admits ``identity``."""
    return any(entry.matches(identity) for entry in allow)


def roles_of(
    identity: Identity, policy: Policy, default_roles: Iterable[str]
) -> frozenset[str] | None:
    """The roles ``identity`` holds under ``policy``; ``None`` when no allow entry
    admits it. A grant entry adds roles to an admitted person alone."""
    if not allowed(identity, policy.allow):
        return None
    roles = set(default_roles)
    for entry in policy.grants:
        if entry.match.matches(identity):
            roles |= entry.roles
    return frozenset(roles)
