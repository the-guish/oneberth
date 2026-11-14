# Processes

Oneberth is two programs: the launcher and the shell. The launcher starts
and stops every process, the shell among them. The shell serves the web
apps and holds all the state. Both run on one machine, and nowhere else.

## The launcher and the shell

| | the launcher | the shell |
|---|---|---|
| what | `oneberth start` and `oneberth desktop`: the commands a person runs | the shell UI, sign-in, sessions, grants, tokens, storage, the registry, the in-process apps, the forwarder |
| where | a native process on the host | a native process, or a container (below) |
| state | a lock, a record of its processes, the token files | all the rest |
| starts | the shell, the apps' web processes, the apps' background processes, the browser window | nothing |

- The launcher has no API of its own and serves no page.
- The shell never starts a process and never holds the Docker socket.

## Where the shell runs

- **Natively**, when no enabled app needs Docker. The shell is then a child
  process of the launcher. Docker is not needed.
- **In a container**, when at least one enabled app needs Docker: an app
  whose manifest names an `image`. Docker is then required.

The shell is the same program either way. It runs from the same wheel, with
the same ports.

## The shell's ports

| port | who reaches it | accepts |
|---|---|---|
| **A**, the front port | the browser, and apps running as OS processes | sessions, the desktop's local user, tokens |
| **B**, the token port | apps running in containers | service tokens only |
| **C**, the launcher's port | the launcher alone | the launch secret only |

- Port A is on the host's `127.0.0.1`. On the web it is the address the
  operator configures, behind TLS.
- On desktop port A is fixed: the launcher picks a free port at the first
  start and records it in the data folder. Later starts reuse it, so the
  origin stays the same. The launcher picks another only when it is taken.
- Port C is on the host's `127.0.0.1` alone, on the web as on desktop. It
  serves the `/launcher/` routes and nothing else. Ports A and B refuse
  `/launcher/`.
- A native shell binds A and C directly. It has no port B.
- Port B refuses a cookie, a personal token and the local user. A request
  there without a valid service token is answered 401.
- The browser reaches the shell on port A. Nothing native forwards requests.

## Docker networks

- The shell's container is on two kinds of network, which the launcher
  creates:
  - **`oneberth-front`**, which holds the shell alone. Ports A and C listen
    there, and are published from there to the host's `127.0.0.1`. No app
    container is on it, so no app container reaches port A or C.
  - **one network per app**, `oneberth-app-<id>`, which holds that app's
    containers and the shell. Port B listens on each. The shell's name on
    each is `oneberth`.
- An app's containers reach the shell and their own app's containers. They
  reach no other app's containers.

## The shell's container

- The launcher builds the image on the host. It starts from Oneberth's base
  image and installs the enabled in-process Python apps inside it, from a
  lock file and a package index the configuration names
  (`[image] lock = "..."`, `index = "..."`). The install runs in Linux, so a
  macOS or Windows host gets Linux wheels.
- The launcher rebuilds the image when the lock file changes. Otherwise it
  reuses the image it built last, named by the lock file's digest.
- The base image is published with each release, named by digest. An
  air-gapped install loads it with `docker load` and names a local index.
- **Development mode**: `oneberth desktop --dev <app id>=<source folder>`
  mounts that app's source into the shell's container, read only, installs
  it from there at every start and skips the image cache for it.
- The data folder is mounted into the shell's container, at the host's own
  path. The SQLite files stay where they are whether the shell runs natively
  or in a container. Nothing moves when the shell changes place.
- The shell's inputs cross as read-only mounts: the configuration file, each
  app's configuration path, and each path-based app's `ui/` folder. Secrets
  cross as files, never as `docker run -e`.
- On the web, the database address the configuration names must be
  reachable from the shell's container. A `localhost` address is refused when
  the shell runs in a container.
- Host folders an app needs are mounted into the shell's container, as the
  manifest declares and the configuration names ([apps.md](apps.md),
  "Mounts").
- On Linux the shell's container and every app container run as the user
  who started the launcher, so files they write belong to that user.

## Runners

A runner starts one process and stops it. Two exist:

- **OS process**: a `command`, as a child of the launcher, in a process group
  of its own.
- **Docker container**: an `image`, through the `docker` command line the host
  has, named by digest, on its app's network.

A process may declare a `command`, an `image` or both. With both, the
launcher uses the image when the shell runs in a container, and the command
when it runs natively. An app that should run in every setup ships both.

The runner is a port. Another runner is another adapter. No runner places
processes on another machine.

## How each process reaches the shell

| process | runs as | reaches the shell at |
|---|---|---|
| the browser | native | port A |
| a background process | OS process | port A, `http://127.0.0.1:<A>/apps/<id>/` |
| a background process | container | port B, `http://oneberth:<B>/apps/<id>/`, on its app's network |
| an out-of-process web app | OS process | is reached by the shell (below) |
| an out-of-process web app | container | is reached by the shell (below) |

- `ONEBERTH_APP_URL` holds the right address for each process.
- The shell forwards to an out-of-process web app:
  - in an OS process, on a loopback port, when the shell is native;
  - in a container, by its name on its app's network, when the shell is in a
    container.
- A web app that declares only a `command` cannot run with a containerised
  shell. The launcher refuses the start of such an app when it is required,
  and leaves it out with a message when it is optional. The fix is to ship
  an image as well.

## The launcher and the shell talk

- The launcher makes a launch secret at each start and writes it to the
  shell's standard input, which the shell reads once and closes. The secret
  is never in a file, so no other process of the same user can read it.
- Before it starts a process, the launcher asks the shell, on port C with
  the launch secret, for that process's service token and environment. The
  shell answers them and records the process.
- The launcher writes the token to a file the process may read. For a
  container, the file is mounted read only.
- When a process stops, the launcher tells the shell, which revokes its
  token.
- The launcher reports each process's state and restarts to the shell, which
  shows them on the admin screen.
- These routes, under `/launcher/`, are served on port C alone and answer
  only the launch secret.

## Starting

1. The launcher reads the configuration and the manifests. It decides where
   the shell runs, builds the shell's image if needed, and creates the
   networks `oneberth-front` and one per app.
2. It removes what a previous launcher left: containers labelled
   `oneberth.data=<data folder>`, and OS processes named in the previous
   launch's record. The shell revokes every process token at start.
3. It starts the shell and waits until port A answers its health route, for
   up to 60 s.
4. On desktop it opens the window now. The shell shows each app in the rail
   as "starting" until its processes are up.
5. It starts each out-of-process web app and waits for its `health` path,
   for up to 60 s.
6. It starts the background processes.

- Building the shell's image happens before step 3, with its progress in the
  launcher's output. It has a timeout of 15 minutes. On desktop with Docker
  not running, the launcher says so and stops.
- Every container carries the labels `oneberth.data` and `oneberth.launch`,
  so the next launcher finds it.

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
- The launcher keeps a record of the processes it started, in the data
  folder, so the next launcher can clean up after a crash. That record, the
  lock and the token files are the launcher's only state.

## Restarting

- `restart = "always"`: restarted whenever it exits. `on-failure`: when it
  exits non-zero. `never`: left down.
- Restarts back off: 1 s, doubling, at most 60 s. A process up for 5 minutes
  starts the backoff again.
- The shell is restarted the same way, on the same ports. While it is down,
  nothing answers.
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

## Without the launcher

A cluster (Kubernetes, or the like) starts the processes itself. Oneberth
then does less.

- `oneberth shell` runs the shell alone. It starts nothing and revokes no
  token it did not issue to a launcher.
- The operator hands the shell and each app their secrets: service tokens,
  each app's identity secret and database login. `oneberth tokens create`
  mints a service token for that.
- The configuration names where each out-of-process app listens:
  `[apps.<id>] url = "..."`.
- The shell's image is built ahead of time with `oneberth image build`.

## Not offered

- Placing processes on other machines, scaling, rolling updates, health-based
  traffic shifting. A deployment that needs them writes its own Helm chart or
  equivalent, with the shell run as above.

## Open

- Limits per process (memory, CPU), and whether the launcher sets them.
