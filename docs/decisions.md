# Decisions so far

The project owner's answers, 2026-11-14. Each line is the fact, then the
rule. The longer reasoning is Robinauts' study,
`docs/research/app-shell/STUDY.md`, and its draft ADR 0008; where they differ,
this file wins.

## What Oneberth is

- Oneberth is an empty shell. It has no app of its own.
- It is built in this repository, not inside Robinauts or neorc.
- `oneberth start` serves the web apps: each app's ASGI application and its
  built UI, behind the shell's sign-in. Robinauts' Chat and neorc are apps.
- An app is one same-origin frame that draws its own left, central and right
  panels.
- Apps may be written in any language. There are two kinds:
  - **in process**: a Python app, its ASGI application mounted inside
    `oneberth start`;
  - **out of process**: an app in any language, its own web process, which
    Oneberth starts and to which it forwards `/apps/<id>/`.
- Every app ships a manifest file, `oneberth-app.toml`, whatever its
  language. A Python app may point an entry point at it.
- Oneberth finds installed apps (entry points and manifests); the
  configuration says which are enabled. An installed app that is not
  enabled has no tab.
- What crosses between Oneberth and an app is specified as plain HTTP, JSON
  and `postMessage`, never as a Python interface: the shell protocol, the
  identity token, the service tokens.

## The chrome

- A 48 px icon rail on the left, and nothing else. No top bar.
- App icons and their badges at the top of the rail; settings and the profile
  at its foot.
- No kiosk or full-screen mode.

## Two deployment modes, the same apps

- **Desktop**: one person on their own machine. A Chromium window: the
  installed Chrome, Chromium or Edge in app mode, nothing bundled; the default
  browser when none is found. SQLite for storage. No sign-in: one local user,
  a real row, loopback only. Optional sign-in on desktop may come later.
- **Web, multi-user**: sign-in through the company's identity provider,
  PostgreSQL.

## Processes

- The web apps run in one process: `oneberth start`.
- An app's background work (workers, schedulers) runs in processes of its own.
- Oneberth starts and stops those processes, as OS processes or Docker
  containers, on the one machine it runs on: on desktop, or on a single host.
- Nothing more: no cluster scheduling. A deployment that wants several
  services builds its own Helm chart or equivalent.
- A background process reaches its app over the app's own HTTP API, with a
  service token Oneberth issues. This is the pattern Robinauts' workers and
  neorc's workers already use. No message broker.

## Identity, roles and tokens

- Sign-in is Robinauts' own OIDC client on httpx, moved here: Google and Okta,
  code flow with PKCE, no crypto dependency.
- An in-process app reads the principal from the request. An out-of-process
  app gets a short-lived JWT (HS256) in a header on every request, signed
  with a secret of that app's: the person, their roles in that app, the age
  of the session. The app checks it with any JWT library and trusts nothing
  else.
- Roles are plain and per app, with an optional resource:
  `neorc:responder@queue:approvals`. Each app declares its permissions and a
  fixed table from its roles to them. No policy engine.
- People get roles from an admin screen in the shell. The grants are stored in
  the database.
- Two kinds of API tokens: personal tokens, which act as the person who
  minted them; and service tokens, with one role and an optional resource,
  for background processes and machines.

## Storage

- Oneberth creates its own tables with idempotent SQL and a `schema_version`
  row, as Robinauts and neorc do: in a schema of its own, `oneberth`, on
  PostgreSQL; in the same SQLite file as the apps on desktop.

## The UI and the protocol

- The shell UI is React and TypeScript, under Robinauts' rules: `react` and
  `react-dom` are the only runtime dependencies.
- An app talks to the shell over `postMessage`. It loads the client from the
  shell, at `/shell/client.js`; the two exchange a protocol version when they
  connect.

## Names

- Everything is named `oneberth`: Python `oneberth-core` and `oneberth`, npm
  packages under `oneberth`.
