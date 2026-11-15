# Storage and configuration

## The shell's database

| setup | database | the shell's tables |
|---|---|---|
| server or cluster | PostgreSQL | in a schema of their own, `oneberth` |
| desktop | SQLite, one file in the data folder | in that file |

- The shell's tables hold users, sessions, pending sign-ins, personal
  tokens, service tokens, device tokens, grants, signing keys, launch
  tickets, the audit log and the schema version.
- The tables are made by idempotent SQL (`CREATE ... IF NOT EXISTS`) and a
  `schema_version` row, at every start. A database of a newer version than
  the code refuses the start.
- PostgreSQL is reached through asyncpg. SQLite is reached through the
  standard library's `sqlite3`, in WAL mode.
- The storage has one port and two adapters. One contract test suite runs
  against both.
- On a desktop the launcher makes the tables with the same step, then
  writes tokens and the ticket to the SQLite file
  ([runtimes.md](runtimes.md), "Starting").
- The first key pair and the first tables are made under a database lock.
  Several replicas that start together make them once.

## An app's database

- An app owns its database. The shell creates nothing for an app and holds
  no login to an app's data.
- **Server or cluster.** The operator gives each app its database, in the
  app's own configuration. Apps may share one PostgreSQL server, each with a
  login and a schema of its own.
- **Desktop.** Each app gets a SQLite file of its own in the data folder:
  `<data folder>/<id>.sqlite3`. The launcher hands its path in
  `ONEBERTH_DATABASE_FILE`.
- Each app adds its own SQLite store, in its own repository. Chat and neorc
  have PostgreSQL stores today.
- An app makes its own tables in what it is given.
- An app learns about users, roles and tokens from the identity token alone.

## The data folder (desktop)

- The data folder is the operating system's user data folder:
  `~/.local/share/oneberth` on Linux,
  `~/Library/Application Support/Oneberth` on macOS,
  `%LOCALAPPDATA%\Oneberth` on Windows.
- It holds the SQLite files, the browser profile, the port, the state
  file, the logs, the lock and the launcher's record of its processes.
- The folder and its files are readable by the person's account alone. The
  launcher checks this at every start.

## The configuration

- One TOML file, named by `ONEBERTH_CONFIG`, configures the shell. Unknown
  keys are errors. All problems are reported at once.
- A secret is given as the name of an environment variable.
- Each app keeps its own configuration, in its own format.

```toml
public_url = "https://work.example.com"
session_hours = 12
reauth_days = 30

[database]
url_env = "ONEBERTH_DATABASE_URL"

[providers.okta]
title = "Okta"
issuer = "https://example.okta.com/oauth2/default"
client_id = "..."
client_secret_env = "ONEBERTH_OKTA_SECRET"
scopes = ["openid", "email", "profile", "groups"]
groups_claim = "groups"

[[allow]]
provider = "okta"
group = "staff"

[[admin]]                       # the first admins
provider = "okta"
group = "platform-admins"

[apps.chat]                     # enabled, in the rail's order
manifest = "/opt/robinauts/oneberth-app.toml"
url = "http://chat.internal:8000"

[apps.neorc]
manifest = "/opt/neorc/oneberth-app.toml"
url = "http://neorc.internal:8420"
```

- `public_url` is required on a server. It is the origin root: the shell is
  served at `/`.
- `[apps.<id>] url` is where the app listens, on a server. On a desktop the
  launcher writes each app's address to the state file.
- `reauth_days`, 30 by default, is how recent a person's sign-in must be for
  their tokens to work ([identity.md](identity.md), "Leavers").
- `[[admin]]` takes the allow list's matchers, except `everyone`.

### On a desktop

- A desktop needs no file. Every app found by entry point is then enabled,
  in the order found.
- A desktop file holds `[apps]` tables alone: which apps are enabled, each
  app's own configuration, its mounts and which processes run from an
  image.

```toml
[apps.chat]
config = "~/.config/robinauts/robinauts.toml"

[apps.chat.mounts]
repos = "~/code"

[apps.chat.processes.claude-code-worker]
run = "image"
```

- A desktop file with sign-in tables is refused.
- A declared mount with no host folder in the configuration fails that
  app's start.

## Open

- Whether desktop and server may share a database, for someone moving from
  one to the other.
- Backups on desktop.
- The environment the launcher passes to an app's processes beyond the
  variables it sets, such as model provider keys.
