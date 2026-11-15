# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The store on a real PostgreSQL, held to the contract.

Beyond the contract: the schema it lives in, and the version it refuses.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg  # type: ignore[import-untyped]
import pytest

from oneberth.identity import (
    SCHEMA_VERSION,
    IdentityError,
    IdentityStore,
    SchemaVersionError,
    check_schema,
)
from oneberth.identity.postgres import SCHEMA, PostgresIdentityStore
from oneberth.identity.postgres._schema import TABLES
from oneberth.identity.testing.contracts import IdentityStoreContract

pytestmark = pytest.mark.postgres

SCRATCH = "oneberth_scratch"
"""A schema the tests of the setup create and drop, beside the store's own."""


async def _execute(database_url: str, *statements: str) -> None:
    conn = await asyncpg.connect(database_url)
    try:
        for statement in statements:
            await conn.execute(statement)
    finally:
        await conn.close()


@pytest.fixture
async def pg_store(database_url: str) -> AsyncIterator[PostgresIdentityStore]:
    """The store in the schema ``oneberth``, set up and emptied."""
    async with PostgresIdentityStore(database_url) as store:
        await store.setup()
        tables = ", ".join(f"{SCHEMA}.{t}" for t in TABLES if t != "schema_version")
        await _execute(database_url, f"TRUNCATE {tables}")
        yield store


@pytest.fixture
async def scratch(database_url: str) -> AsyncIterator[str]:
    """An empty schema name, dropped after the test."""
    await _execute(database_url, f"DROP SCHEMA IF EXISTS {SCRATCH} CASCADE")
    yield SCRATCH
    await _execute(database_url, f"DROP SCHEMA IF EXISTS {SCRATCH} CASCADE")


class TestPostgresIdentityStore(IdentityStoreContract):
    @pytest.fixture
    def store(self, pg_store: PostgresIdentityStore) -> IdentityStore:
        return pg_store


async def test_the_setup_creates_its_schema_and_records_the_version(
    database_url: str, scratch: str
) -> None:
    async with PostgresIdentityStore(database_url, schema=scratch) as store:
        assert await store.schema_version() is None
        with pytest.raises(SchemaVersionError, match="not set up"):
            await check_schema(store)

        await store.setup()
        await store.setup()

        assert await store.schema_version() == SCHEMA_VERSION
        await check_schema(store)

    conn = await asyncpg.connect(database_url)
    try:
        tables = await conn.fetch(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = $1 ORDER BY table_name",
            scratch,
        )
    finally:
        await conn.close()
    assert sorted(row["table_name"] for row in tables) == sorted(TABLES)


async def test_a_schema_of_another_version_is_refused_and_left_as_it_is(
    database_url: str, scratch: str
) -> None:
    async with PostgresIdentityStore(database_url, schema=scratch) as store:
        await store.setup()
    await _execute(
        database_url,
        f"UPDATE {scratch}.schema_version SET version = {SCHEMA_VERSION + 1}",
        f"DROP TABLE {scratch}.users CASCADE",
    )

    async with PostgresIdentityStore(database_url, schema=scratch) as store:
        with pytest.raises(SchemaVersionError, match=f"version {SCHEMA_VERSION + 1}"):
            await check_schema(store)
        with pytest.raises(SchemaVersionError, match=f"version {SCHEMA_VERSION + 1}"):
            await store.setup()
        assert await store.schema_version() == SCHEMA_VERSION + 1

    conn = await asyncpg.connect(database_url)
    try:
        users = await conn.fetchval("SELECT to_regclass($1)", f"{scratch}.users")
    finally:
        await conn.close()
    assert users is None


async def test_a_store_that_is_not_open_says_so(database_url: str) -> None:
    store = PostgresIdentityStore(database_url)

    with pytest.raises(IdentityError, match="not open"):
        await store.schema_version()
