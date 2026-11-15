# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""Permissions and roles, as data that each application registers under its name.

A permission is one operation of one application, such as ``neorc/runs:start``.
A role is a named set of permissions of the same application, such as
``neorc/worker``. A grant gives a role to a principal, for every resource or
for one. The core knows no application's roles: each application hands its
``RoleTable`` to a ``Registry`` when its backend starts, and oneberth registers
``ONEBERTH_ROLES`` the same way.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from oneberth.identity._errors import InvalidValueError

_APP = re.compile(r"[a-z][a-z0-9-]{0,39}")
_PERMISSION = re.compile(r"[a-z0-9][a-z0-9_.-]*(:[a-z0-9][a-z0-9_.-]*)?")
_ROLE = re.compile(r"[a-z0-9][a-z0-9_.-]*")
_RESOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")


def is_app_name(text: str) -> bool:
    """Whether ``text`` may name an application: ``neorc``, ``robinauts``."""
    return _APP.fullmatch(text) is not None


def is_permission_name(text: str) -> bool:
    """Whether ``text`` is spelt as a permission: ``<app>/<thing>:<verb>``."""
    app, slash, rest = text.partition("/")
    return bool(slash) and is_app_name(app) and _PERMISSION.fullmatch(rest) is not None


def is_role_name(text: str) -> bool:
    """Whether ``text`` is spelt as a role: ``<app>/<name>``."""
    app, slash, rest = text.partition("/")
    return bool(slash) and is_app_name(app) and _ROLE.fullmatch(rest) is not None


def is_resource_name(text: str) -> bool:
    """Whether ``text`` may name a resource: a queue, a worker name."""
    return _RESOURCE.fullmatch(text) is not None


def app_of(name: str) -> str:
    """The application a permission or a role belongs to: what comes before ``/``."""
    return name.partition("/")[0]


@dataclass(frozen=True, slots=True)
class Role:
    """A named set of permissions, declared by an application."""

    name: str
    permissions: frozenset[str]
    resource: str | None = None
    """What a grant of this role is bound to, such as ``queue``; ``None`` when a
    grant holds for every resource. A role that needs a resource is given to a
    service token alone, since a person's grant names no resource."""
    people: bool = False
    """Whether a person may hold this role. The local user holds every such role."""

    def __post_init__(self) -> None:
        if not is_role_name(self.name):
            raise InvalidValueError(f"{self.name!r} is not a role name: <app>/<name>")
        if self.resource is not None and not _ROLE.fullmatch(self.resource):
            raise InvalidValueError(
                f"role {self.name!r}: {self.resource!r} is not a kind of resource"
            )
        if self.people and self.resource is not None:
            raise InvalidValueError(
                f"role {self.name!r} needs a resource, and a person's grant names none"
            )


@dataclass(frozen=True, slots=True)
class RoleTable:
    """An application's permissions and roles, and the role every person gets."""

    app: str
    permissions: frozenset[str]
    roles: tuple[Role, ...]
    default: str | None = None
    """The role an allow entry gives each person it admits; ``None`` for none."""

    def __post_init__(self) -> None:
        if not is_app_name(self.app):
            raise InvalidValueError(f"{self.app!r} is not an application name")
        problems: list[str] = []
        for permission in sorted(self.permissions):
            if not is_permission_name(permission):
                problems.append(f"{permission!r} is not a permission name")
            elif app_of(permission) != self.app:
                problems.append(f"permission {permission!r} is not {self.app}'s")
        names = [role.name for role in self.roles]
        for name in sorted({n for n in names if names.count(n) > 1}):
            problems.append(f"role {name!r} is declared twice")
        for role in self.roles:
            if app_of(role.name) != self.app:
                problems.append(f"role {role.name!r} is not {self.app}'s")
            for unknown in sorted(role.permissions - self.permissions):
                problems.append(f"role {role.name!r}: {unknown!r} is not declared")
        if self.default is not None:
            default = next((r for r in self.roles if r.name == self.default), None)
            if default is None:
                problems.append(f"default role {self.default!r} is not declared")
            elif not default.people:
                problems.append(f"default role {self.default!r} is not for people")
        if problems:
            raise InvalidValueError(f"role table of {self.app}: " + "; ".join(problems))


@dataclass(frozen=True, slots=True, order=True)
class Grant:
    """A role given to a principal, for every resource or, with one, for that one."""

    role: str
    resource: str | None = field(default=None)


class Registry:
    """The role tables of the applications of a backend. Fixed once it serves."""

    def __init__(self, tables: Iterable[RoleTable] = ()) -> None:
        self._tables: dict[str, RoleTable] = {}
        self._roles: dict[str, Role] = {}
        self._permissions: set[str] = set()
        for table in tables:
            self.register(table)

    def register(self, table: RoleTable) -> None:
        """Add an application's table. An application registers once."""
        if table.app in self._tables:
            raise InvalidValueError(
                f"the roles of {table.app!r} are registered already"
            )
        self._tables[table.app] = table
        self._roles.update((role.name, role) for role in table.roles)
        self._permissions.update(table.permissions)

    @property
    def apps(self) -> tuple[str, ...]:
        """The applications registered, in order."""
        return tuple(self._tables)

    @property
    def default_roles(self) -> frozenset[str]:
        """The default role of each application: what an allow entry gives."""
        return frozenset(t.default for t in self._tables.values() if t.default)

    @property
    def people_roles(self) -> frozenset[str]:
        """Every role a person may hold."""
        return frozenset(name for name, role in self._roles.items() if role.people)

    def has_permission(self, permission: str) -> bool:
        return permission in self._permissions

    def role(self, name: str) -> Role:
        """The role called ``name``; ``InvalidValueError`` when none is registered."""
        found = self._roles.get(name)
        if found is None:
            raise InvalidValueError(f"{name!r} is not a registered role")
        return found

    def check_grant(self, grant: Grant) -> None:
        """Raise ``InvalidValueError`` unless ``grant`` names a role and, when the
        role needs one, a resource."""
        role = self.role(grant.role)
        if role.resource is None:
            if grant.resource is not None:
                raise InvalidValueError(
                    f"role {role.name!r} holds for every resource: name none"
                )
        elif grant.resource is None:
            raise InvalidValueError(f"role {role.name!r} needs a {role.resource}")
        elif not is_resource_name(grant.resource):
            raise InvalidValueError(
                f"{grant.resource!r} is not a {role.resource} name: letters, digits, "
                "_, . and -"
            )

    def allows(
        self, grants: Iterable[Grant], permission: str, resource: str | None = None
    ) -> bool:
        """Whether ``grants`` hold ``permission``, on ``resource``.

        A grant bound to a resource holds on that resource alone. A request that
        names no resource is allowed by a bound grant too: the application then
        reads the resource from the principal's grant, as a worker's route reads
        its queue. An unknown permission or role allows nothing.
        """
        for grant in grants:
            role = self._roles.get(grant.role)
            if role is None or permission not in role.permissions:
                continue
            if grant.resource is None or resource is None or resource == grant.resource:
                return True
        return False


TOKENS_MANAGE = "oneberth/tokens:manage"
"""Mint, list and revoke service tokens."""

TICKETS_CREATE = "oneberth/tickets:create"
"""Ask for a ticket that signs the local user in. The launch secret's alone."""

ONEBERTH_ROLES = RoleTable(
    app="oneberth",
    permissions=frozenset({TOKENS_MANAGE, TICKETS_CREATE}),
    roles=(
        Role("oneberth/admin", frozenset({TOKENS_MANAGE}), people=True),
        Role("oneberth/launcher", frozenset({TOKENS_MANAGE, TICKETS_CREATE})),
    ),
)
"""oneberth's own permissions and roles, registered like any application's."""
