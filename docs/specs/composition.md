# Composition

oneberth builds the web application. An application gives oneberth a component, and
oneberth composes one or more components into what a backend serves.

## Words

- **Component**: what an application gives oneberth: its name, its routes, its roles and
  what to start and stop.
- **Contract**: the shapes a component is written in. The contract is part of oneberth and
  imports no third-party code.
- **Composition**: the web application oneberth builds from components.

## The rule on the web framework

- oneberth alone imports the web framework: FastAPI, Starlette and uvicorn.
- neorc and Robinauts import oneberth's contract. Each gets FastAPI through `oneberth[web]`.
- A check in each repository refuses an import of the three anywhere else.
- A need the contract lacks is added to the contract.

## A component

A component holds:

- its **name**, such as `neorc` or `robinauts`;
- its **roles and permissions**, as data ([identity.md](identity.md), "Roles");
- its **routes**;
- what it **starts and stops** with the backend, such as its stores or neorc's scheduler.

A route holds:

- a method and a path;
- the permission it needs, and the resource the permission applies to;
- the shapes of its request and of its answer;
- its kind: a plain answer, a long poll or a stream;
- its handler.

A handler is a plain function. It receives the principal and the request's values, and it
returns data or a stream. It imports nothing of the web framework.

A route without a permission cannot be written.

## Composing

```python
from neorc import new_manager_webapp
from robinauts import new_robinauts_webapp
from oneberth import compose_app

app = compose_app(
    apps=[new_robinauts_webapp(...), new_manager_webapp(...)],
    interface=...,   # the directory of the built interface
)
```

`compose_app` does the following:

- It serves each component's routes under `/<name>/`.
- It serves the oneberth routes under `/auth`, the interface under `/ui/` and `/health`.
- It finds who is asking and checks the route's permission before the handler runs.
- It applies the checks on a write and the security headers ([identity.md](identity.md),
  "Checks on a request").
- It builds the front listener and the worker listener ([shapes.md](shapes.md), "Listeners").
- It writes one OpenAPI document per component.
- It starts the components in the order given and stops them in reverse.
- It turns an application's errors into one answer shape, `{"error": …, "detail": …}`.

## Addresses

| address | served by |
|---|---|
| `/auth/…` | oneberth |
| `/ui/` | the built interface |
| `/health` | oneberth, from every component's state |
| `/<name>/…` | the component of that name |

A component has the same addresses alone and composed. neorc's API is at `/neorc/` in
standalone neorc and in Robinauts.

## The compositions

| backend | components |
|---|---|
| Robinauts on the desktop | `robinauts`, `neorc` |
| Robinauts in a cluster | `robinauts`, and a forwarding component named `neorc` |
| standalone neorc, and neorc's manager in a cluster | `neorc` |

The forwarding component is oneberth's. It serves `/neorc/` by passing each request to
another backend ([neorc-in-robinauts.md](neorc-in-robinauts.md), "Forwarded").

## The interface is composed at build time

- `compose_app` composes backends when a process starts. The interface is one bundle, built earlier.
- The host application's build puts the shell and each application's components in that
  bundle ([shell.md](shell.md)).
- A composition serves the bundle it is given. Robinauts' wheel holds a bundle with neorc inside.

## What the contract covers

The contract covers what the two applications need:

| need | needed by |
|---|---|
| values checked against a shape, in the path, the query and the body | every route |
| an OpenAPI document, which each interface generates its typed client from | both applications |
| a stream of events | Robinauts' turns, over AG-UI |
| a long poll that ends when the client leaves | neorc's events and tasks, Robinauts' change feed |
| a route left out of the OpenAPI document | Robinauts' worker routes |
| a page served with headers of its own | the view of an MCP application |
| a limit on the size of a body | both applications |

## Details likely to change

- The names `compose_app`, `new_manager_webapp` and `new_robinauts_webapp`.
- Whether a shape is a dataclass or a model of a validation library.
- The address of the OpenAPI documents.
