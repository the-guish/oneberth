# Apps

An app is what the rail switches between. Oneberth has none of its own.

## What an app is

- A web process of its own, in any language. It listens on HTTP and serves
  its API and its pages.
- Optionally, background processes: workers, schedulers.
- A manifest, `oneberth-app.toml`.

There is one kind of app. A Python app runs in its own process, like an app
in any other language.

## What an app must do

- **Listen on HTTP/1.1** on the address in `HOST` and the port in `PORT`.
- **Check the identity token on every request**, except its health path and
  its public paths ([identity.md](identity.md), "The identity token"). A
  request without a valid token gets 401.
- **Decide from the token's roles.** The app maps its roles to its own
  permissions and checks them.
- **Use relative URLs.** The app is served under `/apps/<id>/`. A page finds
  its API and its assets relative to its own address.
- **Answer its health path** with 200 when it is ready.
- **Keep no cookie.** The shell removes cookies in both directions
  ([gateway.md](gateway.md)). An app keeps browser state in web storage or
  on its server.

An app keeps no sign-in code, no session table and no token table.

## The manifest

`oneberth-app.toml` holds what the app's author knows. Unknown keys are
errors. All problems are reported at once.

```toml
manifest = 1                      # the manifest's own version
id = "neorc"                      # [a-z][a-z0-9-]{0,31}; the URL segment
title = "Flows"
icon = "flow"                     # a name from the shell's icon set
protocol = 1                      # the shell protocol version the UI speaks
entry = "ui/"                     # the page the shell frames, under /apps/<id>/
health = "healthz"                # answers 200 when the app is ready
public = ["hooks/"]               # path prefixes forwarded without a credential

[roles]                           # the app's roles
default = "user"                  # the role of every signed-in person, or absent

[roles.table]                     # each role and its permissions
user = ["runs:read", "runs:start"]
responder = ["queue:pending", "tasks:complete"]   # granted on a resource
worker = ["tasks:claim", "tasks:finish"]
admin = ["*"]

[roles.resources]                 # the kind of resource a role is granted on
responder = "queue"
worker = "queue"

[[calls]]                         # a call this app makes to another app
app = "chat"
role = "user"

[web]                             # the web process, for the desktop
command = ["neorc", "manager", "start"]
# image = "ghcr.io/example/neorc@sha256:..."

[[process]]                       # a background process, for the desktop
name = "worker-default"
command = ["neorc", "worker", "start", "--queue", "default"]
image = "ghcr.io/example/neorc-worker@sha256:..."
role = "worker"                   # the role of the service token it is handed
resource = "queue:default"        # optional
restart = "always"                # always | on-failure | never

[[mount]]                         # a host folder the processes need
name = "repos"
writable = true
```

- `id` is the app's name in URLs, grants and tokens. The ids `oneberth`,
  `shell`, `auth`, `admin` and `apps` are reserved.
- `icon` names one icon of the shell's set. The set belongs to the shell.
- `[roles.table]` is the app's whole list of roles. The permissions are the
  app's own strings. The shell reads the role names only. `*` means every
  permission the app knows.
- `default` opens the app to everyone who may sign in.
- `[roles.resources]` names the kind of resource a role takes, such as
  `queue`. A grant of that role names one: `queue:approvals`. A role absent
  from the table takes no resource.
- `public` lists path prefixes that outside systems call, such as webhooks.
  The app checks the caller itself there.
- A command gets its address and port from `HOST` and `PORT`.
- `[web]`, `[[process]]` and `[[mount]]` are read by the launcher, on a
  desktop. A server ignores them ([runtimes.md](runtimes.md)).
- A process declares a `command`, an `image` or both. The configuration
  picks one when both are present.

## Finding and enabling an app

- The configuration enables an app and names its manifest:
  `[apps.<id>] manifest = "/opt/neorc/oneberth-app.toml"`.
- A Python app may declare an entry point in the group `oneberth.apps`. Its
  value is the path of the manifest inside the package. The configuration
  then needs only `[apps.<id>]`.
- On a desktop without a configuration file, every app found by entry point
  is enabled.
- On a server the configuration also names where the app listens:
  `[apps.<id>] url = "http://neorc.internal:8420"`.
- An app that is not enabled has no tab and no route.
- Two apps with one `id` refuse the start.

## URLs

| path | what |
|---|---|
| `/` | the shell's page |
| `/shell/` | the shell's assets, `/shell/client.js` among them |
| `/auth/` | sign-in, the session, tokens, keys ([identity.md](identity.md)) |
| `/admin/` | the admin screen's API |
| `/apps/<id>/` | everything of that app: its API and its pages |

- The shell's address bar is `#/<id>/<app route>`. The shell loads the app's
  frame at `/apps/<id>/<entry>` and hands it the route in the handshake. The
  two stay in step over the protocol ([protocol.md](protocol.md)).
- The app receives each request without the `/apps/<id>` prefix
  ([gateway.md](gateway.md)).

## What an app's processes are handed

Every process of an app gets these environment variables. The launcher sets
them on a desktop. The operator sets them on a server.

| variable | value |
|---|---|
| `ONEBERTH_APP_ID` | the app's id |
| `ONEBERTH_ISSUER` | the origin people use; the `iss` of every identity token |
| `ONEBERTH_KEYS_URL` | where the process fetches the shell's public keys |
| `ONEBERTH_SHELL_URL` | where the process reaches the shell |
| `ONEBERTH_APP_URL` | where a background process reaches its own app directly |
| `ONEBERTH_TOKEN_FILE` | a file holding the process's service token: every background process, and a web process whose app declares calls |
| `ONEBERTH_DATABASE_FILE` | desktop: the path of the app's own SQLite file |
| `ONEBERTH_APP_CONFIG` | desktop: the path of the app's own configuration file, when the configuration names one |
| `ONEBERTH_MOUNT_<NAME>` | the path of a declared mount |
| `HOST`, `PORT` | the web process: the address and the port to listen on |

- A secret is handed as a file the process may read.
- `ONEBERTH_ISSUER` is a string to compare. A process inside a cluster may
  be unable to reach it. `ONEBERTH_KEYS_URL` and `ONEBERTH_SHELL_URL` are
  addresses the process can reach.

## Background processes

- A background process is a client of its own app's HTTP API. It pulls work
  by long-polling and reports back by HTTP. The app's web process owns the
  state.
- The process calls its app directly, at `ONEBERTH_APP_URL`. It first
  exchanges its service token for an identity token
  ([identity.md](identity.md), "Exchange").
- The app sees a principal of kind `service` with the token's role. What
  crosses is the app's own API.

## Calls to other apps

- An app declares each app it calls, and the role it needs there:
  `[[calls]] app = "chat" role = "user"`, with an optional `resource`.
- On a desktop the launcher mints a service token with those grants and
  hands it to the app's processes.
- On a server an admin approves each declared call on the admin screen and
  mints the token.
- The app exchanges that token for an identity token naming the other app
  ([identity.md](identity.md), "Exchange"), then calls it directly.

## Conformance

- Oneberth ships test vectors for the app's check: valid tokens, and tokens
  with a wrong audience, a wrong issuer, a past expiry, another algorithm
  and a bad signature.
- An app's check passes every vector before the app is listed as supported.

## Open

- The development loop: running one app from a dev server with hot reload,
  and running one app without the shell.

- Whether an app may serve its manifest itself, so that a cluster needs no
  copy of the file beside the shell.
- How an app's settings that people change at run time are stored.
