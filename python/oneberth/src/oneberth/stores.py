# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""How a backend opens the deployment's store: PostgreSQL by URL, or SQLite by folder.

The cluster names a PostgreSQL database, and the store is its schema
``oneberth``. The desktop names its data directory, and the store is the file
``oneberth.db`` in it. ``opened_store`` opens either, checks its version and
closes it at the end of the block.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from oneberth.identity import IdentityStore, check_schema


@asynccontextmanager
async def opened_store(
    *,
    database_url: str | None = None,
    data_dir: str | os.PathLike[str] | None = None,
    setup: bool = False,
) -> AsyncIterator[IdentityStore]:
    """The store, open and at this oneberth's version, for the block.

    Give exactly one of ``database_url`` and ``data_dir``. With ``setup``, the
    tables are created first, as the desktop's backend does at each start. The
    cluster runs ``oneberth store init`` once instead. Raises
    ``SchemaVersionError`` for a store of another version, or one not set up.
    """
    if (database_url is None) == (data_dir is None):
        raise ValueError("give one of database_url and data_dir")
    store: IdentityStore
    if database_url is not None:
        from oneberth.identity.postgres import PostgresIdentityStore

        store = postgres = PostgresIdentityStore(database_url)
        opening, closing = postgres.open, postgres.aclose
    else:
        from oneberth.identity.sqlite import FILE_NAME, SqliteIdentityStore

        assert data_dir is not None
        store = sqlite = SqliteIdentityStore(Path(data_dir) / FILE_NAME)
        opening, closing = sqlite.open, sqlite.aclose
    await opening()
    try:
        if setup:
            await store.setup()
        await check_schema(store)
        yield store
    finally:
        await closing()
