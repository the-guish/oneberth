# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The identity store on PostgreSQL, over a pool of asyncpg connections.

Every operation is one statement, so one transaction, unless it says otherwise.
Where a statement decides by a row another may change at once (a claim, an
approve, a take), the row lock makes the second wait and then see what the
first did. Every connection runs in ``READ COMMITTED``, which that reasoning
assumes, with the store's schema as its ``search_path``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import TracebackType
from typing import Self

from oneberth.identity._errors import IdentityError, SchemaVersionError
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
from oneberth.identity._store import SCHEMA_VERSION, IdentityStore
from oneberth.identity.postgres._driver import (
    Pool,
    Record,
    affected,
    create_pool,
    quote_identifier,
)
from oneberth.identity.postgres._schema import CREATE_TABLES, SCHEMA, SETUP_LOCK

_USER = (
    "u.id AS user_id, u.provider, u.subject, u.created_at AS user_created_at,"
    " u.name AS user_name, u.email, u.hosted_domain, u.groups"
)

_UPSERT_USER = f"""
INSERT INTO users AS u (id, provider, subject, created_at, name, email,
                        hosted_domain, groups)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (provider, subject) DO UPDATE
   SET name = excluded.name, email = excluded.email,
       hosted_domain = excluded.hosted_domain, groups = excluded.groups
RETURNING {_USER}
"""

_SESSION_BY_HASH = f"""
SELECT {_USER}, c.id, c.secret_hash, c.created_at, c.expires_at
  FROM sessions AS c JOIN users AS u ON u.id = c.user_id
 WHERE c.secret_hash = $1 AND c.expires_at > $2
"""

_TOKEN = "id, user_id, name, secret_hash, created_at, expires_at"

_TOKEN_BY_HASH = f"""
SELECT {_USER}, c.id, c.name, c.secret_hash, c.created_at, c.expires_at
  FROM personal_tokens AS c JOIN users AS u ON u.id = c.user_id
 WHERE c.secret_hash = $1 AND c.expires_at > $2
"""

_DEVICE = (
    "id, user_id, name, platform, app_version, secret_hash, created_at,"
    " last_used_at, expires_at"
)

# Written only when a minute has passed since the last write; otherwise read
# as it is, so most requests write nothing.
_DEVICE_BY_HASH = f"""
WITH touched AS (
    UPDATE device_sessions SET last_used_at = $2
     WHERE secret_hash = $1 AND expires_at > $2 AND last_used_at <= $3
    RETURNING {_DEVICE}
),
device AS (
    SELECT {_DEVICE} FROM touched
    UNION ALL
    SELECT {_DEVICE} FROM device_sessions
     WHERE secret_hash = $1 AND expires_at > $2
       AND NOT EXISTS (SELECT 1 FROM touched)
)
SELECT {_USER}, d.id, d.name, d.platform, d.app_version, d.secret_hash,
       d.created_at, d.last_used_at, d.expires_at
  FROM device AS d JOIN users AS u ON u.id = d.user_id
"""

_ALL_DEVICES = f"""
SELECT {_USER}, d.id, d.name, d.platform, d.app_version, d.secret_hash,
       d.created_at, d.last_used_at, d.expires_at
  FROM device_sessions AS d JOIN users AS u ON u.id = d.user_id
 ORDER BY d.created_at, d.id
"""

_DELETE_DEVICES = f"""
DELETE FROM device_sessions
 WHERE $1::boolean OR user_id = $2 OR id = $3
RETURNING {_DEVICE}
"""

_PAIRING = (
    "id, user_id, code_hash, state, created_at, expires_at, claim_hash, number,"
    " wrong_tries, device_name, device_platform, device_app_version"
)

# The count reads the rows as they were before the delete, and counts the live
# ones.
_ADD_PAIRING = f"""
WITH expired AS (DELETE FROM pairings WHERE user_id = $2 AND expires_at <= $6)
INSERT INTO pairings ({_PAIRING})
SELECT $1, $2, $3, 'waiting', $4, $5, NULL, NULL, 0, NULL, NULL, NULL
 WHERE (SELECT count(*) FROM pairings WHERE user_id = $2 AND expires_at > $6) < $7
"""

_CLAIM_PAIRING = f"""
UPDATE pairings
   SET state = 'claimed', claim_hash = $2, number = $3, device_name = $4,
       device_platform = $5, device_app_version = $6, expires_at = $8
 WHERE code_hash = $1 AND state = 'waiting' AND expires_at > $7
RETURNING {_PAIRING}
"""

# The target is locked first. Of two approves at once the second waits, then
# reads the row as the first left it. Exactly one of approved, wrong and ended
# can touch the row, by their conditions on the locked target.
_APPROVE_PAIRING = f"""
WITH target AS (
    SELECT id, state, claim_hash, number, wrong_tries,
           device_name, device_platform, device_app_version
      FROM pairings
     WHERE id = $1 AND user_id = $2 AND expires_at > $6
       FOR UPDATE
),
approved AS (
    UPDATE pairings AS p SET state = 'approved', claim_hash = NULL
      FROM target AS t
     WHERE p.id = t.id AND t.state = 'claimed' AND t.number = $3
    RETURNING t.claim_hash, t.device_name, t.device_platform, t.device_app_version
),
device AS (
    INSERT INTO device_sessions ({_DEVICE})
    SELECT $4, $2, device_name, device_platform, device_app_version, claim_hash,
           $6, $6, $5
      FROM approved
    RETURNING {_DEVICE}
),
wrong AS (
    UPDATE pairings AS p SET wrong_tries = p.wrong_tries + 1
      FROM target AS t
     WHERE p.id = t.id AND t.state = 'claimed' AND t.number <> $3
       AND t.wrong_tries + 1 < {PAIRING_WRONG_TRIES}
    RETURNING p.id
),
ended AS (
    DELETE FROM pairings AS p
     USING target AS t
     WHERE p.id = t.id AND t.state = 'claimed' AND t.number <> $3
       AND t.wrong_tries + 1 >= {PAIRING_WRONG_TRIES}
    RETURNING p.id
)
SELECT (SELECT state FROM target) AS pairing_state,
       EXISTS (SELECT 1 FROM wrong) AS wrong,
       d.*
  FROM (SELECT 1) AS one LEFT JOIN device AS d ON true
"""

_SERVICE = "id, name, role, resource, secret_hash, created_at, expires_at"

_ADD_SERVICE_TOKEN = f"""
INSERT INTO service_tokens ({_SERVICE}) VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (name) DO NOTHING
"""

# The count and the insert are one statement. Two at once may both count under
# the limit, so it can be passed by the number of concurrent sign-ins: a
# ceiling on growth, which is all it is for.
_ADD_PENDING = """
INSERT INTO pending_sign_ins (state_hash, provider, nonce, verifier, return_to,
                              created_at, expires_at)
SELECT $1, $2, $3, $4, $5, $6, $7
 WHERE (SELECT count(*) FROM pending_sign_ins WHERE expires_at > $8) < $9
"""

_CREDENTIALS_OF = """
WITH person AS (SELECT id FROM users WHERE {where}),
s AS (DELETE FROM sessions WHERE user_id IN (SELECT id FROM person) RETURNING 1),
t AS (DELETE FROM personal_tokens WHERE user_id IN (SELECT id FROM person)
      RETURNING 1),
d AS (DELETE FROM device_sessions WHERE user_id IN (SELECT id FROM person)
      RETURNING 1),
p AS (DELETE FROM pairings WHERE user_id IN (SELECT id FROM person) RETURNING 1)
SELECT (SELECT count(*) FROM s) + (SELECT count(*) FROM t)
     + (SELECT count(*) FROM d) + (SELECT count(*) FROM p)
"""

_DELETE_EXPIRED = """
WITH s AS (DELETE FROM sessions WHERE expires_at <= $1 RETURNING 1),
t AS (DELETE FROM personal_tokens WHERE expires_at <= $1 RETURNING 1),
d AS (DELETE FROM device_sessions WHERE expires_at <= $1 RETURNING 1),
p AS (DELETE FROM pairings WHERE expires_at <= $1 RETURNING 1),
i AS (DELETE FROM pending_sign_ins WHERE expires_at <= $1 RETURNING 1)
SELECT (SELECT count(*) FROM s) + (SELECT count(*) FROM t)
     + (SELECT count(*) FROM d) + (SELECT count(*) FROM p)
     + (SELECT count(*) FROM i)
"""


class PostgresIdentityStore(IdentityStore):
    """Users, credentials, pairings and sign-ins in a PostgreSQL schema.

    ``dsn`` is a ``postgresql://`` URL. The tables live in ``schema``,
    ``oneberth`` unless a test names another. Open the store before use, with
    ``open`` or ``async with``, and close it after.
    """

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = SCHEMA,
        min_size: int = 1,
        max_size: int = 4,
    ) -> None:
        if not schema:
            raise ValueError("a schema name cannot be empty")
        self._dsn = dsn
        self._schema = schema
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Pool | None = None

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
    def schema(self) -> str:
        return self._schema

    async def open(self) -> None:
        """Open the pool. Safe to repeat."""
        if self._pool is not None:
            return
        self._pool = await create_pool(
            self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            server_settings={
                "search_path": quote_identifier(self._schema),
                "default_transaction_isolation": "read committed",
                "timezone": "UTC",
            },
        )

    async def aclose(self) -> None:
        """Close the pool. Safe to repeat."""
        if self._pool is None:
            return
        pool, self._pool = self._pool, None
        await pool.close()

    @property
    def _db(self) -> Pool:
        if self._pool is None:
            raise IdentityError("the PostgreSQL store is not open")
        return self._pool

    # The schema.

    async def setup(self) -> None:
        schema = quote_identifier(self._schema)
        async with self._db.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", SETUP_LOCK)
            version = await conn.fetchval(
                "SELECT to_regclass($1) IS NOT NULL",
                f"{schema}.schema_version",
            )
            if version:
                found = await conn.fetchval(
                    f"SELECT version FROM {schema}.schema_version"
                )
                if found is not None and found != SCHEMA_VERSION:
                    raise SchemaVersionError(
                        f"the schema {self._schema} is at version {found}, and "
                        f"this oneberth sets up version {SCHEMA_VERSION}"
                    )
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            await conn.execute(CREATE_TABLES)
            await conn.execute(
                "INSERT INTO schema_version (version) VALUES ($1)"
                " ON CONFLICT (only_row) DO NOTHING",
                SCHEMA_VERSION,
            )

    async def schema_version(self) -> int | None:
        table = f"{quote_identifier(self._schema)}.schema_version"
        async with self._db.acquire() as conn:
            if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table):
                return None
            version: int | None = await conn.fetchval(f"SELECT version FROM {table}")
            return version

    # Users.

    async def upsert_user(
        self, identity: Identity, *, user_id: uuid.UUID, now: datetime
    ) -> User:
        row = await self._db.fetchrow(
            _UPSERT_USER,
            user_id,
            identity.provider,
            identity.subject,
            now,
            identity.name,
            identity.email,
            identity.hosted_domain,
            sorted(identity.groups),
        )
        assert row is not None
        return _user(row)

    async def user(self, user_id: uuid.UUID) -> User | None:
        row = await self._db.fetchrow(
            f"SELECT {_USER} FROM users AS u WHERE id = $1", user_id
        )
        return None if row is None else _user(row)

    async def user_of(self, provider: str, subject: str) -> User | None:
        row = await self._db.fetchrow(
            f"SELECT {_USER} FROM users AS u WHERE provider = $1 AND subject = $2",
            provider,
            subject,
        )
        return None if row is None else _user(row)

    async def users_with_email(self, email: str) -> list[User]:
        rows = await self._db.fetch(
            f"SELECT {_USER} FROM users AS u WHERE lower(u.email) = lower($1)"
            " ORDER BY u.created_at, u.id",
            email,
        )
        return [_user(row) for row in rows]

    # Sessions.

    async def add_session(self, session: Session) -> None:
        await self._db.execute(
            "INSERT INTO sessions (id, user_id, secret_hash, created_at, expires_at)"
            " VALUES ($1, $2, $3, $4, $5)",
            session.id,
            session.user_id,
            session.secret_hash,
            session.created_at,
            session.expires_at,
        )

    async def session_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, Session] | None:
        row = await self._db.fetchrow(_SESSION_BY_HASH, secret_hash, now)
        if row is None:
            return None
        session = Session(
            id=row["id"],
            user_id=row["user_id"],
            secret_hash=row["secret_hash"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )
        return _user(row), session

    async def delete_session(self, secret_hash: str) -> bool:
        status = await self._db.execute(
            "DELETE FROM sessions WHERE secret_hash = $1", secret_hash
        )
        return affected(status) > 0

    async def delete_sessions(self) -> int:
        return affected(await self._db.execute("DELETE FROM sessions"))

    # Personal tokens.

    async def add_personal_token(self, token: PersonalToken) -> None:
        await self._db.execute(
            f"INSERT INTO personal_tokens ({_TOKEN}) VALUES ($1, $2, $3, $4, $5, $6)",
            token.id,
            token.user_id,
            token.name,
            token.secret_hash,
            token.created_at,
            token.expires_at,
        )

    async def personal_token_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, PersonalToken] | None:
        row = await self._db.fetchrow(_TOKEN_BY_HASH, secret_hash, now)
        return None if row is None else (_user(row), _token(row))

    async def personal_tokens_of(self, user_id: uuid.UUID) -> list[PersonalToken]:
        rows = await self._db.fetch(
            f"SELECT {_TOKEN} FROM personal_tokens WHERE user_id = $1"
            " ORDER BY created_at, id",
            user_id,
        )
        return [_token(row) for row in rows]

    async def delete_personal_token(
        self, user_id: uuid.UUID, token_id: uuid.UUID
    ) -> bool:
        status = await self._db.execute(
            "DELETE FROM personal_tokens WHERE id = $1 AND user_id = $2",
            token_id,
            user_id,
        )
        return affected(status) > 0

    # Device sessions.

    async def device_by_hash(
        self, secret_hash: str, now: datetime
    ) -> tuple[User, DeviceSession] | None:
        row = await self._db.fetchrow(
            _DEVICE_BY_HASH, secret_hash, now, now - LAST_USED_EVERY
        )
        return None if row is None else (_user(row), _device(row))

    async def devices_of(self, user_id: uuid.UUID) -> list[DeviceSession]:
        rows = await self._db.fetch(
            f"SELECT {_DEVICE} FROM device_sessions WHERE user_id = $1"
            " ORDER BY created_at, id",
            user_id,
        )
        return [_device(row) for row in rows]

    async def all_devices(self) -> list[tuple[User, DeviceSession]]:
        rows = await self._db.fetch(_ALL_DEVICES)
        return [(_user(row), _device(row)) for row in rows]

    async def delete_device(self, user_id: uuid.UUID, device_id: uuid.UUID) -> bool:
        status = await self._db.execute(
            "DELETE FROM device_sessions WHERE id = $1 AND user_id = $2",
            device_id,
            user_id,
        )
        return affected(status) > 0

    async def delete_devices(
        self,
        *,
        user_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        every: bool = False,
    ) -> list[DeviceSession]:
        if [user_id is not None, device_id is not None, every].count(True) != 1:
            raise ValueError("give one of user_id, device_id and every")
        rows = await self._db.fetch(_DELETE_DEVICES, every, user_id, device_id)
        return sorted(
            (_device(row) for row in rows), key=lambda d: (d.created_at, d.id)
        )

    # Pairings.

    async def add_pairing(
        self, pairing: Pairing, now: datetime, *, at_most: int
    ) -> bool:
        status = await self._db.execute(
            _ADD_PAIRING,
            pairing.id,
            pairing.user_id,
            pairing.code_hash,
            pairing.created_at,
            pairing.expires_at,
            now,
            at_most,
        )
        return affected(status) == 1

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
        row = await self._db.fetchrow(
            _CLAIM_PAIRING,
            code_hash,
            claim_hash,
            number,
            device.name,
            device.platform,
            device.app_version,
            now,
            expires_at,
        )
        return None if row is None else _pairing(row)

    async def pairing_of(
        self, user_id: uuid.UUID, pairing_id: uuid.UUID
    ) -> Pairing | None:
        row = await self._db.fetchrow(
            f"SELECT {_PAIRING} FROM pairings WHERE id = $1 AND user_id = $2",
            pairing_id,
            user_id,
        )
        return None if row is None else _pairing(row)

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
        row = await self._db.fetchrow(
            _APPROVE_PAIRING,
            pairing_id,
            user_id,
            number,
            device_id,
            device_expires_at,
            now,
        )
        assert row is not None
        if row["pairing_state"] is None:
            return Approval.GONE, None
        if row["pairing_state"] != PairingState.CLAIMED:
            return Approval.NOT_CLAIMED, None
        if row["id"] is not None:
            return Approval.APPROVED, _device(row)
        return (Approval.WRONG_NUMBER if row["wrong"] else Approval.GONE), None

    async def delete_pairing(self, user_id: uuid.UUID, pairing_id: uuid.UUID) -> bool:
        status = await self._db.execute(
            "DELETE FROM pairings WHERE id = $1 AND user_id = $2", pairing_id, user_id
        )
        return affected(status) > 0

    async def claim_state(self, claim_hash: str, now: datetime) -> PairingState | None:
        state = await self._db.fetchval(
            "SELECT state FROM pairings WHERE claim_hash = $1 AND expires_at > $2",
            claim_hash,
            now,
        )
        return None if state is None else PairingState(state)

    # Service tokens.

    async def add_service_token(self, token: ServiceToken) -> bool:
        status = await self._db.execute(
            _ADD_SERVICE_TOKEN,
            token.id,
            token.name,
            token.grant.role,
            token.grant.resource,
            token.secret_hash,
            token.created_at,
            token.expires_at,
        )
        return affected(status) == 1

    async def service_token_by_hash(
        self, secret_hash: str, now: datetime
    ) -> ServiceToken | None:
        row = await self._db.fetchrow(
            f"SELECT {_SERVICE} FROM service_tokens WHERE secret_hash = $1"
            " AND (expires_at IS NULL OR expires_at > $2)",
            secret_hash,
            now,
        )
        return None if row is None else _service(row)

    async def service_tokens(self) -> list[ServiceToken]:
        # By code point, as Python sorts, whatever the database's collation.
        rows = await self._db.fetch(
            f'SELECT {_SERVICE} FROM service_tokens ORDER BY name COLLATE "C"'
        )
        return [_service(row) for row in rows]

    async def delete_service_token(self, token_id: uuid.UUID) -> bool:
        status = await self._db.execute(
            "DELETE FROM service_tokens WHERE id = $1", token_id
        )
        return affected(status) > 0

    # Sign-ins in progress.

    async def add_pending_sign_in(
        self, pending: PendingSignIn, now: datetime, *, limit: int
    ) -> bool:
        status = await self._db.execute(
            _ADD_PENDING,
            pending.state_hash,
            pending.provider,
            pending.nonce,
            pending.verifier,
            pending.return_to,
            pending.created_at,
            pending.expires_at,
            now,
            limit,
        )
        return affected(status) == 1

    async def take_pending_sign_in(
        self, state_hash: str, now: datetime
    ) -> PendingSignIn | None:
        # Deleting and reading are one statement: of two takes at once, the
        # second waits for the first's row lock and then finds the row gone.
        row = await self._db.fetchrow(
            "DELETE FROM pending_sign_ins WHERE state_hash = $1"
            " RETURNING state_hash, provider, nonce, verifier, return_to,"
            " created_at, expires_at",
            state_hash,
        )
        # Judged after the delete, so an expired one is gone either way.
        if row is None or row["expires_at"] <= now:
            return None
        return PendingSignIn(
            state_hash=row["state_hash"],
            provider=row["provider"],
            nonce=row["nonce"],
            verifier=row["verifier"],
            return_to=row["return_to"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )

    # Every credential of a person, and the sweep.

    async def delete_credentials_of(self, user_id: uuid.UUID) -> int:
        count: int = await self._db.fetchval(
            _CREDENTIALS_OF.format(where="id = $1"), user_id
        )
        return count

    async def delete_credentials_of_identity(self, provider: str, subject: str) -> int:
        count: int = await self._db.fetchval(
            _CREDENTIALS_OF.format(where="provider = $1 AND subject = $2"),
            provider,
            subject,
        )
        return count

    async def delete_expired(self, now: datetime) -> int:
        count: int = await self._db.fetchval(_DELETE_EXPIRED, now)
        return count


def _user(row: Record) -> User:
    return User(
        id=row["user_id"],
        provider=row["provider"],
        subject=row["subject"],
        created_at=row["user_created_at"],
        name=row["user_name"],
        email=row["email"],
        hosted_domain=row["hosted_domain"],
        groups=frozenset(row["groups"]),
    )


def _token(row: Record) -> PersonalToken:
    return PersonalToken(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        secret_hash=row["secret_hash"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def _device(row: Record) -> DeviceSession:
    return DeviceSession(
        id=row["id"],
        user_id=row["user_id"],
        device=DeviceDescription(
            name=row["name"], platform=row["platform"], app_version=row["app_version"]
        ),
        secret_hash=row["secret_hash"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        expires_at=row["expires_at"],
    )


def _pairing(row: Record) -> Pairing:
    device = None
    if row["device_name"] is not None:
        device = DeviceDescription(
            name=row["device_name"],
            platform=row["device_platform"],
            app_version=row["device_app_version"],
        )
    return Pairing(
        id=row["id"],
        user_id=row["user_id"],
        code_hash=row["code_hash"],
        state=PairingState(row["state"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        claim_hash=row["claim_hash"],
        number=row["number"],
        wrong_tries=row["wrong_tries"],
        device=device,
    )


def _service(row: Record) -> ServiceToken:
    return ServiceToken(
        id=row["id"],
        name=row["name"],
        grant=Grant(row["role"], row["resource"]),
        secret_hash=row["secret_hash"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )
