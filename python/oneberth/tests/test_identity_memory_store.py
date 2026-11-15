# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The store's contract suite on the memory store, and its schema version."""

from __future__ import annotations

import pytest

from oneberth.identity import (
    SCHEMA_VERSION,
    IdentityStore,
    SchemaVersionError,
    check_schema,
)
from oneberth.identity.memory import MemoryIdentityStore
from oneberth.identity.testing.contracts import IdentityStoreContract


class TestMemoryIdentityStore(IdentityStoreContract):
    @pytest.fixture
    async def store(self) -> IdentityStore:
        store = MemoryIdentityStore()
        await store.setup()
        return store


async def test_a_store_nobody_set_up_is_refused_until_it_is() -> None:
    store = MemoryIdentityStore()

    with pytest.raises(SchemaVersionError, match="not set up"):
        await check_schema(store)
    await store.setup()
    await check_schema(store)


async def test_a_store_of_another_version_is_refused() -> None:
    store = MemoryIdentityStore(schema_version=SCHEMA_VERSION + 1)

    with pytest.raises(SchemaVersionError, match="version 2"):
        await check_schema(store)
    with pytest.raises(SchemaVersionError):
        await store.setup()
    assert await store.schema_version() == SCHEMA_VERSION + 1
