# Storage and configuration

## The database

| mode | database | Oneberth's tables |
|---|---|---|
| web | PostgreSQL, one database | a schema of their own, `oneberth`; tables also prefixed `oneberth_` |
| desktop | SQLite, one file, in the user's data folder | prefixed `oneberth_` |

- Oneberth's tables: users, sessions, pending sign-ins, personal tokens,
  service tokens, grants, app secrets, the audit log, the schema version.
- They are made by idempotent SQL (`CREATE ... IF NOT EXISTS`) and a
  `schema_version` row, at every start, as Robinauts and neorc do. A database
  of a newer version than the code refuses the start.
- PostgreSQL through asyncpg. SQLite through the standard library's
  `sqlite3`, in WAL mode, with a writer lock held by the shell.
- One storage port, two adapters, and one contract test suite run against
  both.

## What an app gets

- A database of its own, when the app's manifest asks for one
  (`[storage] database = true`). The address is in a file, named by
  `ONEBERTH_DATABASE_URL_FILE`:
  - web: the same PostgreSQL server, in a schema of the app's own and under a
    login of the app's own (below);
  - desktop: a SQLite file of the app's own, beside the shell's, at
    `sqlite:///<data folder>/<id>.sqlite3`.
- An app keeps its tables in what it is given, and makes them itself.
- An app may ignore it and use what its own configuration names.
- An app learns about users, roles and tokens from the principal alone.
  Oneberth's tables are the shell's.

## One schema and one login per app (PostgreSQL)

- Each app that asks for a database gets a schema and a PostgreSQL role of
  its own. Both are named `oneberth_app_<id>`, with `-` written as `_`.
- The role owns its schema and has no rights anywhere else. It cannot read
  the `oneberth` schema or another app's.
- The role's `search_path` is its own schema, so the app's tables need no
  schema prefix.
- The shell creates the schema and the role at the app's first start. The
  shell's own login therefore needs `CREATEROLE` and `CREATE` on the
  database. An operator who will not grant them creates each role and schema
  beforehand and names the role in `[apps.<id>] database_role`.
- The shell sets a new random password on each app role at every start, and
  hands it to that app's processes in their URL file. No app password is
  stored.
- Disabling an app keeps its schema and role. Removing them is the
  operator's.

## The data folder (desktop)

- The operating system's user data folder: `~/.local/share/oneberth` on
  Linux, `~/Library/Application Support/Oneberth` on macOS,
  `%LOCALAPPDATA%\Oneberth` on Windows.
- It holds the SQLite files, the browser profile, the logs and the lock.
- When the shell runs in a container, its SQLite files live in the Docker
  volume `oneberth-data` instead. The browser profile, the logs and the lock
  stay in the data folder.

## The configuration

- One TOML file, named by `ONEBERTH_CONFIG`. Unknown keys are errors. All
  problems are reported at once. Secrets are given as the name of an
  environment variable, never as values.
- It configures the shell. Each app keeps its own configuration, in its own
  format; the shell only says where it is.

```toml
public_url = "https://work.example.com"
session_hours = 12

[database]
url_env = "ONEBERTH_SHELL_DATABASE_URL"

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
config = "/etc/robinauts/robinauts.toml"

[apps.flows]
config = "/etc/neorc/flows/"

[apps.reports]                  # an app in another language, found by its folder
path = "/opt/reports"
```

- Desktop needs no file. Without one, every installed app is enabled, in the
  order found; with one, only its `[apps]` tables are read, and a file that
  also holds sign-in tables is refused, as Robinauts' local mode refuses one.
- `public_url` is required on the web and is the origin root: the shell is
  served at `/`.

## Open

- Whether desktop and web may share a database, for someone moving from one
  to the other. Today they cannot: the local user is refused on the web.
- Backups on desktop. On the web they are the operator's.
