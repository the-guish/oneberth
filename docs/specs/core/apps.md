# Apps

An app is what the rail switches between. Oneberth has none of its own.

## What an app is

- A web application: an HTTP API and a built UI, served under
  `/apps/<id>/`.
- Optionally, background processes: workers, schedulers
  ([processes.md](processes.md)).
- A manifest, `oneberth-app.toml`, that says all of the above.

An app draws its own left, central and right panels in one frame. The shell
draws the rail and the frame around the app.

## Two kinds

| | in process | out of process |
|---|---|---|
| language | Python | any |
| web part | an ASGI application, mounted inside the shell's process | a web process of its own, started by Oneberth on a loopback port, to which the shell forwards |
| who it is asking | the principal, read from the request ([identity.md](identity.md)) | the identity token, in a header ([identity.md](identity.md)) |
| cost | none | one process, one hop per request |

- An in-process app runs in the shell's process. A crash or a blocking call
  in it stops the shell too. An in-process app keeps its web part light. Its
  heavy work goes to a background process.
- An out-of-process app is reached over HTTP/1.1 on `127.0.0.1`. The shell
  forwards requests, streamed answers (server-sent events, long polls) and
  WebSockets. It strips any incoming identity header and adds its own.
- A Python app may be either kind. The manifest says which.

## The manifest

`oneberth-app.toml`, at the root of the app's installed files. Unknown keys
are errors. All problems are reported at once.

```toml
manifest = 1                      # the manifest's own version
id = "flows"                      # [a-z][a-z0-9-]{0,31}; the URL segment
title = "Flows"
icon = "flow"                     # a name from the shell's icon set; no logos
protocol = 1                      # the shell protocol version the UI speaks
optional = true                   # a missing optional app is skipped; a missing required app refuses the start

[web]
kind = "in-process"               # or "out-of-process"
asgi = "neorc_oneberth:app"       # in-process: module:attribute of the ASGI app factory
# command = ["neorc-web", "--port", "{port}"]   # out-of-process: argv; {port} is filled in
# image = "ghcr.io/example/app@sha256:..."      # out-of-process, in a container instead
ui = "ui/"                        # the built UI, relative to the manifest; served at /apps/<id>/ui/
entry = "ui/index.html"
health = "/healthz"               # out-of-process: polled until it answers 200
redirects = { "/api/" = "/apps/chat/api/" }    # old paths the shell redirects (308)

[roles]                           # the app's roles and their permissions; fixed
user = ["runs:read", "runs:start", "tasks:complete"]
responder = ["queue:pending", "tasks:complete"]   # granted on a resource, e.g. queue:approvals
admin = ["*"]
default = "user"                  # the role every signed-in person gets in this app, or absent for none

[[process]]                       # background processes; see processes.md
name = "scheduler"
command = ["neorc", "scheduler", "--manager", "{app_url}"]
role = "scheduler"                # the role of the service token it is handed
resource = ""                     # optional
restart = "always"                # always | on-failure | never

[[process]]
name = "worker-default"
image = "ghcr.io/example/neorc-worker@sha256:..."
role = "worker"
resource = "queue:default"
```

- An `icon` names one icon of the shell's set. The set is the shell's
  (lucide's path data, carried in the tree). An app cannot ship an SVG.
- `[roles]` is the app's whole permission table. Permissions are the app's
  own strings; the shell checks only that a grant names a role the table
  has, and hands the app the person's roles. `*` means every permission
  the app knows.
- `default` lets an app be open to everyone allowed to sign in without an
  admin granting anything.

## Discovery and enabling

- A Python app declares an entry point in the group `oneberth.apps`, whose
  value is the path of its manifest inside the package
  (`neorc_oneberth:oneberth-app.toml`).
- An app in another language is a folder holding its manifest, named in the
  configuration (`[apps.<id>] path = "..."`).
- An app found but not enabled in the configuration has no tab, no route and
  no process. A required app that is enabled and not found refuses the start.
- Two apps with one `id` refuse the start.

## URLs

| path | what |
|---|---|
| `/` | the shell's page |
| `/shell/` | the shell's assets, `/shell/client.js` among them |
| `/auth/` | sign-in, the session, tokens ([identity.md](identity.md)) |
| `/admin/` | the admin screen's API |
| `/apps/<id>/` | everything of that app: its API and `/apps/<id>/ui/` |

- The shell's address bar is `#/<id>/<app route>`. The shell loads the app's
  frame at `/apps/<id>/ui/` with the app route in its hash, and keeps the two
  in step over the protocol ([protocol.md](protocol.md)).
- An app finds its API relative to its page, never at the origin root.
- The shell serves its own Content-Security-Policy. An app sets its own on
  its answers. The shell adds `frame-ancestors 'self'` to every answer under
  `/apps/` that sets none, and refuses to frame an answer that says `'none'`.

## Lifecycle

- At the start the shell reads every enabled manifest, mounts the in-process
  apps, starts the out-of-process web processes and waits for their health,
  starts the background processes, then listens.
- At the stop it stops listening, stops the background processes, then the
  web processes, then unmounts. See [processes.md](processes.md) for signals
  and timeouts.
- An in-process app may expose an ASGI lifespan. The shell runs it.

## What the shell hands an app

- In process: the principal per request; its settings at the start (below).
- Out of process: environment variables at the start, the identity token per
  request.

| variable | value |
|---|---|
| `ONEBERTH_APP_ID` | the app's id |
| `ONEBERTH_PUBLIC_URL` | the origin people use |
| `ONEBERTH_APP_URL` | where the app's own processes reach its API |
| `ONEBERTH_APP_CONFIG` | the path of the app's own configuration file, if the shell's configuration names one |
| `ONEBERTH_DATABASE_URL` | the database the app may use ([storage-and-config.md](storage-and-config.md)) |
| `ONEBERTH_MODE` | `web` or `desktop` |
| `ONEBERTH_SIGN_IN` | `on` or `off` |
| `ONEBERTH_IDENTITY_SECRET_FILE` | out of process: a file holding the secret to check identity tokens with |
| `ONEBERTH_TOKEN_FILE` | a background process: a file holding its service token |
| `PORT` | an out-of-process web process: the port to listen on |

Secrets are handed as files the process may read, never as values in the
environment.

## Open

- Whether an app's UI may be served by the app's own web process rather than
  from the manifest's folder, for out-of-process apps that build it at run
  time.
- How an app's settings that people change at run time (as opposed to its
  configuration file) are stored.
