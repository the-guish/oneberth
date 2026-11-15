# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The one module that imports asyncpg: typed views of the part the store uses.

asyncpg ships no type information, so its connections and pools are described
here as protocols, and the store talks to those.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, cast

import asyncpg  # type: ignore[import-untyped]


class Record(Protocol):
    """A row, read by column name or position."""

    def __getitem__(self, key: str | int, /) -> Any: ...


class Connection(Protocol):
    """An ``asyncpg.Connection``, as far as the store uses one."""

    async def execute(self, query: str, *args: object) -> str: ...

    async def fetch(self, query: str, *args: object) -> list[Record]: ...

    async def fetchrow(self, query: str, *args: object) -> Record | None: ...

    async def fetchval(self, query: str, *args: object) -> Any: ...

    def transaction(self) -> AbstractAsyncContextManager[object]: ...


class Pool(Protocol):
    """An ``asyncpg.Pool``, as far as the store uses one."""

    def acquire(self) -> AbstractAsyncContextManager[Connection]: ...

    async def execute(self, query: str, *args: object) -> str: ...

    async def fetch(self, query: str, *args: object) -> list[Record]: ...

    async def fetchrow(self, query: str, *args: object) -> Record | None: ...

    async def fetchval(self, query: str, *args: object) -> Any: ...

    async def close(self) -> None: ...


def quote_identifier(name: str) -> str:
    """``name`` as a quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


async def create_pool(
    dsn: str, *, min_size: int, max_size: int, server_settings: dict[str, str]
) -> Pool:
    """An open pool, its first ``min_size`` connections made."""
    pool = await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        server_settings=server_settings,
    )
    return cast(Pool, pool)


def affected(status: str) -> int:
    """How many rows a command touched, from its status, such as ``DELETE 3``."""
    count = status.rpartition(" ")[2]
    return int(count) if count.isdigit() else 0
