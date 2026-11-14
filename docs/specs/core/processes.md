# Processes

Oneberth runs the web apps in one process, and starts and stops every other
process the enabled apps declare. It does this on the one machine it runs
on, and nowhere else.

## The processes

| process | who runs it | what it is |
|---|---|---|
| the shell | the operator, or the desktop launcher | `oneberth start` or `oneberth desktop`: the shell UI, sign-in, the in-process apps, the forwarder, the supervisor |
| an app's web process | the shell | an out-of-process app's HTTP server, on a loopback port |
| an app's background process | the shell | a worker, a scheduler: whatever `[[process]]` names |
| the browser window | the desktop launcher | the installed Chrome, Chromium or Edge in app mode |

The shell is the supervisor. Nothing else needs to be installed to run an
app's processes, beyond the commands or images its manifest names.

## Runners

A runner starts one process and stops it. Two exist:

- **OS process**: the manifest's `command`, as a child of the shell, in a
  process group of its own.
- **Docker container**: the manifest's `image`, through the `docker` command
  line the host has. The image is named by digest. A container's published
  ports are bound to `127.0.0.1`.

The runner is a port. Another runner is another adapter. No runner places
processes on another machine.

## Starting

- The shell starts the web processes first, and waits until each answers its
  `health` path with 200, for up to 60 s. Then the background processes.
  Then it listens.
- A process that does not start, or a web process that is not healthy in
  time, refuses the start of a required app. An optional app is left out and
  logged.
- Each process gets only the environment of [apps.md](apps.md), "What the
  shell hands an app". The shell's configuration, secrets and database
  credentials stay with the shell. The database URL is handed only when the
  manifest asks for it.

## Stopping

- On SIGTERM or SIGINT, or when the desktop window closes, the shell stops
  listening, then sends SIGTERM to each background process, then each web
  process, and kills what is left after 15 s.
- A container is stopped with `docker stop --time 15`.
- The shell revokes the service tokens of the processes it stopped.
- The shell holds a lock on its data folder (desktop) or a row (web), so a
  second shell on the same data refuses to start.

## Restarting

- `restart = "always"`: restarted whenever it exits. `on-failure`: when it
  exits non-zero. `never`: left down.
- Restarts back off: 1 s, doubling, at most 60 s. A process up for 5 minutes
  starts the backoff again.
- An out-of-process web process that exits is restarted the same way. While
  it is down, its app answers 503 from the shell.

## Logs

- Each process's standard output and error go to the shell's log, a line at
  a time, prefixed with the app and the process name.
- No log leaves the host.

## How a background process reaches its app

The pattern Robinauts' workers and neorc's workers already use:

- The background process is a client of its app's HTTP API, at
  `ONEBERTH_APP_URL`, with the service token in `ONEBERTH_TOKEN_FILE` as a
  bearer.
- It pulls work by long-polling, and reports back by HTTP. The app's web
  part owns the state. No message broker, no shared memory.
- `ONEBERTH_APP_URL` points at the shell, `http://127.0.0.1:<port>/apps/<id>/`,
  so the request passes the shell's checks and the app sees a principal with
  the token's grant. A container reaches the host through the address the
  runner gives it.
- What crosses is the app's own API. Oneberth does not define it.

## Desktop

- `oneberth desktop` is the launcher. It picks a free loopback port, starts
  the shell in desktop mode with the apps' processes, then opens the window:
  `--app=http://127.0.0.1:<port>/` with a profile folder of Oneberth's own.
- Which browser: the installed Chrome, Chromium or Edge, found on the usual
  paths of each operating system. None found: the default browser, in a tab.
- Closing the last window stops everything, as SIGTERM does.
- Docker on desktop is allowed, and not required: an app meant for desktop
  should offer commands.

## Not offered

- Placing processes on other machines, scaling, rolling updates, health-based
  traffic shifting. A deployment that needs them writes its own Helm chart or
  equivalent, and runs the shell and the apps' processes as it sees fit,
  giving each process the same environment.

## Open

- Whether a deployment that runs the processes itself starts the shell with a
  flag that turns the supervisor off, and how it then gets service tokens.
- Limits per process (memory, CPU), and whether the shell sets them.
