# Contributing to oneberth

## Branching model

`main` is the only long-lived branch. It is always releasable, and direct pushes to it
are blocked.

1. Create a short-lived branch from `main` for each change. Prefix it with `feature/`
   for new functionality or `fix/` for corrections.
2. Open a pull request against `main`.
3. A maintainer merges it once the checks pass and the review is done.

## Repository layout

    python/oneberth/   the oneberth Python library
    ts/                the node packages, with their own tooling
    docs/specs/        the specs: the desired state, and the authority

The Python packages form a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/).
The root `pyproject.toml` holds the ruff, mypy and pytest configuration and the one `uv.lock`.

A base install of `oneberth` brings no third-party code. Each adapter that needs some is
an extra, such as `oneberth[postgres]`. A distribution ships its own copies of `LICENSE`,
`NOTICE` and `AUTHORS`, and CI checks that they match the root's.

The library's modules:

    oneberth/identity/            the core: rules, the store port, Access
    oneberth/identity/memory/     the store in memory
    oneberth/identity/postgres/   the store on PostgreSQL (extra: postgres)
    oneberth/identity/sqlite/     the store in one SQLite file
    oneberth/identity/testing/    ManualClock, and the store's contract suite
    oneberth/config.py            the reader of the TOML configuration
    oneberth/providers.py         the OpenID Connect client (extra: providers)
    oneberth/stores.py            how a backend opens its store
    oneberth/admin.py             the admin scripts, and the `oneberth` command
    oneberth/web/                 components, compose_app, /auth, the server (extra: web)
    oneberth/web/testing.py       what an application's tests use to drive a composition
    oneberth/launcher/            the launcher and the window of the desktop
    oneberth/launcher/_shape.py   the shape, and what each component gets in it
    oneberth/launcher/_docker.py  the Docker port on the `docker` command
    oneberth/launcher/testing.py  stand-ins of the launcher's ports, Docker in memory,
                                  and a manual timer

Test modules have names unique across the repository, such as `test_identity_rules.py`.
pytest and mypy collect them in one run. Shared fixtures go in the root `conftest.py`.

## The checks

Install the packages and the tools into `.venv`, then run the checks CI runs:

    uv sync
    uv run ruff check
    uv run ruff format --check
    uv run mypy
    uv run pytest

## Tests that need PostgreSQL

The tests of the PostgreSQL store run against a real server. They are marked `postgres`,
and `uv run pytest -m "not postgres"` leaves them out. Point them at a database they may
empty:

    export ONEBERTH_TEST_DATABASE_URL=postgresql://postgres:secret@127.0.0.1:5432/oneberth_test

Without the variable, they skip. CI gives them a server.

## The browser journey

One test drives a real Chromium through the node package's development page,
served by a composed backend. It needs the page built, with Node.js 24:

    (cd ts/oneberth-ui && npm ci && npm run build:page)

Playwright then looks for its own Chromium. Set `ONEBERTH_TEST_CHROMIUM` to the
executable of another one. Without the page or a browser, the test skips. CI
builds both for one Python.

## Tests that need Docker

The tests of the launcher's Docker shape run against the real Docker daemon.
They are marked `docker`, and `uv run pytest -m "not docker"` leaves them out.
They build an image from `python:3.12-slim` once per run, with the checkout
and its web dependencies, which `uv` gathers on the host. They skip without a
daemon or `uv`. CI runs them, since its runners have Docker.

## Licence headers

New source files start with the licence header:

    # Copyright 2026 The oneberth Authors
    # SPDX-License-Identifier: Apache-2.0

## In memory first

The logic lives in the core, behind ports. The core imports no database driver, web
framework or HTTP client.

- An adapter stores or moves data. An `if` about users, credentials or roles belongs in
  the core.
- The store is one port. Each method is one atomic operation, and the core never chains
  several calls into one that must be atomic.
- The memory store keeps the semantics of the deployed stores: the same expiry, the same
  limits, the same answers.
- The suite in `oneberth.identity.testing.contracts` binds the stores together. The memory
  store runs it here, and every other store runs the same suite.
- The core reads the time from an injected clock. Tests move the clock; they never sleep.
- Most tests run in memory, in milliseconds. A test of an adapter covers only what the
  adapter adds: SQL, transport, its own concurrency.

## Developer Certificate of Origin

Every contribution is signed off under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/).
Add `-s` to your commit:

    git commit -s -m "area: short summary"

Git then appends a `Signed-off-by` line. Use your real name and a reachable email
address. If you contribute on behalf of an employer, make sure you have their
authorization.
