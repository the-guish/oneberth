# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The file the SQLite store keeps, how it is opened, and how its version is read.

The file holds oneberth's ``application_id`` and the schema version in
``user_version``. Opening refuses a file of another application, or of another
version of oneberth, before it changes anything in it. The setup creates the
tables, the application id and the version in one transaction.

The choices that differ from the PostgreSQL tables:

- Ids are UUIDs in their text form. SQLite has no UUID type.
- Times are integers, microseconds since the Unix epoch in UTC. They compare
  as numbers, and they come back as written.
- Groups are a JSON array of strings, sorted.
- ``lower`` is Python's, so an email is compared as the memory store compares it.
"""

from __future__ import annotations

import os
import sqlite3

from oneberth.identity._errors import SchemaVersionError
from oneberth.identity._records import PairingState
from oneberth.identity._store import SCHEMA_VERSION

FILE_NAME = "oneberth.db"
"""The store's file in a data directory."""

APPLICATION_ID = 0x6F6E6562
"""``application_id`` of a oneberth file: "oneb"."""

BUSY_TIMEOUT_SECONDS = 5.0
"""How long a statement waits for a lock another connection holds."""

_STATES = ", ".join(f"'{state.value}'" for state in PairingState)

CREATE_TABLES = f"""
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    name TEXT,
    email TEXT,
    hosted_domain TEXT,
    groups TEXT NOT NULL DEFAULT '[]',
    UNIQUE (provider, subject)
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    secret_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX sessions_user_id_idx ON sessions (user_id);

CREATE TABLE personal_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    secret_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX personal_tokens_user_id_idx ON personal_tokens (user_id);

CREATE TABLE device_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    app_version TEXT,
    secret_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX device_sessions_user_id_idx ON device_sessions (user_id);

CREATE TABLE pairings (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ({_STATES})),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    claim_hash TEXT UNIQUE,
    number TEXT,
    wrong_tries INTEGER NOT NULL DEFAULT 0,
    device_name TEXT,
    device_platform TEXT,
    device_app_version TEXT
);
CREATE INDEX pairings_user_id_idx ON pairings (user_id);

CREATE TABLE service_tokens (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    resource TEXT,
    secret_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER
);

CREATE TABLE pending_sign_ins (
    state_hash TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    nonce TEXT NOT NULL,
    verifier TEXT NOT NULL,
    return_to TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

PRAGMA application_id = {APPLICATION_ID};
PRAGMA user_version = {SCHEMA_VERSION};
"""


def connect(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open the file at ``path``, creating an empty one if there is none.

    The connection is in autocommit mode: the caller begins and ends each
    transaction. Raises ``SchemaVersionError`` for a file of another version
    or another application, and ``sqlite3.Error`` for one SQLite cannot open.
    """
    conn = sqlite3.connect(
        path,
        timeout=BUSY_TIMEOUT_SECONDS,
        isolation_level=None,
        check_same_thread=False,
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.create_function("lower", 1, _lower, deterministic=True)
        version(conn, os.fspath(path))
        # The write-ahead log: a crash mid-write leaves the last commit whole.
        # A full sync on every commit: a credential ended stays ended after a
        # power cut.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        conn.close()
        raise
    return conn


def version(conn: sqlite3.Connection, path: str) -> int | None:
    """The file's schema version; ``None`` for an empty file.

    Raises ``SchemaVersionError`` for a file of another application or version.
    """
    application_id = conn.execute("PRAGMA application_id").fetchone()[0]
    found = conn.execute("PRAGMA user_version").fetchone()[0]
    objects = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
    if application_id == 0 and found == 0 and objects == 0:
        return None
    if application_id != APPLICATION_ID:
        raise SchemaVersionError(f"{path} is not a oneberth store")
    if found != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"{path} holds version {found} of oneberth's store, and this oneberth "
            f"reads version {SCHEMA_VERSION}"
        )
    return int(found)


def setup(conn: sqlite3.Connection, path: str) -> None:
    """Create the tables in an empty file, inside the caller's transaction."""
    if version(conn, path) is None:
        for statement in CREATE_TABLES.split(";"):
            if statement.strip():
                conn.execute(statement)


def _lower(text: str | None) -> str | None:
    return None if text is None else text.lower()
