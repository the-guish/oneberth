# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The identity store in one SQLite file, on the standard library's ``sqlite3``.

One connection and one thread serve the store. Each operation is a plain
function that runs as one transaction on that thread, and the event loop awaits
it without blocking. The thread runs one operation at a time, so the operations
are atomic towards each other, as under the memory store. A writing operation
begins with ``BEGIN IMMEDIATE``: it takes the file's write lock first, and waits
for another connection's lock up to the busy timeout.

The backend's process alone opens the file.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import sqlite3
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Self, TypeVar

from oneberth.identity._errors import IdentityError
from oneberth.identity._records import (
    LAST_USED_EVERY,
    PAIRING_WRONG_TRIES,
    Approval,
    DeviceDescription,
    DeviceSession,
    Identity,
    Pairing,
    PairingState,
    PendingSignIn,
    PersonalToken,
    ServiceToken,
    Session,
    User,
)
from oneberth.identity._roles import Grant
from oneberth.identity._store import IdentityStore
from oneberth.identity.sqlite import _schema

_T = TypeVar("_T")
Row = sqlite3.Row

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)

_USER = (
    "u.id AS user_id, u.provider, u.subject, u.created_at AS user_created_at,"
    " u.name AS user_name, u.email, u.hosted_domain, u.groups"
)
_TOKEN = "id, user_id, name, secret_hash, created_at, expires_at"
_DEVICE = (
    "id, user_id, name, platform, app_version, secret_hash, created_at,"
    " last_used_at, expires_at"
)
_DEVICE_OF_D = ", ".join(f"d.{c.strip()}" for c in _DEVICE.split(",") if c.strip())
_PAIRING = (
    "id, user_id, code_hash, state, created_at, expires_at, claim_hash, number,"
    " wrong_tries, device_name, device_platform, device_app_version"
)
_SERVICE = "id, name, role, resource, secret_hash, created_at, expires_at"
_PENDING = "state_hash, provider, nonce, verifier, return_to, created_at, expires_at"


class SqliteIdentityStore(IdentityStore):
    """Users, credentials, pairings and sign-ins in the SQLite file at ``path``.

    Opening creates an empty file if there is none, and refuses a file of
    another application or version with ``SchemaVersionError``. ``setup``
    creates the tables. Open the store before use, with ``open`` or
    ``async with``, and close it after.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = path
        self._executor: ThreadPoolExecutor | None = None
        self._conn: sqlite3.Connection | None = None

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    @property
    def path(self) -> str:
        return os.fspath(self._path)

    async def open(self) -> None:
        """Open the file, on the store's own thread. Safe to repeat."""
        if self._executor is not None:
            return
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="oneberth-db")
        try:
            loop = asyncio.get_running_loop()
            self._conn = await loop.run_in_executor(
                executor, _schema.connect, self._path
            )
        except BaseException:
            executor.shutdown(wait=False)
            raise
        self._executor = executor

    async def aclose(self) -> None:
        """Close the file, once the operations already begun have ended."""
        executor, conn = self._executor, self._conn
        if executor is None or conn is None:
            return
        self._executor = self._conn = None
        await asyncio.get_running_loop().run_in_executor(executor, conn.close)
        executor.shutdown(wait=False)

    async def _read(self, operation: Callable[..., _T], *args: Any) -> _T:
        return await self._run("BEGIN", operation, *args)

    async def _write(self, operation: Callable[..., _T], *args: Any) -> _T:
        return await self._run("BEGIN IMMEDIATE", operation, *args)

    async def _run(self, begin: str, operation: Callable[..., _T], *args: Any) -> _T:
        executor, conn = self._executor, self._conn
        if executor is None or conn is None:
            raise IdentityError("the SQLite store is not open")
        call = functools.partial(_transaction, conn, begin, operation, *args)
        return await asyncio.get_running_loop().run_in_executor(executor, call)

    # The schema.

    async def setup(self) -> None:
        await self._write(_schema.setup, self.path)

    async def schema_version(self) -> int | None:
        return await self._read(_schema.version, self.path)

    # Users.

    async def upsert_user(
        self, identity: Identity, *, user_id: uuid.UUID, now: datetime
    ) -> User:
        return await self._write(_upsert_user, identity, user_id, now)

    async def user(self, user_id: uuid.UUID) -> User | None:
        return await self._read(_one_user, "u.id = ?", (str(user_id),))

    async def user_of(self, provider: str, subject: str) -> User | None:
        return await self._read(
            _one_user, "u.provider = ? AND u.subject = ?", (provider, subject)
        )

    async def users_with_email(self, email: str) -> list[User]:
        return await self._read(_users_with_email, email)

    # Sessions.

    async def add_session(self, session: Session) -> None:
        await self._write(
            _execute,
            "INSERT INTO sessions (id, user_id, secret_hash, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                str(session.id),
                str(session.user_id),
                session.secret_hash,
                _time(session.created_at),
                _time(session.expires_at),
            ),
        )

    async def session_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, Session] | None:
        return await self._read(_session_by_hash, secret_hash, now)

    async def delete_session(self, secret_hash: str) -> bool:
        return (
            await self._write(
                _execute, "DELETE FROM sessions WHERE secret_hash = ?", (secret_hash,)
            )
            > 0
        )

    async def delete_sessions(self) -> int:
        return await self._write(_execute, "DELETE FROM sessions", ())

    # Personal tokens.

    async def add_personal_token(self, token: PersonalToken) -> None:
        await self._write(
            _execute,
            f"INSERT INTO personal_tokens ({_TOKEN}) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(token.id),
                str(token.user_id),
                token.name,
                token.secret_hash,
                _time(token.created_at),
                _time(token.expires_at),
            ),
        )

    async def personal_token_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, PersonalToken] | None:
        return await self._read(_token_by_hash, secret_hash, now)

    async def personal_tokens_of(self, user_id: uuid.UUID) -> list[PersonalToken]:
        rows = await self._read(
            _fetch,
            f"SELECT {_TOKEN} FROM personal_tokens WHERE user_id = ?"
            " ORDER BY created_at, id",
            (str(user_id),),
        )
        return [_token(row) for row in rows]

    async def delete_personal_token(
        self, user_id: uuid.UUID, token_id: uuid.UUID
    ) -> bool:
        deleted = await self._write(
            _execute,
            "DELETE FROM personal_tokens WHERE id = ? AND user_id = ?",
            (str(token_id), str(user_id)),
        )
        return deleted > 0

    # Device sessions.

    async def device_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, DeviceSession] | None:
        return await self._write(_device_by_hash, secret_hash, now)

    async def devices_of(self, user_id: uuid.UUID) -> list[DeviceSession]:
        rows = await self._read(
            _fetch,
            f"SELECT {_DEVICE} FROM device_sessions WHERE user_id = ?"
            " ORDER BY created_at, id",
            (str(user_id),),
        )
        return [_device(row) for row in rows]

    async def all_devices(self) -> list[tuple[User, DeviceSession]]:
        rows = await self._read(
            _fetch,
            f"SELECT {_USER}, {_DEVICE_OF_D} FROM device_sessions AS d"
            " JOIN users AS u ON u.id = d.user_id ORDER BY d.created_at, d.id",
            (),
        )
        return [(_user(row), _device(row)) for row in rows]

    async def delete_device(self, user_id: uuid.UUID, device_id: uuid.UUID) -> bool:
        deleted = await self._write(
            _execute,
            "DELETE FROM device_sessions WHERE id = ? AND user_id = ?",
            (str(device_id), str(user_id)),
        )
        return deleted > 0

    async def delete_devices(
        self,
        *,
        user_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        every: bool = False,
    ) -> list[DeviceSession]:
        if [user_id is not None, device_id is not None, every].count(True) != 1:
            raise ValueError("give one of user_id, device_id and every")
        return await self._write(
            _delete_devices,
            every,
            None if user_id is None else str(user_id),
            None if device_id is None else str(device_id),
        )

    # Pairings.

    async def add_pairing(
        self, pairing: Pairing, now: datetime, *, at_most: int
    ) -> bool:
        return await self._write(_add_pairing, pairing, now, at_most)

    async def claim_pairing(
        self,
        code_hash: str,
        *,
        claim_hash: str,
        number: str,
        device: DeviceDescription,
        now: datetime,
        expires_at: datetime,
    ) -> Pairing | None:
        return await self._write(
            _claim_pairing, code_hash, claim_hash, number, device, now, expires_at
        )

    async def pairing_of(
        self, user_id: uuid.UUID, pairing_id: uuid.UUID
    ) -> Pairing | None:
        rows = await self._read(
            _fetch,
            f"SELECT {_PAIRING} FROM pairings WHERE id = ? AND user_id = ?",
            (str(pairing_id), str(user_id)),
        )
        return _pairing(rows[0]) if rows else None

    async def approve_pairing(
        self,
        user_id: uuid.UUID,
        pairing_id: uuid.UUID,
        number: str,
        *,
        device_id: uuid.UUID,
        device_expires_at: datetime,
        now: datetime,
    ) -> tuple[Approval, DeviceSession | None]:
        return await self._write(
            _approve_pairing,
            user_id,
            pairing_id,
            number,
            device_id,
            device_expires_at,
            now,
        )

    async def delete_pairing(self, user_id: uuid.UUID, pairing_id: uuid.UUID) -> bool:
        deleted = await self._write(
            _execute,
            "DELETE FROM pairings WHERE id = ? AND user_id = ?",
            (str(pairing_id), str(user_id)),
        )
        return deleted > 0

    async def claim_state(self, claim_hash: str, now: datetime) -> PairingState | None:
        rows = await self._read(
            _fetch,
            "SELECT state FROM pairings WHERE claim_hash = ? AND expires_at > ?",
            (claim_hash, _time(now)),
        )
        return PairingState(rows[0]["state"]) if rows else None

    # Service tokens.

    async def add_service_token(self, token: ServiceToken) -> bool:
        added = await self._write(
            _execute,
            f"INSERT INTO service_tokens ({_SERVICE}) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (name) DO NOTHING",
            (
                str(token.id),
                token.name,
                token.grant.role,
                token.grant.resource,
                token.secret_hash,
                _time(token.created_at),
                None if token.expires_at is None else _time(token.expires_at),
            ),
        )
        return added == 1

    async def service_token_by_hash(
        self, secret_hash: str, now: datetime
    ) -> ServiceToken | None:
        rows = await self._read(
            _fetch,
            f"SELECT {_SERVICE} FROM service_tokens WHERE secret_hash = ?"
            " AND (expires_at IS NULL OR expires_at > ?)",
            (secret_hash, _time(now)),
        )
        return _service(rows[0]) if rows else None

    async def service_tokens(self) -> list[ServiceToken]:
        # BINARY collation: by code point, as Python sorts.
        rows = await self._read(
            _fetch, f"SELECT {_SERVICE} FROM service_tokens ORDER BY name", ()
        )
        return [_service(row) for row in rows]

    async def delete_service_token(self, token_id: uuid.UUID) -> bool:
        deleted = await self._write(
            _execute, "DELETE FROM service_tokens WHERE id = ?", (str(token_id),)
        )
        return deleted > 0

    # Sign-ins in progress.

    async def add_pending_sign_in(
        self, pending: PendingSignIn, now: datetime, *, limit: int
    ) -> bool:
        added = await self._write(
            _execute,
            f"INSERT INTO pending_sign_ins ({_PENDING})"
            " SELECT ?, ?, ?, ?, ?, ?, ?"
            " WHERE (SELECT count(*) FROM pending_sign_ins WHERE expires_at > ?) < ?",
            (
                pending.state_hash,
                pending.provider,
                pending.nonce,
                pending.verifier,
                pending.return_to,
                _time(pending.created_at),
                _time(pending.expires_at),
                _time(now),
                limit,
            ),
        )
        return added == 1

    async def take_pending_sign_in(
        self, state_hash: str, now: datetime
    ) -> PendingSignIn | None:
        return await self._write(_take_pending, state_hash, now)

    # Every credential of a person, and the sweep.

    async def delete_credentials_of(self, user_id: uuid.UUID) -> int:
        return await self._write(_delete_credentials, str(user_id))

    async def delete_credentials_of_identity(self, provider: str, subject: str) -> int:
        return await self._write(_delete_credentials_of_identity, provider, subject)

    async def delete_expired(self, now: datetime) -> int:
        return await self._write(_delete_expired, _time(now))


# The operations, each run inside one transaction on the store's thread.


def _transaction(
    conn: sqlite3.Connection, begin: str, operation: Callable[..., _T], *args: Any
) -> _T:
    """Run ``operation`` as one transaction: committed if it returns, else undone."""
    conn.execute(begin)
    try:
        result = operation(conn, *args)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return result


def _execute(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> int:
    """Run one statement; how many rows it changed."""
    return conn.execute(sql, params).rowcount


def _fetch(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> list[Row]:
    return conn.execute(sql, params).fetchall()


def _upsert_user(
    conn: sqlite3.Connection, identity: Identity, user_id: uuid.UUID, now: datetime
) -> User:
    conn.execute(
        "INSERT INTO users (id, provider, subject, created_at, name, email,"
        " hosted_domain, groups) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (provider, subject) DO UPDATE SET name = excluded.name,"
        " email = excluded.email, hosted_domain = excluded.hosted_domain,"
        " groups = excluded.groups",
        (
            str(user_id),
            identity.provider,
            identity.subject,
            _time(now),
            identity.name,
            identity.email,
            identity.hosted_domain,
            json.dumps(sorted(identity.groups)),
        ),
    )
    user = _one_user(
        conn,
        "u.provider = ? AND u.subject = ?",
        (identity.provider, identity.subject),
    )
    assert user is not None
    return user


def _one_user(
    conn: sqlite3.Connection, where: str, params: tuple[Any, ...]
) -> User | None:
    row = conn.execute(
        f"SELECT {_USER} FROM users AS u WHERE {where}", params
    ).fetchone()
    return None if row is None else _user(row)


def _users_with_email(conn: sqlite3.Connection, email: str) -> list[User]:
    rows = conn.execute(
        f"SELECT {_USER} FROM users AS u WHERE lower(u.email) = lower(?)"
        " ORDER BY u.created_at, u.id",
        (email,),
    ).fetchall()
    return [_user(row) for row in rows]


def _session_by_hash(
    conn: sqlite3.Connection, secret_hash: str, now: datetime
) -> tuple[User, Session] | None:
    row = conn.execute(
        f"SELECT {_USER}, c.id, c.secret_hash, c.created_at, c.expires_at"
        " FROM sessions AS c JOIN users AS u ON u.id = c.user_id"
        " WHERE c.secret_hash = ? AND c.expires_at > ?",
        (secret_hash, _time(now)),
    ).fetchone()
    if row is None:
        return None
    session = Session(
        id=uuid.UUID(row["id"]),
        user_id=uuid.UUID(row["user_id"]),
        secret_hash=row["secret_hash"],
        created_at=_moment(row["created_at"]),
        expires_at=_moment(row["expires_at"]),
    )
    return _user(row), session


def _token_by_hash(
    conn: sqlite3.Connection, secret_hash: str, now: datetime
) -> tuple[User, PersonalToken] | None:
    row = conn.execute(
        f"SELECT {_USER}, c.id, c.name, c.secret_hash, c.created_at, c.expires_at"
        " FROM personal_tokens AS c JOIN users AS u ON u.id = c.user_id"
        " WHERE c.secret_hash = ? AND c.expires_at > ?",
        (secret_hash, _time(now)),
    ).fetchone()
    return None if row is None else (_user(row), _token(row))


def _device_by_hash(
    conn: sqlite3.Connection, secret_hash: str, now: datetime
) -> tuple[User, DeviceSession] | None:
    conn.execute(
        "UPDATE device_sessions SET last_used_at = ?"
        " WHERE secret_hash = ? AND expires_at > ? AND last_used_at <= ?",
        (_time(now), secret_hash, _time(now), _time(now - LAST_USED_EVERY)),
    )
    row = conn.execute(
        f"SELECT {_USER}, {_DEVICE_OF_D} FROM device_sessions AS d"
        " JOIN users AS u ON u.id = d.user_id"
        " WHERE d.secret_hash = ? AND d.expires_at > ?",
        (secret_hash, _time(now)),
    ).fetchone()
    return None if row is None else (_user(row), _device(row))


def _delete_devices(
    conn: sqlite3.Connection, every: bool, user_id: str | None, device_id: str | None
) -> list[DeviceSession]:
    where = "? OR user_id = ? OR id = ?"
    params = (every, user_id, device_id)
    rows = conn.execute(
        f"SELECT {_DEVICE} FROM device_sessions WHERE {where} ORDER BY created_at, id",
        params,
    ).fetchall()
    conn.execute(f"DELETE FROM device_sessions WHERE {where}", params)
    return [_device(row) for row in rows]


def _add_pairing(
    conn: sqlite3.Connection, pairing: Pairing, now: datetime, at_most: int
) -> bool:
    user_id = str(pairing.user_id)
    conn.execute(
        "DELETE FROM pairings WHERE user_id = ? AND expires_at <= ?",
        (user_id, _time(now)),
    )
    live = conn.execute(
        "SELECT count(*) FROM pairings WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    if live >= at_most:
        return False
    conn.execute(
        f"INSERT INTO pairings ({_PAIRING})"
        " VALUES (?, ?, ?, 'waiting', ?, ?, NULL, NULL, 0, NULL, NULL, NULL)",
        (
            str(pairing.id),
            user_id,
            pairing.code_hash,
            _time(pairing.created_at),
            _time(pairing.expires_at),
        ),
    )
    return True


def _claim_pairing(
    conn: sqlite3.Connection,
    code_hash: str,
    claim_hash: str,
    number: str,
    device: DeviceDescription,
    now: datetime,
    expires_at: datetime,
) -> Pairing | None:
    row = conn.execute(
        "UPDATE pairings SET state = 'claimed', claim_hash = ?, number = ?,"
        " device_name = ?, device_platform = ?, device_app_version = ?,"
        " expires_at = ?"
        " WHERE code_hash = ? AND state = 'waiting' AND expires_at > ?"
        f" RETURNING {_PAIRING}",
        (
            claim_hash,
            number,
            device.name,
            device.platform,
            device.app_version,
            _time(expires_at),
            code_hash,
            _time(now),
        ),
    ).fetchone()
    return None if row is None else _pairing(row)


def _approve_pairing(
    conn: sqlite3.Connection,
    user_id: uuid.UUID,
    pairing_id: uuid.UUID,
    number: str,
    device_id: uuid.UUID,
    device_expires_at: datetime,
    now: datetime,
) -> tuple[Approval, DeviceSession | None]:
    row = conn.execute(
        f"SELECT {_PAIRING} FROM pairings"
        " WHERE id = ? AND user_id = ? AND expires_at > ?",
        (str(pairing_id), str(user_id), _time(now)),
    ).fetchone()
    if row is None:
        return Approval.GONE, None
    found = _pairing(row)
    if found.state is not PairingState.CLAIMED:
        return Approval.NOT_CLAIMED, None
    assert found.claim_hash is not None and found.device is not None
    if found.number != number:
        if found.wrong_tries + 1 >= PAIRING_WRONG_TRIES:
            conn.execute("DELETE FROM pairings WHERE id = ?", (str(found.id),))
            return Approval.GONE, None
        conn.execute(
            "UPDATE pairings SET wrong_tries = wrong_tries + 1 WHERE id = ?",
            (str(found.id),),
        )
        return Approval.WRONG_NUMBER, None
    device = DeviceSession(
        id=device_id,
        user_id=user_id,
        device=found.device,
        secret_hash=found.claim_hash,
        created_at=now,
        last_used_at=now,
        expires_at=device_expires_at,
    )
    conn.execute(
        "UPDATE pairings SET state = 'approved', claim_hash = NULL WHERE id = ?",
        (str(found.id),),
    )
    conn.execute(
        f"INSERT INTO device_sessions ({_DEVICE}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(device.id),
            str(device.user_id),
            device.device.name,
            device.device.platform,
            device.device.app_version,
            device.secret_hash,
            _time(now),
            _time(now),
            _time(device_expires_at),
        ),
    )
    return Approval.APPROVED, device


def _take_pending(
    conn: sqlite3.Connection, state_hash: str, now: datetime
) -> PendingSignIn | None:
    row = conn.execute(
        f"DELETE FROM pending_sign_ins WHERE state_hash = ? RETURNING {_PENDING}",
        (state_hash,),
    ).fetchone()
    # Judged after the delete, so an expired one is gone either way.
    if row is None or row["expires_at"] <= _time(now):
        return None
    return PendingSignIn(
        state_hash=row["state_hash"],
        provider=row["provider"],
        nonce=row["nonce"],
        verifier=row["verifier"],
        return_to=row["return_to"],
        created_at=_moment(row["created_at"]),
        expires_at=_moment(row["expires_at"]),
    )


_CREDENTIAL_TABLES = ("sessions", "personal_tokens", "device_sessions", "pairings")


def _delete_credentials(conn: sqlite3.Connection, user_id: str) -> int:
    return sum(
        conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,)).rowcount
        for table in _CREDENTIAL_TABLES
    )


def _delete_credentials_of_identity(
    conn: sqlite3.Connection, provider: str, subject: str
) -> int:
    row = conn.execute(
        "SELECT id FROM users WHERE provider = ? AND subject = ?", (provider, subject)
    ).fetchone()
    return 0 if row is None else _delete_credentials(conn, row["id"])


def _delete_expired(conn: sqlite3.Connection, now: int) -> int:
    return sum(
        conn.execute(f"DELETE FROM {table} WHERE expires_at <= ?", (now,)).rowcount
        for table in (*_CREDENTIAL_TABLES, "pending_sign_ins")
    )


# Rows to records.


def _time(moment: datetime) -> int:
    """A time as stored: whole microseconds since the epoch."""
    return (moment - _EPOCH) // _MICROSECOND


def _moment(stored: int) -> datetime:
    return _EPOCH + stored * _MICROSECOND


def _user(row: Row) -> User:
    return User(
        id=uuid.UUID(row["user_id"]),
        provider=row["provider"],
        subject=row["subject"],
        created_at=_moment(row["user_created_at"]),
        name=row["user_name"],
        email=row["email"],
        hosted_domain=row["hosted_domain"],
        groups=frozenset(json.loads(row["groups"])),
    )


def _token(row: Row) -> PersonalToken:
    return PersonalToken(
        id=uuid.UUID(row["id"]),
        user_id=uuid.UUID(row["user_id"]),
        name=row["name"],
        secret_hash=row["secret_hash"],
        created_at=_moment(row["created_at"]),
        expires_at=_moment(row["expires_at"]),
    )


def _device(row: Row) -> DeviceSession:
    return DeviceSession(
        id=uuid.UUID(row["id"]),
        user_id=uuid.UUID(row["user_id"]),
        device=DeviceDescription(
            name=row["name"], platform=row["platform"], app_version=row["app_version"]
        ),
        secret_hash=row["secret_hash"],
        created_at=_moment(row["created_at"]),
        last_used_at=_moment(row["last_used_at"]),
        expires_at=_moment(row["expires_at"]),
    )


def _pairing(row: Row) -> Pairing:
    device = None
    if row["device_name"] is not None:
        device = DeviceDescription(
            name=row["device_name"],
            platform=row["device_platform"],
            app_version=row["device_app_version"],
        )
    return Pairing(
        id=uuid.UUID(row["id"]),
        user_id=uuid.UUID(row["user_id"]),
        code_hash=row["code_hash"],
        state=PairingState(row["state"]),
        created_at=_moment(row["created_at"]),
        expires_at=_moment(row["expires_at"]),
        claim_hash=row["claim_hash"],
        number=row["number"],
        wrong_tries=row["wrong_tries"],
        device=device,
    )


def _service(row: Row) -> ServiceToken:
    expires_at = row["expires_at"]
    return ServiceToken(
        id=uuid.UUID(row["id"]),
        name=row["name"],
        grant=Grant(row["role"], row["resource"]),
        secret_hash=row["secret_hash"],
        created_at=_moment(row["created_at"]),
        expires_at=None if expires_at is None else _moment(expires_at),
    )
