# Deployment shapes

The same components run in every shape ([core.md](core.md), "Components").
A shape decides who starts a component, where it listens and where the data lives.

## Supervisors

- A component is started by a supervisor. The supervisor is the platform in a cluster and
  the launcher everywhere else.
- A backend starts nothing outside its own process.

## Listeners

- A backend has a **front listener**. It serves the interface, the API and `/auth`.
- A backend may open a **worker listener**. It serves the routes a worker role may call.
- The routes of the worker listener are derived. Every route declares its permission, and a
  route is served there when a worker role holds that permission.
- A network that holds untrusted workers reaches the worker listener and the egress proxy alone.
- The composition builds both listeners ([composition.md](composition.md), "Composing").

## Trust

| level | who | holds | reaches |
|---|---|---|---|
| trusted | the backend, the manager, the scheduler, the launcher | the database, the operator's secrets | everything |
| trusted worker | a worker that runs the project's own code | a token, and the keys its engines need | the worker listener, the model providers, the tool servers |
| untrusted worker | a worker that runs code nobody reviewed, such as code an agent writes | a token, and fake keys | the worker listener; the model providers, through the egress proxy |

An untrusted worker follows these rules:

- It runs in a container or in a VM. A process on the host reaches every loopback port.
- Its token is bound to one queue or to one worker name.
- It reads only the tasks it holds, and the sessions of those tasks.
- It holds none of the operator's secrets: no model key, no database URL, no tool server secret.
- It reaches a model provider through the egress proxy. Its engines hold fake keys, and the
  proxy puts the real key in the place of each.
- The egress proxy passes a call on to the model providers alone.
- It keeps its engines' state in a directory of its own: `workers/<name>` in the data directory.
- That directory is all it sees of the host. It mounts the directory or a directory inside
  it, and nothing else: not the data directory, the window's profile, another worker's
  directory, a path outside the data directory or the Docker socket.
- A link inside that directory that leads out of it stops the start.

A token limits every worker, trusted or not. The network is the second limit.

## Starting a worker

- The supervisor gives a worker a token and the address of the worker listener.
- A worker reads its token from standard input, or from a file that a variable names.
- A worker says `ready` on standard output once it serves. The launcher waits for that line.
- The launcher stops a worker with SIGTERM.

## The cluster

- The platform runs each part as a workload of its own: Robinauts' backend, with several
  replicas; neorc's manager; one scheduler; each worker.
- The database is PostgreSQL. One database holds three schemas: `robinauts`, `neorc`, `oneberth`.
- People sign in through identity providers. TLS ends in front of the backends.
- Each application has a public URL of its own. Robinauts' backend forwards `/neorc/` to
  neorc's manager ([neorc-in-robinauts.md](neorc-in-robinauts.md)).
- The operator creates the service tokens with the command line. The platform keeps them as
  secrets and gives each to its workload as a file.
- The worker listener is a service of its own, kept off the public entry. A network policy
  lets the worker workloads reach that service alone.
- One image per application serves the cluster and the desktop's Docker shape.
- A single server is a supported shape too. `robinauts start` uses the launcher there for
  its own processes, behind a reverse proxy, and composes neorc's manager as the desktop does.

## The desktop, as processes

- The launcher starts the backend as one process, each worker as a process, and the window.
- The database is SQLite, in the data directory.
- neorc's manager and scheduler run inside the backend's process, as parts of the composition.
- The person is signed in locally ([identity.md](identity.md), "Locally").
- The front listener is on a loopback address.
- Every worker is a trusted worker here. An untrusted worker needs the Docker shape or a VM.
- This shape needs no Docker.

## The desktop, with Docker

The configuration names at least one worker that runs in a container. The whole
application then runs in this shape.

- The launcher creates the networks, then starts the backend's container, the workers'
  containers, the workers that run as processes, and the window.
- The backend runs in a container, from the image the cluster uses.
- The data directory is the same host directory as in the processes shape, mounted into the
  backend's container. A person who adds a first Docker worker keeps their data.
- The front listener is published on a loopback address of the host. The window opens there.
- The worker listener is published on a loopback address too, for the workers that run as processes.
- The launcher talks to Docker. The backend's container holds no Docker socket.
- The launcher refuses to start while Docker is not running. It names the workers that need it.

There are two networks:

| network | holds | way out |
|---|---|---|
| `app` | the backend and the trusted workers' containers | yes |
| `sandbox` | the backend, the egress proxy and the untrusted workers' containers | the egress proxy alone |

The `sandbox` network is an internal Docker network. Its workers reach the worker listener
and the egress proxy alone.
The egress proxy is on both networks. The launcher starts it when the configuration names
an untrusted worker.

```mermaid
flowchart LR
    subgraph host
        launcher
        window
        hw[worker, a process]
    end
    subgraph app network
        backend
        tw[trusted worker]
    end
    subgraph sandbox network
        uw[untrusted worker]
        proxy[egress proxy]
    end
    window -- front listener --> backend
    hw -- worker listener --> backend
    tw -- worker listener --> backend
    uw -- worker listener --> backend
    uw -- model calls --> proxy
    launcher -. starts .-> backend
    launcher -. starts .-> tw
    launcher -. starts .-> uw
```

A service on the host's loopback address, such as a local tool server or a local model, is
outside the container. The backend and its workers reach it through the
host's gateway name.

## A worker in a VM

- A VM worker is an untrusted worker. It follows the same rules as a container on `sandbox`.
- The supervisor gives the VM a token and the address of the worker listener.
- The path between the VM and the listener is open.

## The launcher

- The launcher is a part of the `oneberth` Python library. An application's command calls it.
- The launcher starts components as processes and as Docker containers.
- A cluster starts Robinauts' web application directly, without the launcher.
- The application gives the launcher a list of components. Each has a name, a command or an
  image, a trust level and the configuration it needs.
- The launcher runs on Linux and macOS.
- One launcher runs per data directory. A second start brings the first one's window forward.

The launcher starts an application in this order:

1. It makes the launch secret.
2. It starts the backend and writes the launch secret on its standard input.
3. It waits for the backend to say `ready`.
4. It asks the backend for one service token per worker.
5. It starts each worker and writes the worker's token on its standard input.
6. It asks the backend for a ticket and opens the window with it.

The launcher stops the workers first and the backend last.
The launch secret, the tokens and the session of a start end at the stop.

## The window

- The window is Chrome or Chromium started with `--app=<url>`. It has no address bar and no tabs.
- The window uses a profile directory of its own, inside the data directory. The launcher can
  then watch the window's process, and the session cookie stays out of the person's everyday profile.
- Closing the window stops the application. The turns that run then end.
- The launcher looks for Chrome, Chromium, Edge and Brave. It opens the default browser at the
  same URL when it finds none. The application then stops on a signal alone.
- The front listener keeps the same port across starts. A browser remembers the theme, the
  open application and the folded panels per origin.
- A link to another site opens in a plain window of the same profile. This is a known limit.

## Storage

| | the cluster | the desktop |
|---|---|---|
| Robinauts' records | schema `robinauts` | `robinauts.db` |
| neorc's records | schema `neorc` | `neorc.db` |
| oneberth's store | schema `oneberth` | `oneberth.db` |
| an engine's state | the engine's tables | `workers/<name>`, a folder per worker |

- The backend's process alone opens the SQLite files.
- The manager on PostgreSQL tells waiting workers about a new task through the database's
  notifications. SQLite has none across processes. The manager on SQLite runs inside the
  backend and notifies in memory.
- The memory stores serve tests and `neorc run`.
- oneberth, neorc and Robinauts' controller each have a SQLite store. Each store passes the
  contract suite of its port.

## Details likely to change

- The names of the networks, of the database files and of the workers' directory.
- The list of browsers the launcher looks for.
- Where the data directory is on each operating system.

## Open

- The path between a VM and the worker listener.
- The data directory with Docker on macOS: the host directory, or a Docker volume.
