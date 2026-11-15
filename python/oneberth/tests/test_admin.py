# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The admin scripts, as an application's command line shows them.

Most tests run the commands on the memory store, through a connector of their
own. The last ones run the ``oneberth`` command on a real PostgreSQL.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest

from oneberth.admin import Admin, StoreAdmin, add_admin_commands, main
from oneberth.identity import (
    ONEBERTH_ROLES,
    Access,
    DeviceDescription,
    Identity,
    Match,
    Matcher,
    Policy,
    Registry,
    Role,
    RoleTable,
    SchemaVersionError,
    secret_hash,
)
from oneberth.identity.memory import MemoryIdentityStore
from oneberth.identity.testing import ManualClock
from oneberth.stores import opened_store

NEORC = RoleTable(
    app="neorc",
    permissions=frozenset({"neorc/tasks:claim", "neorc/flows:upload"}),
    roles=(
        Role("neorc/worker", frozenset({"neorc/tasks:claim"}), resource="queue"),
        Role("neorc/ci", frozenset({"neorc/flows:upload"})),
    ),
)
REGISTRY = Registry([ONEBERTH_ROLES, NEORC])
ADA = Identity("okta", "ada", email="ada@example.com")
GRACE = Identity("okta", "grace", email="grace@example.com")
TWIN = Identity("google", "ada-g", email="ADA@example.com")


class MemoryConnector:
    """The deployment of a test: one memory store, one clock."""

    def __init__(self) -> None:
        self.clock = ManualClock()
        self.store = MemoryIdentityStore()

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

    @asynccontextmanager
    async def open(self, args: argparse.Namespace) -> AsyncIterator[Admin]:
        yield StoreAdmin(self.store, REGISTRY, clock=self.clock)

    def access(self) -> Access:
        policy = Policy(
            allow=(Match("okta", Matcher.EVERYONE), Match("google", Matcher.EVERYONE))
        )
        return Access(self.store, REGISTRY, policy, clock=self.clock)


@pytest.fixture
def deployment() -> MemoryConnector:
    return MemoryConnector()


def run(connector: object, *argv: str) -> int:
    """The application ``app`` with the admin commands, as its user types them."""
    parser = argparse.ArgumentParser(prog="app")
    commands = parser.add_subparsers(dest="command", required=True)
    add_admin_commands(commands, connector)  # type: ignore[arg-type]
    args = parser.parse_args(argv)
    status: int = args.handler(args)
    return status


def link_device(connector: MemoryConnector, identity: Identity, name: str) -> uuid.UUID:
    async def go() -> uuid.UUID:
        access = connector.access()
        signed_in = await access.sign_in(identity)
        code, pairing = await access.begin_pairing(signed_in.principal)
        claimed = await access.claim_pairing(code, DeviceDescription(name, "android"))
        device = await access.approve_pairing(
            signed_in.principal, pairing.id, claimed.number
        )
        return device.id

    return asyncio.run(go())


def test_the_operator_creates_lists_and_revokes_service_tokens(
    deployment: MemoryConnector, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(deployment, "store", "init") == 0
    assert "version 1" in capsys.readouterr().out

    assert (
        run(
            deployment,
            "tokens",
            "create",
            "worker-gpu",
            "--role",
            "neorc/worker",
            "--resource",
            "gpu",
        )
        == 0
    )
    created = capsys.readouterr()
    secret = created.out.strip()
    assert secret.startswith("ob_svc_")
    assert "neorc/worker on gpu" in created.err
    assert "only time" in created.err
    assert (
        run(
            deployment,
            "tokens",
            "create",
            "ci",
            "--role",
            "neorc/ci",
            "--expires-days",
            "1",
        )
        == 0
    )
    capsys.readouterr()
    deployment.clock.advance(timedelta(days=2))

    assert run(deployment, "tokens", "list") == 0
    listing = capsys.readouterr().out.splitlines()
    assert [line.split("\t")[:2] for line in listing] == [
        ["ci", "neorc/ci"],
        ["worker-gpu", "neorc/worker on gpu"],
    ]
    assert listing[0].endswith("expired 2026-01-06T09:00:00+00:00")
    assert listing[1].endswith("never expires")
    assert secret not in "\n".join(listing)

    assert run(deployment, "tokens", "revoke", "worker-gpu") == 0
    assert "revoked the token 'worker-gpu'" in capsys.readouterr().out
    assert run(deployment, "tokens", "revoke", "worker-gpu") == 1
    assert "no service token is called 'worker-gpu'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "error"),
    [
        (["x", "--role", "neorc/worker"], "needs a queue"),
        (["x", "--role", "neorc/ci", "--resource", "q"], "holds for every resource"),
        (["x", "--role", "robinauts/worker", "--resource", "w"], "not a registered"),
        (["x y", "--role", "neorc/ci"], "not a service token name"),
        (["x", "--role", "neorc/ci", "--expires-days", "0"], "--expires-days"),
    ],
)
def test_a_token_the_roles_do_not_allow_is_refused(
    deployment: MemoryConnector,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    error: str,
) -> None:
    assert run(deployment, "tokens", "create", *argv) == 1
    assert error in capsys.readouterr().err


def test_a_token_name_is_taken_once(
    deployment: MemoryConnector, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(deployment, "tokens", "create", "ci", "--role", "neorc/ci") == 0
    assert run(deployment, "tokens", "create", "ci", "--role", "neorc/ci") == 1
    assert "a service token called 'ci' exists" in capsys.readouterr().err


def test_clearing_sessions_signs_everyone_out(
    deployment: MemoryConnector, capsys: pytest.CaptureFixture[str]
) -> None:
    async def sign_in_twice() -> str:
        access = deployment.access()
        await access.sign_in(GRACE)
        return (await access.sign_in(ADA)).secret

    secret = asyncio.run(sign_in_twice())

    assert run(deployment, "sessions", "clear") == 0
    assert capsys.readouterr().out == "ended 2 sessions\n"
    found = deployment.store.session_by_hash(secret_hash(secret), deployment.clock())
    assert asyncio.run(found) is None


def test_the_operator_lists_and_ends_devices(
    deployment: MemoryConnector, capsys: pytest.CaptureFixture[str]
) -> None:
    ada_phone = link_device(deployment, ADA, "Ada's phone")
    deployment.clock.advance(timedelta(seconds=1))
    link_device(deployment, ADA, "Ada's tablet")
    deployment.clock.advance(timedelta(seconds=1))
    grace_phone = link_device(deployment, GRACE, "Grace's phone")

    assert run(deployment, "devices", "list") == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split("\t")[1:4] for line in lines] == [
        ["ada@example.com", "Ada's phone", "android"],
        ["ada@example.com", "Ada's tablet", "android"],
        ["grace@example.com", "Grace's phone", "android"],
    ]
    assert lines[0].startswith(str(ada_phone))
    assert "linked 2026-01-05T09:00:00+00:00" in lines[0]

    assert run(deployment, "devices", "end", "--user", "ADA@example.com") == 0
    out = capsys.readouterr().out
    assert out.count("ended\t") == 2
    assert out.endswith("ended 2 devices\n")

    assert run(deployment, "devices", "end", "--device", str(grace_phone)) == 0
    assert "Grace's phone" in capsys.readouterr().out
    assert run(deployment, "devices", "end", "--device", str(grace_phone)) == 1
    assert f"no device has the id {grace_phone}" in capsys.readouterr().err

    link_device(deployment, GRACE, "Grace's new phone")
    assert run(deployment, "devices", "end", "--all") == 0
    assert capsys.readouterr().out.endswith("ended 1 device\n")


def test_an_email_of_several_users_ends_no_device(
    deployment: MemoryConnector, capsys: pytest.CaptureFixture[str]
) -> None:
    link_device(deployment, ADA, "phone")
    link_device(deployment, TWIN, "phone")

    assert run(deployment, "devices", "end", "--user", "ada@example.com") == 1
    assert "2 users have the email" in capsys.readouterr().err
    assert run(deployment, "devices", "end", "--user", "nobody@example.com") == 1
    assert "no user has the email" in capsys.readouterr().err
    assert len(asyncio.run(deployment.store.all_devices())) == 2


def test_an_end_names_what_to_end(deployment: MemoryConnector) -> None:
    with pytest.raises(SystemExit):
        run(deployment, "devices", "end")


# The oneberth command, on PostgreSQL.


@pytest.fixture
def pg_url(database_url: str) -> Iterator[str]:
    """The database, with the schema oneberth set up and emptied."""

    async def empty() -> None:
        conn = await asyncpg.connect(database_url)
        try:
            await conn.execute("DROP SCHEMA IF EXISTS oneberth CASCADE")
        finally:
            await conn.close()

    asyncio.run(empty())
    yield database_url
    asyncio.run(empty())


@pytest.mark.postgres
def test_the_oneberth_command_works_on_postgresql(
    pg_url: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main(["store", "init", "--database-url", pg_url])
    assert "version 1" in capsys.readouterr().out

    monkeypatch.setenv("ONEBERTH_DATABASE_URL", pg_url)
    main(["tokens", "create", "ops", "--role", "oneberth/admin"])
    assert capsys.readouterr().out.startswith("ob_svc_")
    main(["tokens", "list"])
    assert capsys.readouterr().out.startswith("ops\toneberth/admin\t")
    main(["sessions", "clear"])
    assert capsys.readouterr().out == "ended 0 sessions\n"
    main(["devices", "list"])
    assert capsys.readouterr().out == ""
    with pytest.raises(SystemExit) as refused:
        main(["tokens", "create", "w", "--role", "neorc/worker", "--resource", "q"])
    assert refused.value.code == 1
    assert "not a registered role" in capsys.readouterr().err


def test_the_oneberth_command_needs_a_database(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ONEBERTH_DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as refused:
        main(["tokens", "list"])

    assert refused.value.code == 2
    assert "give --database-url" in capsys.readouterr().err


# How a backend opens its store.


async def test_the_desktop_opens_its_file_and_sets_it_up(tmp_path: Path) -> None:
    with pytest.raises(SchemaVersionError, match="oneberth store init"):
        async with opened_store(data_dir=tmp_path):
            pass

    async with opened_store(data_dir=tmp_path, setup=True) as store:
        assert await store.schema_version() == 1
    assert (tmp_path / "oneberth.db").exists()
    async with opened_store(data_dir=tmp_path) as store:
        assert await store.users_with_email("a@example.com") == []


async def test_a_store_is_named_once() -> None:
    with pytest.raises(ValueError, match="one of"):
        async with opened_store():
            pass
    with pytest.raises(ValueError, match="one of"):
        async with opened_store(database_url="postgresql://x", data_dir="."):
            pass


@pytest.mark.postgres
async def test_the_cluster_opens_its_schema(database_url: str) -> None:
    async with opened_store(database_url=database_url, setup=True) as store:
        assert await store.schema_version() == 1
