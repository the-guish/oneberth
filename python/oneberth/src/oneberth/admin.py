# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The admin scripts both applications reuse: store, tokens, sessions and devices.

    oneberth store init
    oneberth tokens create NAME --role ROLE [--resource R] [--expires-days N]
    oneberth tokens list
    oneberth tokens revoke NAME
    oneberth sessions clear
    oneberth devices list
    oneberth devices end (--user EMAIL | --device ID | --all)

The scripts come in three layers:

- ``Admin`` is what the scripts ask of a deployment. ``StoreAdmin`` answers on
  the store directly, as the operator of a PostgreSQL store does. The desktop's
  scripts will ask the backend instead, through another ``Admin``.
- A ``Connector`` adds the options that find a deployment, such as
  ``--database-url``, and opens an ``Admin`` from them.
- ``add_admin_commands`` adds the commands to an application's own command
  line, under its own name: ``neorc tokens create`` runs the same code as
  ``oneberth tokens create``. Each command sets ``handler``: call
  ``args.handler(args)`` for the exit status.

The scripts use the standard library alone. ``PostgresConnector`` needs the
``postgres`` extra when it opens the store.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime, timedelta
from typing import Protocol

from oneberth.identity import (
    ONEBERTH_ROLES,
    OPERATOR,
    Access,
    Clock,
    DeviceSession,
    IdentityError,
    IdentityStore,
    InvalidValueError,
    NotFoundError,
    Registry,
    ServiceToken,
    User,
    system_clock,
)

DATABASE_URL_ENV = "ONEBERTH_DATABASE_URL"
"""Where ``oneberth`` reads the database URL when ``--database-url`` is not given."""


class Admin(Protocol):
    """What the admin scripts ask of a deployment."""

    def now(self) -> datetime: ...

    async def init_store(self) -> int:
        """Create the store's tables; the schema version."""
        ...

    async def create_token(
        self,
        name: str,
        role: str,
        *,
        resource: str | None = None,
        expires_in: timedelta | None = None,
    ) -> tuple[str, ServiceToken]:
        """A new service token and its secret, which is shown once."""
        ...

    async def tokens(self) -> list[ServiceToken]: ...

    async def revoke_token(self, name: str) -> ServiceToken:
        """End the service token called ``name``; ``NotFoundError`` for none."""
        ...

    async def clear_sessions(self) -> int:
        """End every browser session; how many there were."""
        ...

    async def devices(self) -> list[tuple[User, DeviceSession]]: ...

    async def end_devices(
        self,
        *,
        email: str | None = None,
        device_id: uuid.UUID | None = None,
        every: bool = False,
    ) -> list[tuple[User | None, DeviceSession]]:
        """End the devices of the user with ``email``, one device, or every one."""
        ...


class StoreAdmin:
    """The admin scripts on the store directly, as the operator.

    ``registry`` holds the roles a service token may be given: an application
    passes its own with oneberth's.
    """

    def __init__(
        self, store: IdentityStore, registry: Registry, *, clock: Clock = system_clock
    ) -> None:
        self._store = store
        self._access = Access(store, registry, clock=clock)

    def now(self) -> datetime:
        return self._access.now()

    async def init_store(self) -> int:
        await self._store.setup()
        version = await self._store.schema_version()
        assert version is not None
        return version

    async def create_token(
        self,
        name: str,
        role: str,
        *,
        resource: str | None = None,
        expires_in: timedelta | None = None,
    ) -> tuple[str, ServiceToken]:
        return await self._access.create_service_token(
            name, role, resource=resource, expires_in=expires_in, by=OPERATOR
        )

    async def tokens(self) -> list[ServiceToken]:
        return await self._access.service_tokens(by=OPERATOR)

    async def revoke_token(self, name: str) -> ServiceToken:
        for token in await self._access.service_tokens(by=OPERATOR):
            if token.name == name:
                await self._access.revoke_service_token(token.id, by=OPERATOR)
                return token
        raise NotFoundError(f"no service token is called {name!r}")

    async def clear_sessions(self) -> int:
        return await self._access.end_sessions()

    async def devices(self) -> list[tuple[User, DeviceSession]]:
        return await self._store.all_devices()

    async def end_devices(
        self,
        *,
        email: str | None = None,
        device_id: uuid.UUID | None = None,
        every: bool = False,
    ) -> list[tuple[User | None, DeviceSession]]:
        if [email is not None, device_id is not None, every].count(True) != 1:
            raise InvalidValueError("name a user's email, a device, or every device")
        owners = {user.id: user for user, _ in await self._store.all_devices()}
        if email is not None:
            users = await self._store.users_with_email(email)
            if not users:
                raise NotFoundError(f"no user has the email {email}")
            if len(users) > 1:
                raise InvalidValueError(
                    f"{len(users)} users have the email {email}, one per provider: "
                    "end their devices one by one by id"
                )
            ended = await self._store.delete_devices(user_id=users[0].id)
        elif device_id is not None:
            ended = await self._store.delete_devices(device_id=device_id)
            if not ended:
                raise NotFoundError(f"no device has the id {device_id}")
        else:
            ended = await self._store.delete_devices(every=True)
        return [(owners.get(device.user_id), device) for device in ended]


class Connector(Protocol):
    """Finds a deployment from the command line, and opens its ``Admin``."""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add the options that find the deployment to one command."""
        ...

    def open(self, args: argparse.Namespace) -> AbstractAsyncContextManager[Admin]:
        """The deployment's ``Admin`` for one command. Raises ``ConnectError``."""
        ...


class ConnectError(Exception):
    """The command line does not say how to reach the deployment."""


class PostgresConnector:
    """The store on PostgreSQL, by ``--database-url`` or a variable."""

    def __init__(
        self, registry: Registry, *, database_url_env: str = DATABASE_URL_ENV
    ) -> None:
        self._registry = registry
        self._env = database_url_env

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--database-url",
            default=None,
            help=f"the deployment's PostgreSQL database; defaults to ${self._env}",
        )

    @asynccontextmanager
    async def open(self, args: argparse.Namespace) -> AsyncIterator[Admin]:
        url = args.database_url or os.environ.get(self._env)
        if not url:
            raise ConnectError(f"no database: give --database-url, or set ${self._env}")
        try:
            from oneberth.identity.postgres import PostgresIdentityStore
        except ImportError:
            raise ConnectError(
                "the PostgreSQL store needs the postgres extra: oneberth[postgres]"
            ) from None
        async with PostgresIdentityStore(url, max_size=1) as store:
            yield StoreAdmin(store, self._registry)


Command = Callable[[Admin, argparse.Namespace], Awaitable[int]]


def add_admin_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    connector: Connector,
) -> None:
    """Add ``store``, ``tokens``, ``sessions`` and ``devices`` to ``commands``.

    ``commands`` is what ``ArgumentParser.add_subparsers`` returned for the
    application's own command line. Each command sets ``handler``.
    """

    def command(
        parent: argparse._SubParsersAction[argparse.ArgumentParser],
        name: str,
        run: Command,
        help: str,
    ) -> argparse.ArgumentParser:
        parser = parent.add_parser(name, help=help, description=help)
        connector.add_arguments(parser)
        parser.set_defaults(handler=_handler(connector, run))
        return parser

    store = commands.add_parser("store", help="the deployment's oneberth store")
    store_commands = store.add_subparsers(dest="store_command", required=True)
    command(store_commands, "init", _store_init, "create the store's tables")

    tokens = commands.add_parser("tokens", help="the service tokens")
    tokens_commands = tokens.add_subparsers(dest="tokens_command", required=True)
    create = command(
        tokens_commands,
        "create",
        _tokens_create,
        "create a service token and print its secret, which is shown once",
    )
    create.add_argument("name", help="letters, digits, _, . and -")
    create.add_argument("--role", required=True, help="such as neorc/worker")
    create.add_argument(
        "--resource",
        default=None,
        help="what the role is bound to, when it needs one: a queue, a worker name",
    )
    create.add_argument(
        "--expires-days",
        type=float,
        default=None,
        help="stop accepting it after this many days; never by default",
    )
    command(tokens_commands, "list", _tokens_list, "list the service tokens")
    revoke = command(
        tokens_commands, "revoke", _tokens_revoke, "stop accepting a token, at once"
    )
    revoke.add_argument("name")

    sessions = commands.add_parser("sessions", help="the browser sessions")
    sessions_commands = sessions.add_subparsers(dest="sessions_command", required=True)
    command(sessions_commands, "clear", _sessions_clear, "sign everyone out")

    devices = commands.add_parser("devices", help="the linked devices")
    devices_commands = devices.add_subparsers(dest="devices_command", required=True)
    command(devices_commands, "list", _devices_list, "every linked device")
    end = command(
        devices_commands,
        "end",
        _devices_end,
        "end linked devices: they are refused at once",
    )
    which = end.add_mutually_exclusive_group(required=True)
    which.add_argument("--user", metavar="EMAIL", help="every device of that user")
    which.add_argument("--device", metavar="ID", type=uuid.UUID, help="one device")
    which.add_argument("--all", action="store_true", help="every device")


def _handler(connector: Connector, run: Command) -> Callable[[argparse.Namespace], int]:
    def handler(args: argparse.Namespace) -> int:
        async def go() -> int:
            async with connector.open(args) as admin:
                return await run(admin, args)

        try:
            return asyncio.run(go())
        except ConnectError as error:
            print(error, file=sys.stderr)
            return 2
        except IdentityError as error:
            print(error, file=sys.stderr)
            return 1

    return handler


async def _store_init(admin: Admin, args: argparse.Namespace) -> int:
    version = await admin.init_store()
    print(f"the store is set up at version {version}")
    return 0


async def _tokens_create(admin: Admin, args: argparse.Namespace) -> int:
    days = args.expires_days
    if days is not None and not 0 < days <= 5 * 366:
        raise InvalidValueError("--expires-days must be over 0 and at most 1830")
    secret, token = await admin.create_token(
        args.name,
        args.role,
        resource=args.resource,
        expires_in=None if days is None else timedelta(days=days),
    )
    until = token.expires_at.isoformat() if token.expires_at else "never"
    print(
        f"created the token {token.name!r}, {_grant(token)}, expiring {until}. "
        "This is the only time its secret is shown:",
        file=sys.stderr,
    )
    print(secret)
    return 0


async def _tokens_list(admin: Admin, args: argparse.Namespace) -> int:
    now = admin.now()
    for token in await admin.tokens():
        if token.expires_at is None:
            expiry = "never expires"
        elif token.expires_at <= now:
            expiry = f"expired {_when(token.expires_at)}"
        else:
            expiry = f"expires {_when(token.expires_at)}"
        created = f"created {_when(token.created_at)}"
        print(f"{token.name}\t{_grant(token)}\t{created}\t{expiry}")
    return 0


async def _tokens_revoke(admin: Admin, args: argparse.Namespace) -> int:
    token = await admin.revoke_token(args.name)
    print(f"revoked the token {token.name!r}")
    return 0


async def _sessions_clear(admin: Admin, args: argparse.Namespace) -> int:
    count = await admin.clear_sessions()
    print(f"ended {count} session{'' if count == 1 else 's'}")
    return 0


async def _devices_list(admin: Admin, args: argparse.Namespace) -> int:
    for user, device in await admin.devices():
        print(_device_line(user, device))
    return 0


async def _devices_end(admin: Admin, args: argparse.Namespace) -> int:
    ended = await admin.end_devices(
        email=args.user, device_id=args.device, every=args.all
    )
    for user, device in ended:
        print("ended\t" + _device_line(user, device))
    print(f"ended {len(ended)} device{'' if len(ended) == 1 else 's'}")
    return 0


def _grant(token: ServiceToken) -> str:
    grant = token.grant
    return grant.role if grant.resource is None else f"{grant.role} on {grant.resource}"


def _when(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _device_line(user: User | None, device: DeviceSession) -> str:
    """One device as the operator reads it: whose, what, and its three dates."""
    if user is None:
        who = str(device.user_id)
    else:
        who = user.email or f"{user.provider}:{user.subject}"
    return "\t".join(
        (
            str(device.id),
            who,
            device.device.name,
            device.device.platform,
            f"linked {_when(device.created_at)}",
            f"last used {_when(device.last_used_at)}",
            f"expires {_when(device.expires_at)}",
        )
    )


def main(argv: Sequence[str] | None = None) -> None:
    """The ``oneberth`` command. It knows oneberth's roles alone: an application
    shows the same commands with its own roles under its own name."""
    parser = argparse.ArgumentParser(
        prog="oneberth", description="the admin scripts of a oneberth deployment"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    add_admin_commands(commands, PostgresConnector(Registry([ONEBERTH_ROLES])))
    args = parser.parse_args(argv)
    status = args.handler(args)
    if status:
        raise SystemExit(status)
