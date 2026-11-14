# Processes

Oneberth is two programs: the launcher and the shell. The launcher starts
and stops every process, the shell among them. The shell serves the web
apps and holds all the state. Both run on one machine, and nowhere else.

## The launcher and the shell

| | the launcher | the shell |
|---|---|---|
| what | `oneberth start` and `oneberth desktop`: the commands a person runs | the shell UI, sign-in, sessions, grants, tokens, storage, the registry, the in-process apps, the forwarder |
| where | a native process on the host | a native process, or a container (below) |
| state | none | all of it |
| starts | the shell, the apps' web processes, the apps' background processes, the browser window | nothing |

- The launcher has no API of its own and serves no page.
- The shell never starts a process and never holds the Docker socket.

## Where the shell runs

- **Natively**, when no enabled app needs Docker. The shell is then a child
  process of the launcher. Docker is not needed.
- **In a container**, when at least one enabled app needs Docker: an app
  whose manifest names an `image`. Docker is then required.

The shell is the same program either way. It runs from the same wheel, with
the same two ports.

## The shell's two ports

| port | who reaches it | accepts |
|---|---|---|
| **A**, the front port | the browser, and apps running as OS processes | sessions, the desktop's local user, tokens |
| **B**, the token port | apps running in containers | bearer tokens only |

- Port A is on the host's `127.0.0.1`. On the web it is the address the
  operator configures, behind TLS. A native shell binds it directly. A shell
  in a container publishes it to that address.
- Port B is on the Docker network `oneberth`, which the launcher creates.
  Only containers on that network reach it. A native shell has no port B.
- Port B refuses a cookie and the local user. A request there without a
  valid bearer token is answered 401.
- The browser reaches the shell on port A. Nothing native forwards requests.

## The shell's container

- The image is built by the launcher on the host, from Oneberth's base image
  and the wheels of the enabled in-process Python apps.
- The launcher builds it at start when the set of enabled apps or their
  versions changed. Otherwise it reuses the image it built last, named by
  the set's digest.
- The base image is published with each release, named by digest. An
  air-gapped install loads it with `docker load`.
- The shell's storage is a Docker volume, `oneberth-data`: the SQLite files
  on desktop. On the web, the database is PostgreSQL, as without Docker.
- Host folders an app needs are mounted into the shell's container, as the
  manifest declares and the configuration names ([apps.md](apps.md),
  "Mounts").

## Runners

A runner starts one process and stops it. Two exist:

- **OS process**: a `command`, as a child of the launcher, in a process group
  of its own.
- **Docker container**: an `image`, through the `docker` command line the host
  has, named by digest, attached to the network `oneberth`.

The runner is a port. Another runner is another adapter. No runner places
processes on another machine.

## How each process reaches the shell

| process | runs as | reaches the shell at |
|---|---|---|
| the browser | native | port A |
| a background process | OS process | port A, `http://127.0.0.1:<A>/apps/<id>/` |
| a background process | container | port B, `http://oneberth:<B>/apps/<id>/` |
| an out-of-process web app | OS process | is reached by the shell (below) |
| an out-of-process web app | container | is reached by the shell (below) |

- `ONEBERTH_APP_URL` holds the right address for each process.
- The shell forwards to an out-of-process web app:
  - in an OS process, on a loopback port, when the shell is native;
  - in a container, by its name on the network `oneberth`, when the shell is
    in a container.
- An OS-process web app with a containerised shell is not offered. Such an
  app ships an image, or the shell runs natively.

## The launcher and the shell talk

- The launcher makes a launch secret at each start and hands it to the
  shell as a file.
- Before it starts a process, the launcher asks the shell, on port A with
  the launch secret, for that process's service token and environment. The
  shell answers them and records the process.
- The launcher writes the token to a file the process may read. For a
  container, the file is mounted read only.
- When a process stops, the launcher tells the shell, which revokes its
  token.
- These routes, under `/launcher/`, answer only the launch secret.

## Starting

1. The launcher reads the configuration and the manifests. It decides where
   the shell runs, builds the shell's image if needed, and creates the
   network `oneberth`.
2. It starts the shell and waits until port A answers its health route, for
   up to 60 s.
3. It starts each out-of-process web app and waits for its `health` path,
   for up to 60 s.
4. It starts the background processes.
5. On desktop it opens the window.

- A process that does not start, or a web process that is not healthy in
  time, refuses the start of a required app. An optional app is left out and
  logged.
- Each process gets only the environment the shell answered
  ([apps.md](apps.md), "What the shell hands an app").

## Stopping

- On SIGTERM or SIGINT, or when the desktop window closes, the launcher stops
  the background processes, then the out-of-process web apps, then the
  shell. Each gets SIGTERM, or `docker stop --time 15`, and is killed after
  15 s.
- The launcher holds a lock on its data folder, so a second launcher on the
  same data refuses to start.

## Restarting

- `restart = "always"`: restarted whenever it exits. `on-failure`: when it
  exits non-zero. `never`: left down.
- Restarts back off: 1 s, doubling, at most 60 s. A process up for 5 minutes
  starts the backoff again.
- The shell is restarted the same way. While it is down, nothing answers.
- An out-of-process web app that exits is restarted the same way. While it
  is down, the shell answers 503 for its app.

## Logs

- Each process's standard output and error go to the launcher's log, a line
  at a time, prefixed with the app and the process name. Containers' logs
  are read with `docker logs --follow`.
- No log leaves the host.

## How a background process reaches its app

The pattern Robinauts' workers and neorc's workers already use:

- The background process is a client of its app's HTTP API, at
  `ONEBERTH_APP_URL`, with the service token in `ONEBERTH_TOKEN_FILE` as a
  bearer.
- It pulls work by long-polling, and reports back by HTTP. The app's web
  part owns the state.
- The request passes the shell's checks, and the app sees a principal with
  the token's grant.
- What crosses is the app's own API. Oneberth does not define it.

## Desktop

- `oneberth desktop` is the launcher in desktop mode. It starts everything as
  above, then opens the window: `--app=http://127.0.0.1:<A>/` with a browser
  profile folder of Oneberth's own.
- Which browser: the installed Chrome, Chromium or Edge, found on the usual
  paths of each operating system. None found: the default browser, in a tab.
- Closing the last window stops everything, as SIGTERM does.
- Docker on desktop is needed only when an enabled app ships an image.

## Not offered

- Placing processes on other machines, scaling, rolling updates, health-based
  traffic shifting. A deployment that needs them writes its own Helm chart or
  equivalent.

## Open

- Whether a deployment that runs the processes itself starts the shell
  without the launcher, and how it then gets service tokens.
- Limits per process (memory, CPU), and whether the launcher sets them.
