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
  port, with a memory store and the store's contract suite. A service token is created
  and revoked by the operator, by the launch secret, or by an admin from a browser
  session. A bearer of that admin creates and revokes none.
- The stores: `oneberth.identity.postgres`, in the PostgreSQL schema `oneberth`, and
  `oneberth.identity.sqlite`, in the file `oneberth.db`. Both pass the contract suite.
  `oneberth.stores.opened_store` opens either for a backend. Its `schema` names
  another PostgreSQL schema, for tests that share a database.
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
  permission with `permit`, and what it starts and stops. A route declares one
  permit, on itself or on an `include_router` call above it. A route that names
  no resource refuses a grant bound to one, such as a worker's to its queue. A
  permit with `bound=True` passes that grant: the route then acts on the grant's
  own resource. A component may also check the service tokens of its roles
  before oneberth creates them.
  `compose_app` composes components into a backend's web application. It serves
  the `/auth` routes, the interface under `/ui/` and `/health`, and checks who is
  asking before a handler runs. `serve` runs the result on uvicorn, with a front
  listener and a worker listener. `oneberth.web.testing` helps an application's
  tests do the same.

  A component starts in its `lifespan`, before any listener serves. Its
  `serving` begins once both listeners serve, before `ready`, and ends before
  they stop. Both run in the order of the components and end in reverse. A
  component sends its own requests to the backend from its `serving`, and
  starts there the parts that call the backend. A `serving` that fails to
  begin stops the start: the others end, the components stop, and nothing
  says `ready`.

- Tokens in memory. A backend mints a service token for a part it starts
  itself with `Access.create_own_token`, in either mode. The token lives in
  the backend's memory and ends with the process. It passes the checks of any
  service token, the application's own included.

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
  across starts. The launcher reads each part's output and logs it for as
  long as the part runs. A line longer than its buffer comes in pieces.
  `oneberth.launcher.testing` holds stand-ins of its ports.

- The desktop with Docker. A component runs as a `Process` of the host or in a
  Docker `Container`: an image, a command, its variables and its mounts. One
  worker in a container puts the whole application in the Docker shape. The
  backend then runs in its container, with the data directory mounted. The
  launcher creates two networks: `app`, for the backend and the trusted
  workers, and `sandbox`, which has no way out, for the backend and the
  untrusted workers. A container on `sandbox` reaches the worker listener
  alone: the front listener binds the backend's address on `app`, and
  `sandbox` has no route to the host. Both listeners are published on the
  host's loopback address. An untrusted worker runs in a container, and gets
  its token and the worker listener's address. A container keeps unreviewed
  code from damage done by accident. It is no boundary against an attacker.

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
