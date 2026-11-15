# Plan: the first version

## Scope

- This version builds the desktop, in both of its shapes
  ([shapes.md](../specs/shapes.md)).
- The cluster is out of scope for this version only. The specs describe it, and a later
  plan builds it.
- What both applications do on a server today keeps working: PostgreSQL, sign-in through
  identity providers, one backend behind a reverse proxy.

### In this version

| part | what this version builds | spec |
|---|---|---|
| identity | users, sessions, tokens and roles; the memory, PostgreSQL and SQLite stores; sign-in through providers and local sign-in; device pairing; the admin scripts | [identity.md](../specs/identity.md) |
| composition | the contract, `compose_app`, the front listener and the worker listener | [composition.md](../specs/composition.md) |
| the shell | the rail, the session, the sign-in page, the account pages | [shell.md](../specs/shell.md) |
| neorc | the manager as a component; the role table as data; the interface as a package; a SQLite store | [composition.md](../specs/composition.md), [shell.md](../specs/shell.md) |
| Robinauts | the backend as a component; a permission on each route; neorc composed into the backend; neorc's components in the interface; a SQLite store | [neorc-in-robinauts.md](../specs/neorc-in-robinauts.md), "Composed" |
| the desktop | the launcher, the window, the processes shape, the Docker shape with its two networks, untrusted workers in containers | [shapes.md](../specs/shapes.md) |

### Out of this version

- The forwarding component, and a person's credential sent from one backend to another.
- The version check between Robinauts and neorc's manager.
- Two backends on one store, and neorc's own address beside Robinauts'.
- Workers that the platform starts, with tokens from the platform's secrets.
- The worker listener as a service of its own, with a network policy.
- A worker in a VM. The path to the worker listener is open.

## Decisions needed

[review.md](review.md), "Open questions", states each question in full.

| question | needed before step |
|---|---|
| Where does the form that starts a run live? | 7 |
| Whose conversations does a flow handler create? | 7 |
| Do the modes without credentials go away? | 9 |
| Does the launcher start in oneberth? | 9 |
| What does closing the window do? | 9 |
| How does an untrusted worker reach a model? | 11 |

## Steps

Each step leaves both applications working, with their tests passing.

1. **The identity core**, in oneberth. Users, credentials, the allow list and roles, in
   memory, with the contract suite of the store. It starts from neorc's core and adds
   Robinauts' users, device pairing and the check at every use.
2. **The PostgreSQL store, the provider adapter and the admin scripts**, in oneberth.
3. **The contract and `compose_app`**, in oneberth. The contract is written from the routes
   both applications have today. The step includes the `/auth` routes, the checks on a
   request, the security headers, the OpenAPI documents and the server.
4. **neorc on oneberth**, in neorc. `neorc-core` loses the identity core and keeps its role
   table. The manager becomes a component, served under `/neorc/`. The clients and the
   commands use the new address.
5. **`@oneberth/ui`**, in oneberth and neorc. The package holds the session, the sign-in
   page, the rail and the account pages. neorc's interface uses them and becomes a package
   with one root component.
6. **Robinauts on oneberth**, in Robinauts. The backend becomes a component, served under
   `/robinauts/`. Each route declares a permission. The interface uses `@oneberth/ui`.
7. **neorc composed into Robinauts**, in Robinauts. The backend composes both components.
   The interface shows neorc's components in the shell. The frame and the copied navigation
   go away.
8. **The SQLite stores**, in all three. Each store passes the contract suite of its port.
   neorc's manager notifies in memory on SQLite.
9. **The desktop as processes**, in oneberth and Robinauts. The step builds local sign-in,
   the launcher and the window. The launcher starts the backend and the workers, and gives
   each worker a service token.
10. **The test of SQLite with Docker on macOS**, in Robinauts. The data directory is mounted
    into a container, and one process opens the files. The result picks the host directory
    or a Docker volume.
11. **The desktop with Docker**, in oneberth and Robinauts. The step builds the backend's
    image, the two networks, the worker listener, the narrower worker routes and untrusted
    workers in containers.

Steps 1 to 7 remove the duplication.
Steps 8 to 11 are the desktop.

## After this version

The cluster gets a plan of its own. It builds what "Out of this version" lists.
