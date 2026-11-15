# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The pure rules of the identity core: secrets, matchers, roles and decisions."""

from __future__ import annotations

import re
from typing import Any

import pytest

from oneberth.identity import (
    ONEBERTH_ROLES,
    PREFIXES,
    REFUSED_FOR_GOOGLE,
    TOKENS_MANAGE,
    CredentialKind,
    Grant,
    GrantEntry,
    Identity,
    InvalidValueError,
    Match,
    Matcher,
    Policy,
    Registry,
    Role,
    RoleTable,
    is_permission_name,
    is_role_name,
    kind_of,
    new_secret,
    roles_of,
    secret_hash,
)

# Tables shaped like the applications' own, for the tests alone.
NEORC = RoleTable(
    app="neorc",
    permissions=frozenset(
        {
            "neorc/runs:start",
            "neorc/runs:read",
            "neorc/tasks:claim",
            "neorc/flows:upload",
        }
    ),
    roles=(
        Role(
            "neorc/user",
            frozenset({"neorc/runs:start", "neorc/runs:read"}),
            people=True,
        ),
        Role("neorc/worker", frozenset({"neorc/tasks:claim"}), resource="queue"),
        Role("neorc/ci", frozenset({"neorc/flows:upload"})),
    ),
    default="neorc/user",
)
ROBINAUTS = RoleTable(
    app="robinauts",
    permissions=frozenset({"robinauts/sessions:read", "robinauts/config:edit"}),
    roles=(
        Role("robinauts/user", frozenset({"robinauts/sessions:read"}), people=True),
        Role("robinauts/admin", frozenset({"robinauts/config:edit"}), people=True),
    ),
    default="robinauts/user",
)
REGISTRY = Registry([ONEBERTH_ROLES, NEORC, ROBINAUTS])


# Secrets.


@pytest.mark.parametrize("kind", list(CredentialKind))
def test_a_new_secret_names_its_kind(kind: CredentialKind) -> None:
    secret = new_secret(kind)

    assert secret.startswith(PREFIXES[kind])
    assert kind_of(secret) is kind
    assert len(secret) == len(PREFIXES[kind]) + 43


@pytest.mark.parametrize(
    ("secret", "kind"),
    [
        ("ob_ses_abc", CredentialKind.SESSION),
        ("ob_pat_abc", CredentialKind.PERSONAL_TOKEN),
        ("ob_dev_abc", CredentialKind.DEVICE),
        ("ob_svc_abc", CredentialKind.SERVICE_TOKEN),
        ("ob_lch_abc", CredentialKind.LAUNCH),
        ("ob_ses_", None),
        ("neorc_abc", None),
        ("rbt_abc", None),
        ("", None),
        ("ob_svc_" + "a" * 300, None),
    ],
)
def test_the_prefix_picks_the_kind(secret: str, kind: CredentialKind | None) -> None:
    assert kind_of(secret) is kind


def test_a_secret_is_kept_as_its_sha256() -> None:
    assert secret_hash("a") == (
        "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"
    )
    assert secret_hash("a") != secret_hash("b")


# Matchers.

ADA = Identity(
    provider="okta",
    subject="00u1",
    name="Ada",
    email="Ada@Example.com",
    hosted_domain="Example.com",
    groups=frozenset({"platform-users"}),
)
NO_EMAIL = Identity(provider="okta", subject="00u2")


@pytest.mark.parametrize(
    ("entry", "identity", "expected"),
    [
        (Match("okta", Matcher.EVERYONE), ADA, True),
        (Match("google", Matcher.EVERYONE), ADA, False),
        (Match("okta", Matcher.SUBJECT, "00u1"), ADA, True),
        (Match("okta", Matcher.SUBJECT, "00U1"), ADA, False),
        (Match("okta", Matcher.EMAIL, "ada@example.com"), ADA, True),
        (Match("okta", Matcher.EMAIL, "ADA@EXAMPLE.COM"), ADA, True),
        (Match("okta", Matcher.EMAIL, "bob@example.com"), ADA, False),
        (Match("okta", Matcher.EMAIL, "ada@example.com"), NO_EMAIL, False),
        (Match("okta", Matcher.EMAIL_DOMAIN, "example.com"), ADA, True),
        (Match("okta", Matcher.EMAIL_DOMAIN, "EXAMPLE.com"), ADA, True),
        (Match("okta", Matcher.EMAIL_DOMAIN, "ample.com"), ADA, False),
        (Match("okta", Matcher.EMAIL_DOMAIN, "example.com"), NO_EMAIL, False),
        (Match("okta", Matcher.HOSTED_DOMAIN, "example.com"), ADA, True),
        (Match("okta", Matcher.HOSTED_DOMAIN, "other.com"), ADA, False),
        (Match("okta", Matcher.HOSTED_DOMAIN, "example.com"), NO_EMAIL, False),
        (Match("okta", Matcher.GROUP, "platform-users"), ADA, True),
        (Match("okta", Matcher.GROUP, "Platform-Users"), ADA, False),
        (Match("okta", Matcher.GROUP, "platform-users"), NO_EMAIL, False),
        (
            Match("okta", Matcher.EMAIL, "ada@example.com"),
            Identity("okta", "x", email="not-an-address"),
            False,
        ),
    ],
)
def test_a_matcher_accepts(entry: Match, identity: Identity, expected: bool) -> None:
    assert entry.matches(identity) is expected


@pytest.mark.parametrize(
    ("provider", "matcher", "value"),
    [
        ("", Matcher.EVERYONE, None),
        ("okta", Matcher.EVERYONE, "x"),
        ("okta", Matcher.EMAIL, None),
        ("okta", Matcher.GROUP, ""),
    ],
)
def test_a_malformed_entry_is_refused(
    provider: str, matcher: Matcher, value: str | None
) -> None:
    with pytest.raises(InvalidValueError):
        Match(provider, matcher, value)


def test_google_refuses_everyone_and_email_domain() -> None:
    assert frozenset({Matcher.EVERYONE, Matcher.EMAIL_DOMAIN}) == REFUSED_FOR_GOOGLE


# Roles from the allow list and the grant entries.

POLICY = Policy(
    allow=(
        Match("okta", Matcher.GROUP, "platform-users"),
        Match("google", Matcher.HOSTED_DOMAIN, "example.com"),
    ),
    grants=(
        GrantEntry(
            Match("okta", Matcher.GROUP, "platform-admins"),
            frozenset({"robinauts/admin", "oneberth/admin"}),
        ),
        GrantEntry(
            Match("google", Matcher.EMAIL, "root@example.com"),
            frozenset({"oneberth/admin"}),
        ),
    ),
)
DEFAULTS = frozenset({"neorc/user", "robinauts/user"})


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        (Identity("okta", "1", groups=frozenset({"platform-users"})), DEFAULTS),
        (
            Identity(
                "okta", "2", groups=frozenset({"platform-users", "platform-admins"})
            ),
            DEFAULTS | {"robinauts/admin", "oneberth/admin"},
        ),
        # A grant entry adds roles to an admitted person alone.
        (Identity("okta", "3", groups=frozenset({"platform-admins"})), None),
        (Identity("google", "4", hosted_domain="example.com"), DEFAULTS),
        (
            Identity(
                "google", "5", email="root@example.com", hosted_domain="example.com"
            ),
            DEFAULTS | {"oneberth/admin"},
        ),
        (Identity("google", "6", email="root@example.com"), None),
        (Identity("github", "7", groups=frozenset({"platform-users"})), None),
    ],
)
def test_the_roles_of_an_identity(
    identity: Identity, expected: frozenset[str] | None
) -> None:
    assert roles_of(identity, POLICY, REGISTRY.default_roles) == expected


def test_the_registry_knows_each_application_default_and_the_roles_of_people() -> None:
    assert REGISTRY.apps == ("oneberth", "neorc", "robinauts")
    assert REGISTRY.default_roles == DEFAULTS
    assert REGISTRY.people_roles == {
        "oneberth/admin",
        "neorc/user",
        "robinauts/user",
        "robinauts/admin",
    }
    assert REGISTRY.has_permission(TOKENS_MANAGE)
    assert not REGISTRY.has_permission("neorc/runs:delete")


@pytest.mark.parametrize(
    ("grants", "problem"),
    [
        (
            (GrantEntry(Match("okta", Matcher.EVERYONE), frozenset({"neorc/admin"})),),
            "not a registered role",
        ),
        (
            (GrantEntry(Match("okta", Matcher.EVERYONE), frozenset({"neorc/worker"})),),
            "not a role for people",
        ),
        (
            (
                GrantEntry(
                    Match("okta", Matcher.EVERYONE), frozenset({"oneberth/launcher"})
                ),
            ),
            "not a role for people",
        ),
    ],
)
def test_a_policy_grants_registered_roles_for_people(
    grants: tuple[GrantEntry, ...], problem: str
) -> None:
    with pytest.raises(InvalidValueError, match=problem):
        Policy(allow=(), grants=grants).check(REGISTRY)


# Names.


@pytest.mark.parametrize(
    ("text", "permission", "role"),
    [
        ("neorc/runs:start", True, False),
        ("neorc/worker", True, True),
        ("neorc/external-trigger", True, True),
        ("oneberth/tokens:manage", True, False),
        ("neorc", False, False),
        ("/runs:start", False, False),
        ("Neorc/runs:start", False, False),
        ("neorc/runs:start:now", False, False),
        ("neorc/", False, False),
        ("neorc/runs start", False, False),
    ],
)
def test_names_of_permissions_and_roles(
    text: str, permission: bool, role: bool
) -> None:
    assert (is_permission_name(text), is_role_name(text)) == (permission, role)


@pytest.mark.parametrize(
    ("fields", "problem"),
    [
        ({"permissions": frozenset({"robinauts/x:y"})}, "is not neorc's"),
        (
            {"roles": (Role("robinauts/r", frozenset()),)},
            "role 'robinauts/r' is not neorc's",
        ),
        (
            {"roles": (Role("neorc/r", frozenset({"neorc/x:y"})),)},
            "'neorc/x:y' is not declared",
        ),
        (
            {"roles": (Role("neorc/r", frozenset()), Role("neorc/r", frozenset()))},
            "declared twice",
        ),
        ({"default": "neorc/user"}, "default role 'neorc/user' is not declared"),
        (
            {"roles": (Role("neorc/ci", frozenset()),), "default": "neorc/ci"},
            "is not for people",
        ),
        ({"app": "Neorc"}, "not an application name"),
    ],
)
def test_a_malformed_role_table_is_refused(
    fields: dict[str, Any], problem: str
) -> None:
    table: dict[str, Any] = {"app": "neorc", "permissions": frozenset(), "roles": ()}
    with pytest.raises(InvalidValueError, match=re.escape(problem)):
        RoleTable(**(table | fields))


def test_a_role_with_a_resource_is_not_for_people() -> None:
    with pytest.raises(InvalidValueError, match="needs a resource"):
        Role("neorc/worker", frozenset(), resource="queue", people=True)


def test_an_application_registers_once() -> None:
    with pytest.raises(InvalidValueError, match="registered already"):
        Registry([NEORC, NEORC])


# Decisions.

USER = frozenset({Grant("neorc/user"), Grant("robinauts/user")})
WORKER = frozenset({Grant("neorc/worker", "python-gpu")})


@pytest.mark.parametrize(
    ("grants", "permission", "resource", "expected"),
    [
        (USER, "neorc/runs:start", None, True),
        (USER, "neorc/runs:start", "any", True),
        (USER, "neorc/tasks:claim", None, False),
        (USER, "robinauts/config:edit", None, False),
        (USER | {Grant("robinauts/admin")}, "robinauts/config:edit", None, True),
        (WORKER, "neorc/tasks:claim", "python-gpu", True),
        (WORKER, "neorc/tasks:claim", "default", False),
        (WORKER, "neorc/tasks:claim", None, False),
        (WORKER, "neorc/runs:read", "python-gpu", False),
        (frozenset({Grant("oneberth/launcher")}), TOKENS_MANAGE, None, True),
        (frozenset({Grant("oneberth/admin")}), TOKENS_MANAGE, None, True),
        (USER, TOKENS_MANAGE, None, False),
        (frozenset({Grant("gone/role")}), "gone/x:y", None, False),
        (frozenset(), "neorc/runs:read", None, False),
        (USER, "neorc/runs:delete", None, False),
    ],
)
def test_a_decision(
    grants: frozenset[Grant], permission: str, resource: str | None, expected: bool
) -> None:
    assert REGISTRY.allows(grants, permission, resource) is expected


@pytest.mark.parametrize(
    ("grants", "permission", "resource", "expected"),
    [
        (WORKER, "neorc/tasks:claim", None, True),
        (WORKER, "neorc/tasks:claim", "python-gpu", True),
        (WORKER, "neorc/tasks:claim", "default", False),
        (WORKER, "neorc/runs:read", None, False),
        (USER, "neorc/runs:start", None, True),
        (USER, "neorc/tasks:claim", None, False),
    ],
)
def test_a_bound_grant_holds_without_a_resource_where_the_request_says_bound(
    grants: frozenset[Grant], permission: str, resource: str | None, expected: bool
) -> None:
    assert REGISTRY.allows(grants, permission, resource, bound=True) is expected


@pytest.mark.parametrize(
    ("grant", "problem"),
    [
        (Grant("neorc/worker"), "needs a queue"),
        (Grant("neorc/ci", "q"), "holds for every resource"),
        (Grant("neorc/worker", "bad queue"), "is not a queue name"),
        (Grant("neorc/nobody"), "not a registered role"),
    ],
)
def test_a_grant_names_a_role_and_the_resource_it_needs(
    grant: Grant, problem: str
) -> None:
    with pytest.raises(InvalidValueError, match=problem):
        REGISTRY.check_grant(grant)


@pytest.mark.parametrize(
    ("permission", "expected"),
    [
        ("neorc/tasks:claim", True),
        ("neorc/runs:read", False),
        ("neorc/flows:upload", False),
        (TOKENS_MANAGE, False),
        ("neorc/unknown:x", False),
    ],
)
def test_a_worker_role_is_one_bound_to_a_resource(
    permission: str, expected: bool
) -> None:
    assert REGISTRY.held_by_worker_role(permission) is expected


@pytest.mark.parametrize(
    ("grants", "permission", "expected"),
    [
        (frozenset({Grant("neorc/worker", "gpu")}), "neorc/tasks:claim", (True, "gpu")),
        (
            frozenset({Grant("neorc/worker", "gpu"), Grant("neorc/worker", "cpu")}),
            "neorc/tasks:claim",
            (True, None),
        ),
        (
            frozenset({Grant("neorc/worker", "gpu"), Grant("neorc/user")}),
            "neorc/runs:read",
            (True, None),
        ),
        (frozenset({Grant("neorc/user")}), "neorc/tasks:claim", (False, None)),
        (frozenset(), "neorc/tasks:claim", (False, None)),
    ],
)
def test_the_resource_a_grant_confines_a_permission_to(
    grants: frozenset[Grant], permission: str, expected: tuple[bool, str | None]
) -> None:
    assert REGISTRY.bound_resource(grants, permission) == expected


def test_the_roles_a_service_token_may_hold() -> None:
    names = [role.name for role in REGISTRY.service_roles]

    assert names == ["neorc/worker", "neorc/ci"]
