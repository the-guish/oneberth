# Decisions so far

The project owner's answers, 2026-11-14. Each line is the fact, then the
rule. The longer reasoning is Robinauts' study,
`docs/research/app-shell/STUDY.md`, and its draft ADR 0008; where they differ,
this file wins.

## What Oneberth is

- Oneberth is an empty shell. It has no app of its own.
- It is built in this repository, not inside Robinauts or neorc.
- Two commands: `oneberth start` for the web, multi-user mode, and
  `oneberth desktop` for one person. Developers use `oneberth desktop`.
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
- On a phone the rail becomes a bottom tab bar, 56 px: up to four apps and
  "You", then "More". The app's own panels are its drawers.

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
- Requests to an out-of-process app are forwarded by `oneberth start`
  itself, on httpx, streaming included (server-sent events, long polls) and
  WebSockets. No reverse proxy is required.
- Oneberth starts and stops those processes, as OS processes or Docker
  containers, on the one machine it runs on: on desktop, or on a single host.
- Oneberth is two programs. The **launcher** (`oneberth start`,
  `oneberth desktop`) starts and stops every process and holds no state. The
  **shell** holds all the state and serves the web apps.
- The shell runs natively when no enabled app needs Docker. It runs in a
  container when at least one does. Docker is needed only then.
- The shell has three ports. Port A, on the host's loopback (or the
  configured address on the web), is for the browser and OS processes. Port
  B, on each app's Docker network, is for containers, and accepts service
  tokens only. Port C, on loopback alone, is for the launcher.
- The launcher builds the shell's image from Oneberth's base image and the
  wheels of the enabled in-process Python apps, and reuses it until that set
  changes.
- The launcher starts containers with the `docker` command line. The shell
  never holds the Docker socket.
- A process may declare a command, an image or both. With both, the image is
  used when the shell runs in a container. A web app with only a command
  cannot run with a containerised shell.
- The data folder is mounted into the shell's container. Nothing moves when
  the shell changes place.
- The launcher installs the in-process web apps inside the shell's image,
  from a lock file and a named package index. A development mode mounts an
  app's source and skips the image cache.
- One Docker network per app, with the shell attached to each. An app's
  containers reach the shell and their own app alone.
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
- Who may sign in at all is the configuration file's allow list, as in
  Robinauts and neorc: a provider and one matcher (subject, email, email
  domain, hosted domain, group, everyone).
- People get roles from an admin screen in the shell. The grants are stored in
  the database.
- The configuration file names the first admins, with the allow list's
  matchers. They grant the rest on the admin screen. The file always gets an
  operator back in.
- Two kinds of API tokens: personal tokens, which act as the person who
  minted them; and service tokens, with one role and an optional resource,
  for background processes and machines.

## Storage

- Each app gets its own database login and its own schema on PostgreSQL. The
  login reaches that schema alone, never the shell's tables or another
  app's. On desktop each app gets its own SQLite file.

- Oneberth creates its own tables with idempotent SQL and a `schema_version`
  row, as Robinauts and neorc do: in a schema of its own, `oneberth`, on
  PostgreSQL; in a SQLite file of their own on desktop, beside one file per
  app. (Changed in the specs pull request from "the same SQLite file as the
  apps": apps in other languages write from processes of their own, and one
  file per writer keeps SQLite's single-writer lock local to each.)

## The UI and the protocol

- Oneberth's own routes are FastAPI, as Robinauts and neorc use.

- The shell UI is React and TypeScript, under Robinauts' rules: `react` and
  `react-dom` are the only runtime dependencies.
- An app talks to the shell over `postMessage`. It loads the client from the
  shell, at `/shell/client.js`; the two exchange a protocol version when they
  connect.
- Version 1 of the protocol holds what the rail needs and nothing more: the
  handshake and its version; the app's route, both ways, for deep links and
  Back; the title; badges; the theme; opening another app; and, on a phone,
  which drawer is open. A command palette (⌘K) comes later.

## Configuration and URLs

- One TOML file, named by `ONEBERTH_CONFIG`, configures the shell: sign-in,
  the allow list, the first admins, the enabled apps, and where each app's
  own configuration is. Each app keeps its own file, in its own format.
- Every app lives under `/apps/<id>/`, its API and its pages alike. An app may
  declare old paths, which the shell redirects. Robinauts' `/api/` becomes
  `/apps/chat/api/`.

## Phones and app storage

- Linking phones (Robinauts' pairing and device sessions) belongs to
  Oneberth, for every app, from the first milestone. Robinauts' Android app
  signs in through it.
- Each app adds its own SQLite store, in a pull request of its own repository.
  Oneberth only hands it the file.

## Clusters

- On a cluster Oneberth does less: `oneberth shell` runs the shell without the
  launcher, and the operator hands the shell and the apps their secrets.

## Releases

- PyPI and npm, by trusted publishing, from the first tagged release. Until
  then, an app pins a commit of this repository, as Robinauts pins neorc.

## Names

- Everything is named `oneberth`: Python `oneberth-core` and `oneberth`, npm
  packages under `oneberth`.
