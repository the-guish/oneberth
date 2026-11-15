# Overview

Oneberth is two programs. The **shell** signs people in, holds roles and
tokens, draws the rail and forwards each request to its app. The
**launcher** starts everything on a desktop.

The first apps are Robinauts' Chat and neorc.

## Principles

- **Trust is in the credential.** Every request to an app carries a signed
  identity token. The app checks the signature and reads who is asking from
  it. A process gains nothing from the address it calls from.
- **One kind of app.** An app is a web process of its own, in any language.
  The shell reaches it over HTTP.
- **One contract for identity.** A person's browser, a script, a phone and a
  background process all reach an app with the same identity token. The app
  has one check to write.
- **The shell is empty.** The shell owns the rail, sign-in, sessions, roles,
  tokens and forwarding. An app owns its pages, its data and its processes.
- **The platform starts the processes.** A cluster starts and restarts
  processes with its own tools. Oneberth starts processes on a desktop only.
- **An app is one frame.** The shell frames each app once. The app draws its
  own panels inside it.
- **Apps are trusted code.** The operator installs each app. All apps share
  one origin, and a script of one app can reach the others with the
  person's session. Third-party content inside an app is sandboxed by that
  app.
- **Hexagonal.** The Python code follows ports and adapters. `oneberth-core`
  is pure and does no I/O. The adapters are in `oneberth`.

## The system in one page

- **Packages.** `oneberth-core` holds principals, roles, grants, the
  manifest schema and the configuration parser. `oneberth` holds the shell,
  the launcher, the stores, the command line and the built shell UI.
  `oneberth-protocol` holds the TypeScript source of the shell client and
  the shell UI.
- **Commands.** `oneberth shell` runs the shell alone, for a server or a
  cluster. `oneberth desktop` runs the launcher, which starts the shell, the
  apps and the window.
- **Apps.** An app ships a manifest: its id, its title, its roles and, for
  the desktop, its processes. The configuration enables it
  ([apps.md](apps.md)).
- **Identity.** The shell signs people in over OpenID Connect and keeps
  sessions, grants and tokens. It signs a short-lived identity token for
  each request ([identity.md](identity.md)).
- **Gateway.** The shell serves every app under `/apps/<id>/` on one
  origin. It checks the credential, adds the identity token and forwards
  the request ([gateway.md](gateway.md)).
- **Runtimes.** A cluster runs the shell and the apps as its own services.
  A desktop runs them under the launcher, as OS processes or Docker
  containers ([runtimes.md](runtimes.md)).
- **UI.** The shell draws a 48 px icon rail, the sign-in page and the admin
  screen ([shell-ui.md](shell-ui.md)).
- **Protocol.** The rail and an app's frame talk in JSON-RPC 2.0 over
  `postMessage` ([protocol.md](protocol.md)).
- **Storage.** The shell keeps its tables in PostgreSQL on a server and in
  SQLite on a desktop. Each app keeps its own database
  ([storage-and-config.md](storage-and-config.md)).

## One request

A signed-in person completes a task in neorc.

1. The browser sends `POST /apps/neorc/tasks/42/complete` to the shell, with
   the session cookie.
2. The shell checks `Host`, `Origin` and `Sec-Fetch-Site`.
3. The shell reads the session and the person from its database.
4. The shell reads the person's grants in `neorc`. A person with no role
   there gets 403.
5. The shell signs an identity token for 60 seconds: the person, the app,
   the roles.
6. The shell forwards `POST /tasks/42/complete` to neorc, with the token and
   without the cookie.
7. neorc checks the token's signature with a key it holds in memory. It
   reads the roles and decides.
8. neorc does the work in its own database and answers.

The shell keeps the answers of steps 3 and 4 for up to 60 seconds.

## The two setups

| | server or cluster: `oneberth shell` | desktop: `oneberth desktop` |
|---|---|---|
| who | many people, a company | one person, their machine |
| sign-in | OpenID Connect, allow list, roles | none: one local user |
| who starts the processes | the cluster, or the operator's own supervisor | the launcher |
| the shell listens on | the configured address, behind TLS | one loopback port, fixed at the first start |
| the shell's database | PostgreSQL | a SQLite file in the data folder |
| an app's database | what the operator configures for it | a SQLite file of its own in the data folder |
| window | any browser | the installed Chrome, Chromium or Edge in app mode |
| stops | on signal | when the window closes, or on signal |

An app reads its setup from what it is handed: its addresses, its database
and its token.

## Planned

- A cluster's own proxy forwards the requests and asks the shell who is
  asking. The shell then leaves the path of the request bodies.
- Optional sign-in on desktop.
- A command palette (⌘K).
- Scopes on personal tokens.

## Open

- The shell UI's bundle size budget.
- A signed and packaged desktop installer.
