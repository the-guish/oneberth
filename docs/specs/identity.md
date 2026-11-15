# Identity: sign-in, sessions, tokens and roles

oneberth answers two questions for a backend: who is asking, and may that principal do this.

## Words

- **Identity**: what a provider says about a person at a sign-in: provider, subject, name,
  verified email, hosted domain and groups.
- **User**: a stored person, keyed by provider and subject.
- **Service**: a program with a token of its own, such as a worker, a scheduler or a CI job.
- **Principal**: who is asking. A principal is a user or a service.
- **Credential**: a secret that names a principal.
- **Permission**: one operation of one application, such as `neorc/runs:start`.
- **Role**: a named set of permissions, declared by an application.
- **Grant**: a role given to a principal, for every resource or for one.
- **Store**: where oneberth keeps users, credentials and grants.
- **Deployment**: the backends that share one store.

## One store per deployment

- A deployment has one store. Every backend of the deployment opens it.
- A person is one user in every application of the deployment.
- The store is a PostgreSQL schema named `oneberth`, or a SQLite file named `oneberth.db`.
  A third store keeps everything in memory, for tests.
- oneberth creates its own tables. The setup is safe to repeat.
- The store holds its schema version. A backend built for another version refuses to start.
- The three stores pass one contract suite.

## Sign-in

A deployment signs people in through identity providers or locally.
The two modes exclude each other.

### Through identity providers

This is the cluster's mode.

- Google and Okta sign people in over OpenID Connect. One generic client on `httpx` serves both.
- The flow is the authorization code flow with `state`, `nonce` and PKCE (S256).
- Discovery happens at the first sign-in, not at start-up. A success is cached.
- The ID token arrives from the token endpoint over TLS. Its claims are checked and its
  signature is left unverified, which keeps oneberth free of a JWT or crypto dependency.
- An allow list decides who may sign in. Each entry names a provider and one matcher:
  `everyone`, `subject`, `email`, `email_domain`, `hosted_domain` or `group`.
- Google gets the stricter matchers. `everyone` and `email_domain` are refused for it.
- A configuration with providers and an empty allow list fails at start-up.

### Locally

This is the desktop's mode, and the mode for development.

- The deployment has one user, the person at the machine. That user is a real row under a
  reserved key that no provider can produce.
- The launcher signs that person in. It makes a launch secret and writes it on the
  backend's standard input. It then asks the backend for a ticket and opens the window at
  `/auth/local?ticket=…`. The backend swaps the ticket for a session cookie.
- A ticket works once, within one minute.
- The front listener accepts requests whose `Host` is `localhost` or an IP address.
  This defeats DNS rebinding.
- A start command without a launcher signs the person in itself. It prints the URL with the ticket.
- Development uses the local mode too. Every request there has an identity, and no code is
  special to development.
- The local mode asks the person for no sign-in. No remote site takes part.

## Users

- The first sign-in creates the user. Later sign-ins refresh the name, verified email,
  hosted domain and groups.
- The allow list is checked again when a credential is used, at most once a minute.
  A user it refuses loses every credential.
- A sign-in refused by the allow list ends every credential of that identity.

## Credentials

Every secret is 256 random bits. The store keeps its SHA-256.

| kind | names | made by | lives | sent as |
|---|---|---|---|---|
| session | a user | a sign-in | `session_hours`, 12 by default | a cookie |
| personal token | a user | that user, in the browser | 90 days | a bearer |
| device session | a user | a pairing that user approved in the browser | `device_days`, 30 by default | a bearer |
| service token | a service | an admin, the operator or the launcher | set when created | a bearer |

- A secret starts with a prefix that names its kind. The prefix picks where a bearer is looked up.
- A session has a fixed life and no renewal.
- A personal token and a device session have the roles of their user.
- A service token has one role and, when the role needs one, one resource.
- **A person's credentials are minted from that person's browser session.** The session must
  be younger than ten minutes. A bearer that asks is answered 403.
- A service token is minted by a principal with `oneberth/tokens:manage`: an admin in the
  interface, or the launcher. The operator also creates one with the command line.
- A token the launcher mints ends when the application stops.
- Taking access away needs no fresh sign-in.

## Device pairing

- A phone is linked from the browser. The browser shows a QR code, and the phone scans it.
- The code names the server. Nobody types an address into a phone.
- The phone presents the code and gets a secret and a six-digit number. The secret does
  nothing until the pairing is approved.
- The person types the number into the browser. The secret then becomes the device's session.
- A code works once, within two minutes.
- The person sees every linked device in the browser and removes any of them there.

## Roles

- An application declares its permissions and roles as data when its backend starts.
  A name starts with the application's name: `neorc/runs:start`, `neorc/worker`.
- Roles are fixed per release. Nobody edits a role in a deployment.
- A role says whether its grants need a resource. `neorc/worker` needs a queue, and
  `robinauts/worker` needs a worker name.
- Every route declares the permission it needs. The contract has no route without one
  ([composition.md](composition.md), "A component").
- oneberth checks the permission and the resource. The application checks ownership, such as
  whose conversation this is.

The roles at the start:

| role | given to | resource |
|---|---|---|
| `neorc/user` | every person who may sign in | none |
| `neorc/worker`, `neorc/responder` | a service token | one queue |
| `neorc/scheduler`, `neorc/ci`, `neorc/external-trigger` | a service token | none |
| `robinauts/user` | every person who may sign in | none |
| `robinauts/admin` | the people the configuration names | none |
| `robinauts/worker` | a service token | one worker name |
| `oneberth/admin` | the people the configuration names | none |
| `oneberth/launcher` | the launch secret | none |

- An allow entry admits a person and gives the default role of each application.
- A `[[grant]]` entry gives one more role, with the same matchers as the allow list.
- A person's roles are decided at sign-in and checked again with the allow list.
- The local user holds every role a person can hold.

`neorc-core` holds neorc's permission table as plain data and asks its decisions through a port.
The `neorc` application registers the table with oneberth and gives the port its answer.

## Checks on a request

- A write is `application/json`. Any other content type is refused.
- A cross-site write is refused, by `Sec-Fetch-Site`.
- A write with the session cookie has `Origin` equal to the backend's `public_url`.
- A write with a bearer skips the `Origin` check.
- A request with both a bearer and a cookie is refused.
- A backend is served at the root of its origin. `public_url` has no path.
- The session cookie is `__Host-oneberth_session`: `HttpOnly`, `SameSite=Lax`, `Secure`.
  A loopback origin over `http` drops the prefix and `Secure`, and ends the name with the
  port. Browsers share cookies across the ports of one host.

## Routes

A composition serves these under `/auth`.

| route | purpose |
|---|---|
| `GET /auth/session` | who is asking, their roles, the providers; never a 401 |
| `GET /auth/login/{provider}`, `GET /auth/callback/{provider}` | a sign-in through a provider |
| `GET /auth/local` | swaps a ticket for a session, in the local mode |
| `POST /auth/logout` | ends the session, or the device that asks |
| `POST`, `GET /auth/tokens`, `DELETE /auth/tokens/{id}` | personal tokens |
| `/auth/pairings…`, `/auth/devices…` | device pairing and the linked devices |
| `/auth/services…` | service tokens, for a principal with `oneberth/tokens:manage` |
| `POST /auth/tickets` | a ticket, for the launch secret alone |

## Between two backends

- The backends of a deployment trust the same store.
- A backend that forwards a person's request sends that person's credential as a bearer.
  The receiving backend finds it in the store and decides the permission itself.
- A forwarded session counts as a bearer. It mints and removes nothing.
- A backend's own requests use a service token of its own.

## Configuration

One TOML file holds the sign-in configuration of a deployment, and `ONEBERTH_CONFIG` names it.
Every backend reads the same file and finds its `public_url` under its own name.
A secret is given as the name of an environment variable. Unknown keys are errors.

```toml
session_hours = 12
device_days = 30

[apps.robinauts]
public_url = "https://robinauts.example.com"

[apps.neorc]
public_url = "https://neorc.example.com"

[providers.okta]
title = "Okta"
issuer = "https://example.okta.com/oauth2/default"
client_id = "..."
client_secret_env = "ONEBERTH_OKTA_SECRET"
scopes = ["openid", "email", "profile", "groups"]
groups_claim = "groups"

[[allow]]
provider = "okta"
group = "platform-users"

[[grant]]
provider = "okta"
group = "platform-admins"
roles = ["robinauts/admin", "oneberth/admin"]
```

Each provider registers one redirect URI per application:
`{public_url}/auth/callback/{provider}`.

## Admin scripts

oneberth holds the admin scripts both applications reuse.

- `oneberth store init` creates the store's tables.
- `oneberth tokens create|list|revoke` manages service tokens.
- `oneberth sessions clear` ends every session.
- `oneberth devices list|end` lists and ends devices.
- Each application offers the same scripts under its own name, such as `neorc tokens create`.
- The scripts open the store on PostgreSQL. The desktop's scripts ask the backend, which
  alone opens the SQLite files.

## The Python library

| part | holds | third-party code |
|---|---|---|
| core | identities, users, credentials, the allow list, roles; the store port; the memory store; the contract suite | none |
| contract | the shapes of a component and of a route | none |
| providers | the OpenID Connect client | `httpx` |
| configuration | the TOML reader | none |
| PostgreSQL store | the store on PostgreSQL | `asyncpg` |
| SQLite store | the store on SQLite | none |
| web | `compose_app`, the `/auth` routes, who is asking, the checks on a request, the security headers, the server | FastAPI, Starlette, uvicorn |
| admin scripts | the store, token, session and device scripts | none |
| launcher | [shapes.md](shapes.md), "The launcher" | none |

- A base install brings no third-party code. Each adapter is an extra.
- The logic lives in the core and is tested in memory. An adapter stores or moves data.

## Details likely to change

- The prefixes: `ob_ses_`, `ob_pat_`, `ob_dev_`, `ob_svc_`.
- The cookie names, the route paths, the names of the configuration keys.
- The separator in a permission's name.

## Open

- A token with fewer roles than its person.
- Sign-out at the identity provider.
- A limit on the rate of sign-ins.
- Sign-in through a provider on the desktop.
- How the local user is authenticated. The ticket of "Locally" is the proposal.
