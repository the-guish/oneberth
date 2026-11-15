# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The store on a real SQLite file, held to the contract.

Beyond the contract: what the file keeps across a restart, how it is set up for
a crash, and the files it refuses.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from oneberth.identity import (
    SCHEMA_VERSION,
    IdentityError,
    IdentityStore,
    SchemaVersionError,
    check_schema,
)
from oneberth.identity.sqlite import APPLICATION_ID, FILE_NAME, SqliteIdentityStore
from oneberth.identity.testing.contracts import IdentityStoreContract
from oneberth.identity.testing.contracts._store import ADA, T0


@pytest.fixture
async def sqlite_store(tmp_path: Path) -> AsyncIterator[SqliteIdentityStore]:
    async with SqliteIdentityStore(tmp_path / FILE_NAME) as store:
        await store.setup()
        yield store


class TestSqliteIdentityStore(IdentityStoreContract):
    @pytest.fixture
    def store(self, sqlite_store: SqliteIdentityStore) -> IdentityStore:
        return sqlite_store


def _pragmas(path: Path) -> tuple[str, int, int, list[str]]:
    conn = sqlite3.connect(path)
    try:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        application = conn.execute("PRAGMA application_id").fetchone()[0]
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
    finally:
        conn.close()
    return journal, version, application, tables


async def test_a_new_file_is_set_up_for_a_crash_and_keeps_what_it_holds(
    tmp_path: Path,
) -> None:
    path = tmp_path / FILE_NAME
    async with SqliteIdentityStore(path) as store:
        assert await store.schema_version() is None
        with pytest.raises(SchemaVersionError, match="not set up"):
            await check_schema(store)
        await store.setup()
        await store.setup()
        user = await store.upsert_user(ADA, user_id=uuid.uuid4(), now=T0)

    async with SqliteIdentityStore(path) as store:
        await check_schema(store)
        assert await store.user(user.id) == user

    journal, version, application, tables = _pragmas(path)
    assert (journal, version, application) == ("wal", SCHEMA_VERSION, APPLICATION_ID)
    assert "users" in tables


async def test_a_file_of_another_version_is_refused_and_left_as_it_is(
    tmp_path: Path,
) -> None:
    path = tmp_path / FILE_NAME
    async with SqliteIdentityStore(path) as store:
        await store.setup()
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()

    with pytest.raises(SchemaVersionError, match=f"version {SCHEMA_VERSION + 1}"):
        await SqliteIdentityStore(path).open()

    assert _pragmas(path)[1] == SCHEMA_VERSION + 1


async def test_a_file_of_another_application_is_refused_and_left_as_it_is(
    tmp_path: Path,
) -> None:
    path = tmp_path / "notes.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE notes (body TEXT)")
    conn.close()

    with pytest.raises(SchemaVersionError, match="not a oneberth store"):
        await SqliteIdentityStore(path).open()

    assert _pragmas(path) == ("delete", 0, 0, ["notes"])


async def test_a_store_that_is_not_open_says_so(tmp_path: Path) -> None:
    with pytest.raises(IdentityError, match="not open"):
        await SqliteIdentityStore(tmp_path / FILE_NAME).schema_version()
