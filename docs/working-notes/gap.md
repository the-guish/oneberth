# The gap between the code and the specs

The code was read at neorc `26a30a0` and Robinauts `e2f276d`.
[plan.md](plan.md) holds the steps that close the gap.

## The two copies of sign-in

Robinauts' sign-in was written from neorc's design, and `docs/legal/ip-clearance.md` records it.
The two copies have the same shape and differ in these points. The last column is what
[identity.md](../specs/identity.md) keeps.

| topic | neorc | Robinauts | the specs keep |
|---|---|---|---|
| users | no table; a principal is what its provider said | a `users` table | Robinauts' table |
| the allow list is checked | at sign-in | at sign-in and at every use, once a minute | Robinauts' check at every use |
| roles | six fixed roles, a permission per route, tokens bound to a queue | none; an `admin` key is refused | neorc's model, for both applications |
| tokens | named, with a role, created with the command line on the database, no expiry by default | per person, minted in the browser from a fresh session, 90 days | both: service tokens and personal tokens |
| devices | none | pairing with a QR code and a number | Robinauts' pairing |
| the cross-site check by `Sec-Fetch-Site` | in the code | in the spec, absent from the code | the check |
| a bearer and a cookie together | refused | accepted, bearer first | neorc's refusal |
| sign-in off | `--no-auth`: no roles, everything allowed | `--dev-no-sign-in`: one local user, loopback, a `Host` check | neither; the local sign-in, with Robinauts' local user and `Host` check |
| stores | memory, PostgreSQL | in process, PostgreSQL | memory, PostgreSQL and SQLite |
| the session in the browser | a query library | React's store hook | Robinauts' store hook |

The copies in lines of code:

| part | neorc | Robinauts |
|---|---|---|
| the identity core | `neorc_core/_access.py`, 654 | `web/sign_in.py`, 418 |
| the OpenID Connect client | `auth/_oidc.py`, 328 | `web/oidc.py`, 299 |
| the configuration | `auth/_config.py`, 396 | in `web/sign_in.py` |
| cookies, the guard, the routes | `manager/`, 451 in three files | `web/cookies.py`, 42, and part of `web/app.py` |
| the stores | 714 in four files | 708 in two files |
| device pairing | none | `web/pairing.py`, 224 |
| the interface | `session.ts` and `SignIn.tsx`, 130 | `session/` and `devices/`, about 1,700 |

## How Robinauts uses neorc

- Robinauts pins `neorc[http,manager,postgres]`, `neorc-core` and `neorc-ui` to one commit.
- One file imports neorc: `orchestrator/adapters/neorc/embedded.py`, 401 lines.
- The manager is mounted at `/neorc` with no authentication. Robinauts allows it only with
  `--dev-no-sign-in`.
- The interface frames neorc's built interface in an `<iframe>`. It draws its own copy of
  neorc's navigation and its own form to start a run.

## What moves to oneberth

| part | from neorc | from Robinauts | to oneberth's |
|---|---|---|---|
| identities, the allow list, sessions, pending sign-ins | `neorc_core/_access.py` | `web/sign_in.py` | identity core |
| the OpenID Connect client | `neorc/auth/_oidc.py` | `web/oidc.py` | provider adapter |
| the sign-in configuration | `neorc/auth/_config.py` | `web/sign_in.py` | configuration reader |
| cookies and the checks on a write | `manager/_sign_in.py`, `manager/_access.py` | `web/cookies.py`, `web/app.py` | web part |
| the `/auth/*` routes | `manager/_auth_routes.py` | `web/app.py` | web part |
| the credential stores | `ports/_credentials.py`, memory, PostgreSQL | `Credentials`, in process, PostgreSQL | one port, with memory, PostgreSQL and SQLite stores |
| the check of a permission | `authorize` in `neorc_core/_access.py` | none | identity core |
| users | none | `users` | store |
| device pairing | none | `web/pairing.py` | identity core |
| token commands | `neorc tokens`, `neorc sessions` | `robinauts devices` | admin scripts |
| the web application and its server | `manager/_app.py`, `manager/_service.py` | `web/app.py`, `cli/main.py` | composition |
| the start of the workers | none | `cli/lifecycle.py` | launcher |
| the security headers on the interface | `manager/_ui.py` | `web/headers.py` | web part |
| the session in the browser, the sign-in page | `session.ts`, `SignIn.tsx` | `session/`, `devices/` | node package |

The routes stay in each application, and are written again in oneberth's contract:
`manager/_routes.py` in neorc, 680 lines, and `web/app.py` with `web/worker_api.py` in
Robinauts, about 1,700 lines.

## What each application stops having

| part | stops having |
|---|---|
| Robinauts' backend | the manager served without authentication, and the rule that refuses flows while sign-in is on; the rewrite of neorc's frame headers, `Framable`; `flows_url` in the answer of `GET /auth/session`; `--dev-no-sign-in`; the start of its own workers |
| Robinauts' interface | the Sessions and Flows tabs; its copy of neorc's navigation (`flows/FlowsSection.tsx`, `flows/orchestrator.ts`); the frame around neorc's interface (`flows/FlowsPage.tsx`); its own page to start a run (`flows/NewRunPage.tsx`, `flows/intake.ts`); the profile block of its panel; `session/` and `devices/` |
| neorc's backend | `--no-auth`; the identity core in `neorc-core` |
| neorc's interface | the `?embedded` switch; the profile at the bottom of its sidebar; `session.ts` and `SignIn.tsx` |

## What has no code yet

| part | nearest code |
|---|---|
| the contract and `compose_app` | each application's own FastAPI application |
| the SQLite stores | none; Robinauts raises `NotImplementedError` for local storage, and neorc has memory and PostgreSQL |
| the local sign-in | Robinauts' local user under `--dev-no-sign-in` |
| roles in Robinauts | none; neorc's routes each declare a permission |
| the node packages | none; neorc's interface package is private and exports nothing |
| the launcher and the window | `cli/lifecycle.py` in Robinauts, for processes alone |
| the image of the backend | none; the extra workers have images |
| the forwarding component | none |

## Moving the code

- The three repositories are Apache-2.0.
- A record of provenance goes in each repository, as Robinauts keeps one in
  `docs/legal/ip-clearance.md`.
- oneberth joins Robinauts' locked set and passes its licence gate.
- Neither application has a release. Stored credentials need no migration.

## Documents to update

| repository | document | what changes |
|---|---|---|
| neorc | `docs/specs/roles.md` | the roles become oneberth roles; tokens gain routes and a page |
| neorc | `docs/working-notes/sso-plan.md` | superseded by [identity.md](../specs/identity.md) |
| neorc | `README.md` | the token commands, `--no-auth`, and a stale line that says roles are for later |
| neorc | `contributing/js-dependencies.md` | the interface is a package too |
| neorc | `contributing/in-memory-first.md` | a route is declared in oneberth's contract |
| Robinauts | `docs/specs/sign-in.md`, `docs/architecture/device-pairing.md` | superseded by [identity.md](../specs/identity.md) |
| Robinauts | `docs/specs/core.md` | goal 6, "the system in one page", the planned container image |
| Robinauts | `docs/specs/frontend.md` | the panel, the tabs, the runtime dependencies, the budget |
| Robinauts | `docs/specs/operations.md`, `docs/deployment.md` | the shapes, the workers, SQLite |
| Robinauts | `docs/architecture/orchestration.md` | composed and forwarded; the frame goes away |
| Robinauts | `docs/architecture/rules.md` | where `oneberth` may be imported; FastAPI, Starlette and uvicorn leave the list |
| Robinauts | `docs/architecture/web.md` | the routes move under `/robinauts/` |
| Robinauts | `extra-workers/README.md` | who starts a worker, the networks |
