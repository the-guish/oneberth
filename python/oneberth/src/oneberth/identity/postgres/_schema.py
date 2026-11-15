# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The tables of the store on PostgreSQL, in the schema named ``oneberth``.

The choices behind them:

- Every id is a uuid the core mints, and every time a ``timestamptz`` the core
  sets. No default reads the clock or makes an id.
- A secret is kept as the SHA-256 hex the core hands over, and a row is found
  by it.
- The ``CHECK`` constraints on states are written from the core's enums.
- ``schema_version`` holds one row. It is written last, so a setup that stopped
  half way records no version.
- The setup is one transaction under an advisory lock, so two backends that
  start at once do not race. It reads the version before it changes anything.
- The foreign keys are a second guard. The store's operations keep the
  references whole on their own, as the memory store does.
"""

from __future__ import annotations

from oneberth.identity._records import PairingState

SCHEMA = "oneberth"
"""The PostgreSQL schema that holds the store's tables."""

SETUP_LOCK = 0x6F6E6562
"""The advisory lock the setup holds: "oneb"."""

TABLES = (
    "schema_version",
    "users",
    "sessions",
    "personal_tokens",
    "device_sessions",
    "pairings",
    "service_tokens",
    "pending_sign_ins",
)

_STATES = ", ".join(f"'{state.value}'" for state in PairingState)

_HASH = "~ '^[0-9a-f]{64}$'"

CREATE_TABLES = f"""
CREATE TABLE IF NOT EXISTS schema_version (
    only_row boolean PRIMARY KEY DEFAULT true CHECK (only_row),
    version integer NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    provider text NOT NULL,
    subject text NOT NULL,
    created_at timestamptz NOT NULL,
    name text,
    email text,
    hosted_domain text,
    groups text[] NOT NULL DEFAULT '{{}}',
    CONSTRAINT users_provider_subject_key UNIQUE (provider, subject)
);
CREATE INDEX IF NOT EXISTS users_email_idx ON users (lower(email));

CREATE TABLE IF NOT EXISTS sessions (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    secret_hash text NOT NULL UNIQUE CHECK (secret_hash {_HASH}),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions (user_id);
CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions (expires_at);

CREATE TABLE IF NOT EXISTS personal_tokens (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name text NOT NULL,
    secret_hash text NOT NULL UNIQUE CHECK (secret_hash {_HASH}),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS personal_tokens_user_id_idx ON personal_tokens (user_id);
CREATE INDEX IF NOT EXISTS personal_tokens_expires_at_idx
    ON personal_tokens (expires_at);

CREATE TABLE IF NOT EXISTS device_sessions (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name text NOT NULL,
    platform text NOT NULL,
    app_version text,
    secret_hash text NOT NULL UNIQUE CHECK (secret_hash {_HASH}),
    created_at timestamptz NOT NULL,
    last_used_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS device_sessions_user_id_idx ON device_sessions (user_id);
CREATE INDEX IF NOT EXISTS device_sessions_expires_at_idx
    ON device_sessions (expires_at);

-- A waiting pairing has no claim; a claimed one has its claim hash, its number
-- and its device; an approved one has moved the claim hash to its device.
CREATE TABLE IF NOT EXISTS pairings (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    code_hash text NOT NULL UNIQUE CHECK (code_hash {_HASH}),
    state text NOT NULL CHECK (state IN ({_STATES})),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    claim_hash text UNIQUE CHECK (claim_hash {_HASH}),
    number text CHECK (number ~ '^[0-9]{{6}}$'),
    wrong_tries smallint NOT NULL DEFAULT 0 CHECK (wrong_tries >= 0),
    device_name text,
    device_platform text,
    device_app_version text,
    CONSTRAINT pairings_claim_follows_the_state CHECK (
        (state = 'waiting' AND claim_hash IS NULL AND number IS NULL)
        OR (state = 'claimed' AND claim_hash IS NOT NULL AND number IS NOT NULL
            AND device_name IS NOT NULL)
        OR (state = 'approved' AND claim_hash IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS pairings_user_id_idx ON pairings (user_id);
CREATE INDEX IF NOT EXISTS pairings_expires_at_idx ON pairings (expires_at);

CREATE TABLE IF NOT EXISTS service_tokens (
    id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE,
    role text NOT NULL,
    resource text,
    secret_hash text NOT NULL UNIQUE CHECK (secret_hash {_HASH}),
    created_at timestamptz NOT NULL,
    expires_at timestamptz
);

CREATE TABLE IF NOT EXISTS pending_sign_ins (
    state_hash text PRIMARY KEY CHECK (state_hash {_HASH}),
    provider text NOT NULL,
    nonce text NOT NULL,
    verifier text NOT NULL,
    return_to text NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS pending_sign_ins_expires_at_idx
    ON pending_sign_ins (expires_at);
"""
