# Composition

oneberth builds the web application. An application gives oneberth a component, and
oneberth composes one or more components into what a backend serves.

## Words

- **Component**: what an application gives oneberth: its name, its routes, its roles and
  what to start and stop.
- **Composition**: the web application oneberth builds from components.

## Written once

- The web framework is FastAPI. An application writes its routes on FastAPI.
- oneberth holds what both applications need: the composing, the server, the `/auth`
  routes, who is asking, the check of a permission, the checks on a request, the security
  headers and the shape of an error. Each is written once.
- oneberth names FastAPI, Starlette and uvicorn as its dependencies, in `oneberth[web]`.
  An application gets the three through oneberth and names no version of its own.

## A component

A component holds:

- its **name**, such as `neorc` or `robinauts`;
- its **roles and permissions**, as data ([identity.md](identity.md), "Roles");
- its **routes**, as a FastAPI router;
- what it **starts and stops** with the backend, such as its stores or neorc's scheduler.

A route is a FastAPI route. oneberth gives it two things:

- a dependency that declares the permission the route needs, and the resource the
  permission applies to;
- a dependency that gives the handler the principal.

The resource is a parameter of the route's path, or the resource of the caller's grant.
A route without a resource serves every resource ([identity.md](identity.md), "Roles").

Every route declares a permission. `compose_app` refuses a component that has a route
without one, and the backend does not start.

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
  "Checks on a request"). A page that a route serves with headers of its own keeps them.
- It limits the size of a body.
- It builds the front listener and the worker listener ([shapes.md](shapes.md), "Listeners").
- It writes one OpenAPI document per component.
- It starts the components in the order given and stops them in reverse.
- It keeps why a start failed. The server's last line then names the component and gives its
  error's sentence. A builtin error, and one with no text, is named by its type.
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

## Details likely to change

- The names `compose_app`, `new_manager_webapp` and `new_robinauts_webapp`.
- The address of the OpenAPI documents.
