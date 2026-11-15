# Review of the specs

## The request

1. neorc and Robinauts duplicate code and depend on each other. Both follow one pattern
   that works in a cloud cluster, as a desktop application of processes, as a desktop
   application with some processes in Docker, and in a Chrome window without a navigation bar.
2. SSO, RBAC and API token management are in a single place, oneberth.
3. oneberth is a Python library and a node package that hold the reusable parts.
   It also holds reusable admin scripts.
4. oneberth alone imports FastAPI. Robinauts imports oneberth and gets FastAPI through it.
5. Each application returns its web application as a component, in a shape oneberth
   understands. oneberth composes them: `compose_app(apps=[robinauts, neorc])`.
6. neorc ships `neorc-core` and the standalone neorc application, which uses oneberth.
7. Robinauts ships a cloud application on PostgreSQL. Its interface embeds neorc's and
   oneberth's components and speaks to Robinauts' backend alone. The backend forwards
   requests to neorc's backend. The neorc instance has the same version, and may serve its
   own interface with its own sign-in.
8. Robinauts ships a desktop application on SQLite. Without a Docker worker, the whole
   application runs as processes. With one, the backend and the oneberth routes are served
   from a container, on a Docker network the other processes reach.
9. Some workers run in VMs, hold untrusted code, and reach only what they need of the core API.
10. Robinauts drops its copy of neorc's left panel. A rail in oneberth, 48 px wide, shows
    one icon per application and switches between them. The application draws everything else.
11. The dependencies are: `neorc-core` on nothing; neorc on oneberth; Robinauts on oneberth
    and on `neorc-core` or neorc.
12. All SSO, session handling and token issuing moves to oneberth.

## Verdict

The request is consistent in its direction and feasible.

- **The direction holds.** The dependencies form no cycle. The single copy of sign-in
  removes real duplication. The rule for Docker fixes a real problem of today's setup.
  One owner of the routes makes a permission per route a matter of structure.
- **Twelve points needed a decision.** The request left them open or stated them two ways.
  ["Decisions taken in the specs"](#decisions-taken-in-the-specs) lists each with its reason.
- **Seven questions stay open** (["Open questions"](#open-questions)).
- **Four pieces are most of the work**: oneberth's contract for routes, the SQLite stores,
  neorc's interface as components, and the launcher with its Docker shape.

## The code today

Read at neorc `26a30a0` and Robinauts `e2f276d`.

Robinauts' sign-in was written from neorc's design, and `docs/legal/ip-clearance.md` records it.
The two copies have the same shape and differ in these points:

| topic | neorc | Robinauts |
|---|---|---|
| users | no table; a principal is what its provider said | a `users` table |
| the allow list is checked | at sign-in | at sign-in and at every use, once a minute |
| roles | six fixed roles, a permission per route, tokens bound to a queue | none; an `admin` key is refused |
| tokens | named, with a role, created with the command line on the database, no expiry by default | per person, minted in the browser from a fresh session, 90 days |
| devices | none | pairing with a QR code and a number |
| the cross-site check by `Sec-Fetch-Site` | in the code | in the spec, absent from the code |
| a bearer and a cookie together | refused | accepted, bearer first |
| sign-in off | `--no-auth`: no roles, everything allowed | `--dev-no-sign-in`: one local user, loopback, a `Host` check |
| stores | memory, PostgreSQL | in process, PostgreSQL |
| the session in the browser | a query library | React's store hook |

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

How Robinauts uses neorc today:

- Robinauts pins `neorc[http,manager,postgres]`, `neorc-core` and `neorc-ui` to one commit.
- One file imports neorc: `orchestrator/adapters/neorc/embedded.py`.
- The manager is mounted at `/neorc` with no authentication. Robinauts allows it only with
  `--dev-no-sign-in`.
- The interface frames neorc's built interface in an `<iframe>`. It draws its own copy of
  neorc's navigation and its own form to start a run.
- Robinauts has no SQLite store, no image of its backend and no desktop packaging.
- Its Docker workers use `--network host`, which works on Linux alone.

What moves to oneberth:

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
| the security headers on the interface | `manager/_ui.py` | `web/headers.py` | web part |
| the session in the browser, the sign-in page | `session.ts`, `SignIn.tsx` | `session/`, `devices/` | node package |

The routes stay in each application, and are written again in oneberth's contract:
`manager/_routes.py` in neorc, `web/app.py` and `web/worker_api.py` in Robinauts.

What each application stops having:

| part | stops having |
|---|---|
| Robinauts' backend | the manager served without authentication, and the rule that refuses flows while sign-in is on; the rewrite of neorc's frame headers, `Framable`; `flows_url` in the answer of `GET /auth/session`; `--dev-no-sign-in`; the start of its own workers |
| Robinauts' interface | the Sessions and Flows tabs; its copy of neorc's navigation (`flows/FlowsSection.tsx`, `flows/orchestrator.ts`); the frame around neorc's interface (`flows/FlowsPage.tsx`); the profile block of its panel; `session/` and `devices/` |
| neorc's backend | `--no-auth`; the identity core in `neorc-core` |
| neorc's interface | the `?embedded` switch; the profile at the bottom of its sidebar; `session.ts` and `SignIn.tsx` |

## Findings on consistency

**C1. "A single place" and "a library" are two different things.**
A library runs inside each backend, and a cluster may have two backends.
The specs read "a single place" as one code base and one store per deployment
([identity.md](../specs/identity.md), "One store per deployment").
A person is then one user in both applications.

**C2. The request states two ways to serve neorc.**
Point 7 has Robinauts forward to neorc's backend. Point 5 composes both applications in one.
The specs keep both. The desktop composes: one process serves both applications.
The cluster forwards to neorc's manager, through a component of oneberth's.
Robinauts mounts neorc's manager by hand today, inside an adapter of 401 lines.
`compose_app` does the same for any set of components.

**C3. `neorc-core` has one dependency, and holds the identity core today.**
Its one runtime dependency is a YAML parser. It also holds the role table and the whole
identity core. The identity core moves out. The role table stays as plain data, and
`neorc-core` asks its decisions through a port. `neorc-core` then imports no oneberth.

**C4. Robinauts depends on neorc, the application.**
The request left the choice open. Robinauts composes neorc's manager into its backend, and
the manager's routes and stores are in `neorc`. `neorc-core` alone would bring the duplication back.

**C5. neorc ships a third thing.**
The request lists `neorc-core` and the standalone application. Robinauts embeds neorc's
components, and those need a node package ([shell.md](../specs/shell.md), "The neorc interface as a package").

**C6. Two sign-ins need one store.**
The request lets a person open Robinauts' URL or neorc's own. Each origin has its own
cookie. The two backends share one oneberth store, which makes the person one user with
one set of roles. Two separate stores would make two users.

**C7. The desktop has no sign-in today, and untrusted workers need one.**
Both applications run without credentials on one machine today. An untrusted worker beside
such a backend acts as the person. The specs sign the desktop's person in locally and
give every worker a token ([identity.md](../specs/identity.md), "Locally").

**C8. A backend in a container cannot start containers.**
Robinauts' server starts its workers itself today. The request moves the server into a
container when a Docker worker exists. The specs give the starting to a launcher on the
host, in both desktop shapes ([shapes.md](../specs/shapes.md), "The launcher").

**C9. FastAPI is declared once.**
An application that imports a package declares it. Importing FastAPI through oneberth alone
would break that. The strict rule removes the import from both applications, and
`oneberth[web]` alone declares FastAPI. A worker's image installs oneberth without that extra.

**C10. The interface is composed at build time.**
`compose_app` composes backends when a process starts. The interface is one bundle, built
by the host application with every component's interface inside. A composition has the
interface of the bundle it is given.

**C11. A component keeps its addresses.**
neorc's API is at the root of its origin today. A component is served under `/<name>/`,
alone too. neorc's clients already take a base address, and Robinauts' API moves from
`/api/` to `/robinauts/`.

**C12. The rail needs a place for the account.**
Each application draws the profile at the bottom of its own panel today. The rail holds one
account button and the theme toggle for all applications, and stays shown with one application too.

**C13. "The same version" needs a check.**
Nothing stops a cluster from running two versions. The forwarding component compares versions
and answers 503 for `/neorc/` while they differ ([neorc-in-robinauts.md](../specs/neorc-in-robinauts.md), "One version").
The desktop holds one version by construction.

**C14. Four current rules change.**
Robinauts' specs say these today, and each one changes:
"PostgreSQL is always required"; "one Python wheel" as the only deliverable;
the local mode "is not a way to deploy"; the interface's only runtime dependencies are React's.
["Documents to update"](#documents-to-update) lists the places.

## Findings on feasibility

**F1. "Only oneberth imports FastAPI" makes the contract a small web framework.**
This is the large part of oneberth. neorc declares 680 lines of routes on FastAPI today, and
Robinauts about 1,700. An application that may not import FastAPI needs everything from the contract.
[composition.md](../specs/composition.md), "What the contract covers", lists the needs found in the code:
checked values, the OpenAPI documents, streams, long polls, hidden routes, a page with its
own headers, and a limit on a body.
The work is feasible. neorc's routes are thin by rule: each parses a request and calls one method.
A softer rule is the fallback: oneberth composes, and an application still declares its
routes on FastAPI.

**F2. Three SQLite stores are new code.**
oneberth, neorc and Robinauts' controller each need one. Robinauts raises
`NotImplementedError` for local storage today, and neorc has memory and PostgreSQL alone.
neorc's ports have contract suites, which limit the work.
neorc tells waiting workers about a new task through PostgreSQL's notifications. SQLite has
none across processes. The desktop's manager runs inside the backend's process and notifies in memory.

**F3. neorc's interface is an application today, and has to become components.**
Its package is private, exports nothing and builds one page. Its stylesheet is global.
Its only switch for a host is `?embedded`. The work is a root component that takes the API's
address, prefixed class names, and peer dependencies.
Robinauts' bundle is 101.5 KB against a budget of 400 KB. neorc brings a query library and
two graph libraries. The budget is measured again, and neorc's code loads on first use.
neorc pins React 19.0.8 and Robinauts 19.3.1. The three repositories move React together.

**F4. Forwarding is feasible, with one limit to watch.**
The forwarding component passes long polls through. A browser allows six connections per
origin over HTTP/1.1, and a Robinauts tab already holds two. neorc's long poll makes three.
A hidden application stops its long polls ([shell.md](../specs/shell.md), "An application in the shell").

**F5. SQLite on a directory shared with a container needs a test.**
The request moves the backend into a container, and the data has to follow.
A host directory mounted into a container works on Linux. Docker Desktop on macOS passes
file operations through a virtual machine, and SQLite's locks and shared memory are the risk there.
One process opens the files, which removes most of it. A test on macOS comes before the
Docker shape is built. A Docker volume with a copy at the switch is the fallback.

**F6. The rule for Docker is sound, and it has costs.**
Today's `--network host` works on Linux alone, and the workers' own README says so.
A backend on a Docker network gives every container one address for it on every platform.
An internal network also gives untrusted workers no way out.
The costs are four: an image of the backend, which is only planned today; Docker running
before the application starts; a slower start; and host services reached through the gateway's name.

**F7. Today's worker routes are too wide for an untrusted worker.**
Robinauts' worker routes take the owner from the path. A worker learns an owner's id from
each turn it runs. With a valid secret it then lists and reads every session of that owner.
A worker started by the server also inherits the server's environment, the database URL included.
An untrusted worker gets narrower routes: the tasks it holds, and their sessions.

**F8. The window is feasible on Linux and macOS.**
Chrome's application mode needs a browser of the Chromium family on the machine.
A profile of the window's own lets the launcher watch the window's process.
The default browser is the fallback.

**F9. Moving the code is clean.**
The three repositories are Apache-2.0. A record of provenance goes in each, as Robinauts
keeps one today. oneberth joins Robinauts' locked set and passes its licence gate.
Neither application has a release. Stored credentials need no migration.

**F10. Roles are new work in Robinauts.**
Robinauts defers roles today. With oneberth, each Robinauts route declares a permission.
neorc's routes declare one already.

**F11. The packages have no registry yet.**
Robinauts builds neorc from a pinned commit today. The node packages follow the same way.
Install scripts are disabled in both projects. A node package ships its TypeScript
source, and the application's build compiles it.

**F12. The cluster needs workers the platform starts.**
The server starts every worker today and writes a secret on its standard input.
A workload in a cluster reads a token from a file. The token is a service token, created
ahead of time. neorc's tokens work this way already.
neorc runs one scheduler per deployment. That limit stays.

## Decisions taken in the specs

Each decision fills a gap in the request. Any of them can be overturned.

| | decision | why |
|---|---|---|
| D1 | oneberth is a library, with one store per deployment | C1, C6 |
| D2 | The desktop composes neorc's manager into Robinauts' backend; the cluster forwards to it | C2 |
| D3 | Robinauts depends on `neorc`; `neorc-core` keeps its role table as data | C3, C4 |
| D4 | neorc ships its interface as a node package too | C5 |
| D5 | A forwarded request is sent with the person's credential, and neorc decides the permission | neorc's route table stays in one place; no master key exists |
| D6 | The desktop signs its person in locally; the modes without credentials go away | C7 |
| D7 | A launcher on the host starts every component; workers hold service tokens | C8, F12 |
| D8 | A backend has a worker listener; untrusted workers reach it alone | point 9, F7 |
| D9 | The rail is always shown, and holds the account button and the theme toggle | C12 |
| D10 | The launcher and the window are part of oneberth | point 1 names them as the pattern |
| D11 | A component is served under `/<name>/`, alone and composed | C11 |
| D12 | The interface is one bundle, built by the host application | C10 |

## Open questions

**Q1. Do the modes without credentials go away?** D6 removes `--no-auth` and
`--dev-no-sign-in`. A developer then opens the printed URL once, and a script needs a token.
The alternative keeps them for development and forbids them beside an untrusted worker.

**Q2. Does the launcher start in oneberth?** Robinauts is its one user at first.
The launcher can start in Robinauts and move once neorc needs it.

**Q3. How does an untrusted worker reach a model?** It holds none of the operator's keys.
There are three ways. The worker uses the person's own credentials, as the Claude Code worker does.
The network lets it reach the model provider alone. Or the backend passes its model calls on.

**Q4. Which VMs, and by what path?** A local VM reaches the worker listener over a host-only
network. A VM elsewhere needs a tunnel or a relay, and the desktop accepts no inbound connection.

**Q5. What does closing the window do?** A turn runs in the background by design. Stopping
the application with its window ends running turns. Keeping it alive leaves processes
nobody sees.

**Q6. Where does the form that starts a run live?** Robinauts has its own form, with lists of
values for models, agents and repositories. neorc has forms of its own since, with fixed options.
One way keeps neorc's form and lets the host fill the lists.

**Q7. Whose conversations does a flow handler create?** They are the developer's today,
without sign-in. With sign-in the handler's token decides: the token of the person who
started the run, or a service of its own.

Smaller points, with no decision needed yet:

- Windows is not a target of Robinauts today. A desktop application makes the question larger.
- The package names, and the registries, are proposals.
- Robinauts' docs name `open-shipyard/neorc`. The repositories read here are under `the-guish`.
- A desktop that signs in through a company's provider is not specified.
- Three limits of today's sign-in stay: a token has all of its person's roles; nobody is
  signed out at the provider; sign-in has no rate limit of its own.

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

## Order of work

[plan.md](plan.md) holds the steps of this version.
