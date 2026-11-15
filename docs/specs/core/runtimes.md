# Runtimes

The same apps run in two setups. A server or cluster starts the processes
itself. A desktop starts them with the launcher.

## Who does what

| | server or cluster | desktop |
|---|---|---|
| starts and restarts processes | the cluster, or the operator's supervisor | the launcher |
| the shell | `oneberth shell`, one or more replicas | one child process of the launcher |
| an app's web process | a service the operator runs | an OS process or a container |
| a background process | a service the operator runs | an OS process or a container |
| service tokens | minted by an admin, kept in the platform's secrets | minted by the launcher at each start |
| the window | any browser | Chrome, Chromium or Edge in app mode |

The shell is the same program in both. It starts no process.

## Server or cluster

- `oneberth shell` runs the shell. It reads the configuration, serves the
  UI and forwards to the apps.
- The operator runs each app's web process and background processes with the
  platform's own tools: Kubernetes, compose, systemd.
- The configuration names where each app listens:
  `[apps.<id>] url = "..."`.
- The operator hands each process its environment
  ([apps.md](apps.md), "What an app's processes are handed").
- `oneberth tokens create --grant neorc:worker@queue:default` mints a
  service token and prints it once. The operator stores it as a secret and
  mounts it as the process's token file.
- A proxy or load balancer in front ends TLS and sends every request to the
  shell.
- Oneberth ships no chart. A deployment writes its own.

## Desktop: the launcher

`oneberth desktop` is the launcher. It starts the shell, the apps and the
window on one person's machine, and stops them together.

### Starting

1. The launcher locks the data folder. A second launcher on the same folder
   refuses to start.
2. It removes what a previous launch left: the processes in the last
   launch's record, and the containers labelled with this data folder.
3. It reads the port from the data folder. The first start picks a free
   loopback port and records it. A taken port refuses the start.
4. It writes to the shell's database: one service token per background
   process, and the window's ticket. It deletes the tokens of earlier
   launches.
5. It starts the shell and waits for its health path, for up to 60 s.
6. It opens the window. The rail shows each app as "starting".
7. It starts each app's web process on a free loopback port and waits for
   the app's health path, for up to 60 s.
8. It starts the background processes.

- An app that fails to start is shown in the rail as failed, with its last
  log lines. The other apps run.
- The launcher writes each token before the shell starts. The two programs
  need no channel between them.

### Stopping

- The launcher stops everything on SIGTERM or SIGINT, and when the window
  closes.
- It stops the background processes, then the web processes, then the
  shell. Each gets SIGTERM, or `docker stop --time 15`, and is killed after
  15 s.
- The launcher keeps a record of what it started, in the data folder. The
  next launch reads it to clean up after a crash.

### Restarting

- `restart = "always"` restarts a process whenever it exits. `on-failure`
  restarts it when it exits non-zero. `never` leaves it down.
- Restarts back off: 1 s, doubling, at most 60 s. A process that stays up
  for 5 minutes starts the backoff again.
- The shell and each web process restart the same way, on the same port.

### Logs

- Each process's output goes to the launcher's log, a line at a time,
  prefixed with the app and the process name.
- The log stays in the data folder.

## Desktop: OS processes

- A process with a `command` runs as a child of the launcher, in a process
  group of its own.
- A web process listens on `127.0.0.1` alone, on the port in `PORT`.
- A background process reaches its app at `http://127.0.0.1:<app port>` and
  the shell at `http://127.0.0.1:<shell port>`.
- The token file is readable by the person's account alone.

## Desktop: Docker containers

- A process with an `image` runs as a container. The launcher starts it with
  the `docker` command line the host has.
- Docker is needed only when an enabled process runs from an image.
- The configuration picks the image when a process declares both:
  `[apps.<id>.processes.<name>] run = "image"`. A command is the default.
- An image is named by digest.
- Every container carries a label with the data folder, for the next
  launch's cleanup.
- The token file is mounted read only. A declared mount is mounted at the
  host's own path, so a stored path means the same file to every process.
- On Linux the container runs as the person who started the launcher.

### How a container and the host reach each other

| host | the container reaches the host at | the host reaches a web container at |
|---|---|---|
| Linux, Docker Engine | `127.0.0.1`, with `--network host` | `127.0.0.1:<port>`, with `--network host` |
| Docker Desktop, macOS and Windows | `host.docker.internal` | a port published on `127.0.0.1` |

- The launcher picks the row and sets the process's addresses to match.
- A container shares the host's network on Linux. Docker packages a process
  here. The identity token protects each app, as it does for OS processes.
- The shell always runs as an OS process.

## The window

- The launcher opens the installed Chrome, Chromium or Edge with
  `--app=<url>` and a browser profile folder of Oneberth's own. The window
  has no navigation bar.
- The launcher finds the browser on the usual paths of each operating
  system. With none found, it opens the default browser in a tab.
- **The ticket.** The URL is `http://127.0.0.1:<port>/auth/launch?ticket=…`.
  The ticket is random, works once and expires after 60 s. The shell
  exchanges it for the local user's session cookie and redirects to `/`.
- **The origin stays the same.** The port is fixed at the first start, so
  the theme and each app's web storage survive a restart.
- **Closing.** The shell's page sends a heartbeat every 5 s. The shell's
  health path reports the age of the last one. The launcher stops everything
  when the browser process exits, or when the heartbeat is 15 s old.

## Not offered

- Placing processes on other machines, scaling and rolling updates. The
  cluster does these.
- A launcher on a server.

## Open

- Whether Docker Desktop reaches a host process that listens on loopback
  alone. The table above assumes it does.
- Limits per process (memory, CPU), and whether the launcher sets them.
- How the launcher reports a failed app when the window is the default
  browser.
