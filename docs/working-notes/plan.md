# Plan: the first version

[gap.md](gap.md) maps the code as it is to the specs.

## Scope

- This version builds the desktop, in both of its shapes
  ([shapes.md](../specs/shapes.md)).
- The cluster is out of scope for this version only. The specs describe it, and a later
  plan builds it.
- What both applications do on a server today keeps working: PostgreSQL, sign-in through
  identity providers, one backend behind a reverse proxy.
- No package is published in this version. Each repository pins the others to a commit
  (["Pins"](#pins)).

### In this version

| part | what this version builds | spec |
|---|---|---|
| identity | users, sessions, tokens and roles; the memory, PostgreSQL and SQLite stores; sign-in through providers and local sign-in; device pairing; the admin scripts | [identity.md](../specs/identity.md) |
| composition | the shape of a component, `compose_app`, the front listener and the worker listener | [composition.md](../specs/composition.md) |
| the shell | the rail, the session, the sign-in page, the account pages | [shell.md](../specs/shell.md) |
| neorc | the manager as a component; the role table as data; the interface as a package; a SQLite store | [composition.md](../specs/composition.md), [shell.md](../specs/shell.md) |
| Robinauts | the backend as a component; a permission on each route; neorc composed into the backend; neorc's components in the interface; a SQLite store | [neorc-in-robinauts.md](../specs/neorc-in-robinauts.md), "Composed" |
| the desktop | the launcher, the window, the processes shape, the Docker shape with workers in containers | [shapes.md](../specs/shapes.md) |

### Out of this version

- The forwarding component, and a person's credential sent from one backend to another.
- The version check between Robinauts and neorc's manager.
- Two backends on one store, and neorc's own address beside Robinauts'.
- Workers that the platform starts, with tokens from the platform's secrets.
- The worker listener as a service of its own, with a network policy.
- Untrusted workers: a worker in a VM, the egress proxy that puts real keys in the place of
  fake ones, and the narrower worker routes. The path between a VM and the worker listener
  is open.
- Publishing the packages to PyPI and npm.

## Pins

- Each repository pins the others to a commit, as Robinauts pins neorc today.
- A Python package is pinned by its git revision, in `[tool.uv.sources]`. uv builds it from
  that commit.
- The pins are: neorc on oneberth; Robinauts on oneberth and on neorc.
- Robinauts pins the oneberth commit that its neorc commit pins. Robinauts' lock then holds
  one oneberth.
- A pinned commit is on the `main` branch of its repository.
- A node package is installed from a checkout of the pinned commit. npm installs a git
  dependency from the root of a repository alone, and the node packages live under `ts/`.
- A script checks the pinned commits out and builds what a release needs.
  `scripts/neorc-from-source.sh` in Robinauts does this for neorc's wheels today.

## Steps

Each step leaves both applications working, with their tests passing.

### 1. The identity core

- In oneberth. Users, credentials, the allow list and roles, in memory, with the contract
  suite of the store.
- The core starts from neorc's and adds Robinauts' users, device pairing and the check at
  every use ([gap.md](gap.md), "The two copies of sign-in").

### 2. The PostgreSQL store, the provider adapter and the admin scripts

- In oneberth.

### 3. `compose_app`

- In oneberth. The step includes the shape of a component, the `/auth` routes, who is
  asking, the check of a route's permission, the checks on a request, the security headers,
  the OpenAPI documents and the server.
- The routes stay on FastAPI in each application: 680 lines in neorc and about 1,700 in
  Robinauts.
- neorc's routes each declare a permission today, with a dependency in
  `manager/_access.py`. The step starts from that dependency.

### 4. neorc on oneberth

- In neorc. `neorc-core` loses the identity core and keeps its role table.
- The manager becomes a component, served under `/neorc/`. The clients and the commands use
  the new address. neorc's clients already take a base address.

### 5. `@oneberth/ui`

- In oneberth and neorc. The package holds the session, the sign-in page, the rail and the
  account pages.
- neorc's interface uses them and becomes a package with one root component.
- neorc's interface package is private today, exports nothing and builds one page. Its
  stylesheet is global, and its one switch for a host is `?embedded`.
- neorc pins React 19.0.8 and Robinauts 19.3.1. The three repositories move React together.
- A node package ships its TypeScript source, since install scripts are disabled in both
  projects. ["Pins"](#pins) says how an application gets it.

### 6. Robinauts on oneberth

- In Robinauts. The backend becomes a component, served under `/robinauts/`.
- Each route declares a permission. Robinauts has no roles today.
- The interface uses `@oneberth/ui`.

### 7. neorc composed into Robinauts

- In Robinauts. The backend composes both components.
- The interface shows neorc's components in the shell. The frame and the copied navigation go away.
- Robinauts' bundle is 101.5 KB against a budget of 400 KB. neorc brings a query library
  and two graph libraries. The budget is measured again.
- A browser allows six connections per origin over HTTP/1.1. A Robinauts tab holds two, and
  neorc's long poll makes three. A hidden application stops its long polls.
- neorc has a basic form to start a run. Robinauts overrides it with an A2UI description of
  its own form ([neorc-in-robinauts.md](../specs/neorc-in-robinauts.md), "The form that
  starts a run").
- Robinauts describes a form in a file of its own today: labels, and lists of values for the
  repository, the agent and the model. `review_loop.form.toml` in the scratchpad's demo is
  one. The step turns such a file into an A2UI description, and Robinauts' own page to start
  a run goes away.
- A flow started by a person creates conversations for that person.

### 8. The SQLite stores

- In all three repositories. Each store passes the contract suite of its port.
- neorc's ports have contract suites today. Robinauts raises `NotImplementedError` for
  local storage.
- neorc tells waiting workers about a new task through PostgreSQL's notifications.
  The manager notifies in memory on SQLite.

### 9. The desktop as processes

- In oneberth and Robinauts. The step builds local sign-in, the launcher and the window.
- The launcher starts the backend and the workers, and gives each worker a service token.
- The launcher is oneberth's. It starts components as processes and as Docker containers.
  The cluster starts Robinauts' web application directly, without it.
- Robinauts' server starts its workers itself today, in `cli/lifecycle.py`. That code is
  where the launcher starts from.
- Closing the window stops the application and ends the turns that run.
- The local user is signed in with the launcher's ticket, and types nothing. The session
  lasts until the application stops. A script uses a personal token from the account page.

### 10. The test of SQLite with Docker on macOS

- In Robinauts. The data directory is mounted into a container, and one process opens the files.
- Docker Desktop on macOS passes file operations through a virtual machine. SQLite's locks
  and shared memory are the risk there.
- The result picks the host directory or a Docker volume with a copy at the switch.

### 11. The desktop with Docker

- In oneberth and Robinauts. The step builds the backend's image, the two networks and the
  worker listener.
- Every worker of this version is a trusted worker. It holds the credentials it needs and
  has a way out, on the `app` network. Most people's setup is this one.
- oneberth's launcher builds the `sandbox` network too. No worker of this version joins it.
- Robinauts' Docker workers use `--network host` today, which works on Linux alone.

Steps 1 to 7 remove the duplication.
Steps 8 to 11 are the desktop.

## Decisions needed

### After this version

**Which VMs, and by what path?** A local VM reaches the worker listener over a host-only
network. A VM elsewhere needs a tunnel or a relay, and the desktop accepts no inbound connection.

Smaller points, with no decision needed yet:

- Windows is not a target of Robinauts today. A desktop application makes the question larger.
- The package names, and the registries, are proposals.
- Robinauts' docs name `open-shipyard/neorc`. The repositories read here are under `the-guish`.
- A desktop that signs in through a company's provider is not specified.

## After this version

The cluster gets a plan of its own. It builds what "Out of this version" lists.

Untrusted workers get a step of their own. It builds:

- A VM for the worker.
- The egress proxy. The worker's engines hold fake keys, and the proxy puts the real key in
  the place of each ([shapes.md](../specs/shapes.md), "Trust").
- The narrower worker routes. Robinauts' worker routes take the owner from the path today.
  A worker learns an owner's id from each turn it runs, and then lists and reads every
  session of that owner. An untrusted worker gets the tasks it holds, and their sessions.
- A worker's own environment. A worker started by the server inherits the server's
  environment today, the database URL included. An untrusted worker gets none of it.
