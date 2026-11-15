# oneberth

oneberth is the shared base of [neorc](https://github.com/the-guish/neorc) and
[Robinauts](https://github.com/the-guish/robinauts). It holds sign-in, sessions, tokens
and roles, the web application, the application shell, the admin scripts and the
desktop launcher.

It ships two packages:

- `oneberth`, a Python library, under [python/oneberth](python/oneberth);
- `@oneberth/ui`, a node package of interface components, under [ts](ts).

## What is built

- The identity core, `oneberth.identity`: users, the four kinds of credential, device
  pairing, the allow list, roles and the decision of a permission. It runs on a store
  port, with a memory store and the store's contract suite.
- The stores: `oneberth.identity.postgres`, in the PostgreSQL schema `oneberth`, and
  `oneberth.identity.sqlite`, in the file `oneberth.db`. Both pass the contract suite.
  `oneberth.stores.opened_store` opens either for a backend.
- The configuration reader, `oneberth.config`: the TOML file that `ONEBERTH_CONFIG` names.
- The OpenID Connect client, `oneberth.providers`, for Google and Okta.
- The admin scripts, `oneberth.admin`. The `oneberth` command runs them on PostgreSQL:

      oneberth store init --database-url postgresql://…
      oneberth tokens create|list|revoke
      oneberth sessions clear
      oneberth devices list|end

  An application shows the same commands under its own name, with its own roles.

- The web part, `oneberth.web`, in the extra `oneberth[web]`. An application gives
  a `Component`: its name, its roles, a FastAPI router whose routes each declare a
  permission with `permit`, and what it starts and stops. `compose_app` composes
  components into a backend's web application. It serves the `/auth` routes, the
  interface under `/ui/` and `/health`, and checks who is asking before a handler
  runs. `serve` runs the result on uvicorn, with a front listener and a worker
  listener. `oneberth.web.testing` helps an application's tests do the same.

- The local sign-in, for the desktop and for development. `compose_app(...,
  local=True)` composes a backend with one user, the person at the machine, who
  holds every role a person can hold. `oneberth.config.local_config` gives its
  configuration. `run` reads the launch secret from standard input. The holder of
  the secret asks `POST /auth/tickets` for a ticket and mints the workers' tokens.
  `GET /auth/local?ticket=…` swaps a ticket for the session cookie. A start by
  hand makes its own secret and prints the address with a ticket.

- The launcher, `oneberth.launcher`, for the desktop as processes. An application
  describes its backend, its workers and its data directory with an `Application`,
  and its command calls `launch`. The launcher starts the backend with the launch
  secret on its standard input and waits for `ready`. It mints a service token per
  worker and starts each worker with its token on its standard input. It then asks
  for a ticket and opens the window. The window is Chrome or Chromium with `--app`,
  on a profile in the data directory. Closing it stops the application: the
  workers first, the backend last. One launcher runs per data directory, and a
  second start brings the window forward. The front listener keeps its port
  across starts. `oneberth.launcher.testing` holds stand-ins of its ports.

The desktop with Docker comes later.

## Provenance

The web part is written from neorc's `manager/` (`_access.py`, `_auth_routes.py`,
`_sign_in.py`, `_ui.py`; Apache-2.0, The neorc Authors) and Robinauts' `web/`
(`cookies.py`, `headers.py`, `pairing.py`, the `/auth` routes of `app.py` and
the check of a local `Host`;
Apache-2.0, The Robinauts Authors). The launcher is written from Robinauts'
`cli/lifecycle.py` (Apache-2.0, The Robinauts Authors). The QR encoder follows ISO/IEC 18004, and its
tests compare it with `qrcodegen`.

## Documents

- [docs/specs](docs/specs/README.md): the specs. They describe the desired state, and
  they are the authority.
- [docs/working-notes](docs/working-notes): the gap between the code and the specs, and
  the plan that closes it.
- [CONTRIBUTING.md](CONTRIBUTING.md): the branching model, the checks and the rules.

oneberth is licensed under the [Apache License 2.0](LICENSE).
