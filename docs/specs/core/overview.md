# Overview

Oneberth is an empty shell that hosts apps. It draws an icon rail, signs
people in, holds their sessions, roles and tokens, and frames the apps.
It has no app of its own.

Its first apps are Robinauts' Chat and neorc. The same apps run on one
person's desktop and on a company's server.

## Goals

### 1. Apache-2.0 without restrictions

- Everything here is Apache-2.0. Every dependency is scanned, transitively,
  against the licence allowlist of [DEPENDENCIES.md](../../../DEPENDENCIES.md).
  A dependency that fails the scan breaks the build.

### 2. Secure, and fit for a company

- Sign-in is through the company's identity provider: Google and Okta, over
  OpenID Connect.
- Every request to every app passes the shell's checks first.

### 3. Nothing leaves the host

- No telemetry, no CDN, no web font, no hosted service. The only outbound
  traffic Oneberth makes is to the identity providers at sign-in.

### 4. Compose over build

- Use an existing component where one fits. Build the glue and the missing
  parts. Where Robinauts or neorc already have working code, move it here
  rather than write it again.

### 5. A small footprint

- Web: one shell process, one database. An app adds the processes it
  declares, and no other service.
- Desktop: one launcher, a browser window, one SQLite file.

### 6. Apps in any language

- Every contract between Oneberth and an app is plain HTTP, JSON or
  `postMessage`. No contract is a Python interface.

## Principles

- **The shell is empty.** It owns the rail, sign-in, sessions, roles,
  tokens, the app registry and the processes. An app owns its pages, its
  panels and its data.
- **An app is one frame.** The shell frames each app once. The app draws its
  own left, central and right panels. The shell draws nothing inside it.
- **Apps are trusted code.** An app is installed by the operator. Same-origin
  frames isolate styles and crashes, not privileges: an app's script can
  reach the shell and other apps with the person's session. Third-party
  content inside an app stays sandboxed by that app, as Robinauts sandboxes
  MCP views.
- **One seam per part.** Each external piece (the identity provider, the
  database, the process runner, the browser on desktop) is behind one
  interface, with a discard test: removing it breaks one known place.
- **Hexagonal.** Python code follows ports and adapters: a pure core,
  `oneberth-core`, with no I/O; adapters in `oneberth`.

## The system in one page

- **Packages.** `oneberth-core` (pure: principals, roles, grants, the
  manifest schema, the configuration parser). `oneberth` (FastAPI routes,
  sign-in, the stores, the app registry, the forwarder, the process
  supervisor, the CLI, and the built shell UI as package data).
  `oneberth-protocol` (the TypeScript source of the shell client and the
  shell UI).
- **Commands.** `oneberth start` runs the web, multi-user mode.
  `oneberth desktop` runs one person's desktop.
- **Apps.** Found by entry point or manifest; enabled by the configuration;
  mounted in process (Python) or forwarded to (any language) under
  `/apps/<id>/` ([apps.md](apps.md)).
- **Identity.** OIDC sign-in, server-side sessions, an allow list, per-app
  roles granted on an admin screen, personal and service tokens. An
  out-of-process app gets a short-lived signed token on every request
  ([identity.md](identity.md)).
- **Processes.** Oneberth starts and stops each app's web process (out of
  process) and background processes, as OS processes or Docker containers,
  on the machine it runs on. A background process reaches its app over the
  app's HTTP API with a service token ([processes.md](processes.md)).
- **UI.** A 48 px icon rail, no top bar; a bottom tab bar on phones; the
  sign-in page; the admin screen ([shell-ui.md](shell-ui.md)).
- **Protocol.** JSON-RPC 2.0 over `postMessage`, version 1: handshake,
  route, title, badges, theme, open, drawers ([protocol.md](protocol.md)).
- **Storage.** PostgreSQL on the web, SQLite on desktop; Oneberth's own
  tables by idempotent SQL ([storage-and-config.md](storage-and-config.md)).

## The two modes

| | web: `oneberth start` | desktop: `oneberth desktop` |
|---|---|---|
| who | many people, a company | one person, their machine |
| sign-in | OIDC, allow list, roles | none: one local user |
| listens on | the configured address, behind TLS | loopback only, a free port |
| database | PostgreSQL | one SQLite file in the user's data folder |
| window | any browser | the installed Chrome, Chromium or Edge in app mode; else the default browser |
| processes | the shell, and what the enabled apps declare, on one host | the same, on the desktop |
| stops | on signal | when the window closes or on signal |

An app does not branch on the mode beyond what it is told: the storage it is
handed, and whether sign-in is on.

## Planned

- Linking phones, for every app: pairing and device sessions, moved from
  Robinauts.
- Optional sign-in on desktop.
- A command palette (⌘K).
- Scopes on personal tokens.

## Open

- The shell UI's bundle size budget.
- Whether an app may run more than one web process.
- A signed and packaged desktop installer, as opposed to `pip install`.
