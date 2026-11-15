# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The suite every identity store passes: memory, PostgreSQL and SQLite.

A suite is a class of tests written against the port alone. To run it on a
store, subclass it in a test module, under a name pytest collects, and provide
a ``store`` fixture that hands over an empty store, set up::

    class TestPostgresIdentityStore(IdentityStoreContract):
        @pytest.fixture
        async def store(self, database: str) -> AsyncIterator[IdentityStore]:
            store = PostgresIdentityStore(database)
            await store.setup()
            yield store
            await store.close()

The tests are coroutines, so the suite expects pytest-asyncio in ``auto``
mode. Call ``pytest.register_assert_rewrite("oneberth.identity.testing")`` in
a ``conftest.py`` before importing the suite, for pytest's detailed assertion
messages.
"""

from oneberth.identity.testing.contracts._store import IdentityStoreContract

__all__ = ["IdentityStoreContract"]
