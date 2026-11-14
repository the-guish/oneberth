# Identity: sign-in, roles, tokens

Oneberth signs people in, keeps their sessions, decides their roles in each
app and issues tokens. An app trusts only what the shell hands it.

The sign-in is Robinauts' (`docs/specs/sign-in.md` there), which is neorc's
design. Its code moves here.

## Providers

- Google and Okta, over OpenID Connect. One generic client serves both.
- The client is written on `httpx`. There is no OIDC, JWT or crypto
  dependency.
- Authorization code flow with `state`, `nonce` and PKCE (S256).
- Discovery at the first sign-in; the issuer must match the configured one.
- The ID token comes from the token endpoint over TLS, so its signature is
  not verified (OIDC Core 3.1.3.7). Its claims are: `iss`, `aud`, `azp`,
  `exp` and `iat` with 60 s of skew, `nonce`, `sub`.
- Google's `email_verified` is trusted only with `hd`, or for `gmail.com`.

## Who may sign in

- The configuration's allow list. Each entry names a provider and one
  matcher: `everyone` (not for Google), `subject`, `email`, `email_domain`
  (not for Google), `hosted_domain` (Google only), `group`.
- With providers and no allow entry, the start is refused.
- The allow list is checked at sign-in, and again on every use of a
  credential, at most once a minute. A person taken out of it loses every
  credential within a minute.

## Users

- The first sign-in creates a user, keyed by `(provider, subject)`. Later
  sign-ins refresh the name, the verified email, the hosted domain and the
  groups.
- A user has a stable id, a UUID. Apps key their own records by it.
- An app keeps its own profile of a user if it needs one. An app learns of a
  user from the first request that names the user.

## Sessions

- A session is a row. The cookie holds a random 256-bit secret; the row
  holds its SHA-256.
- Cookie: `__Host-oneberth_session`, `HttpOnly`, `SameSite=Lax`, `Secure`,
  `Path=/`. On a loopback `http` origin the prefix and `Secure` are left out.
- Fixed lifetime, `session_hours`, 12 by default. Not renewed. The
  provider's tokens are discarded after sign-in.
- Sign-out deletes the row and clears the cookie.

## Request protection

- No CSRF token. Every write must be `application/json` (or a WebSocket
  upgrade) and must not be cross-site (`Sec-Fetch-Site`). A
  cookie-authenticated write must carry `Origin` equal to `public_url`.
- These checks run in the shell, for every path, apps included.

## Roles and grants

- Each app declares its roles and their permissions in its manifest
  ([apps.md](apps.md)). The table is fixed in the app.
- A **grant** gives a user, or a service token, one role of one app,
  optionally on one resource: `neorc:responder@queue:approvals`. The
  resource is a string the app interprets.
- The shell has its own app id, `oneberth`, with two roles: `admin` (the
  admin screen, every grant, every service token) and `user`.
- People's grants are made on the admin screen and stored in the database.
- **The first admins** are named in the configuration, with the allow list's
  matchers. They are admins whatever the database says, so the file always
  gets an operator back in.
- An app's `default` role, if it declares one, is held by every signed-in
  person without a grant.
- An app is listed in the rail to a person only if they hold a role of it.
- The shell refuses a request to `/apps/<id>/` from a person with no role of
  that app (403). Every finer check is the app's: it reads the roles and
  decides.

## The principal an app receives

The same fields, in process and out of process:

| field | meaning |
|---|---|
| `sub` | the user's id, or the service token's id |
| `kind` | `person`, `service` or `local` |
| `name`, `email` | a person's, as the provider said |
| `roles` | this app's roles: `["user", "responder@queue:approvals"]` |
| `via` | `session`, `personal-token`, `service-token` or `local` |
| `auth_time` | when the person signed in, for "a sign-in younger than ten minutes" |

- In process, the shell puts it in the ASGI scope, under
  `scope["state"]["oneberth.principal"]`, as a frozen value of
  `oneberth-core`.
- Out of process, it travels as the identity token.

## The identity token

What an out-of-process app receives on every request it is forwarded.

- A JWT, signed with HS256, in the header `Oneberth-Identity`.
- Signed with a secret of that app's alone, made by the shell at its first
  start and kept in the database. One app's secret cannot forge another's
  token.
- Claims: `iss` = `public_url`, `aud` = the app's id, `iat`, `exp` = `iat`
  + 60 s, `jti`, and the principal's fields above.
- The shell signs it with the standard library (`hmac`, `hashlib`,
  `base64`): HS256 is HMAC-SHA256.
- The app checks `alg` is `HS256`, the signature, `aud`, `iss` and `exp`, and
  trusts nothing else in the request about who is asking.
- The shell removes any `Oneberth-Identity` header a client sent.
- The app's web process listens on loopback only when it is an OS process.
  In a container it is reached by its name on its app's Docker network,
  and publishes no port.

## API tokens

Two kinds. A secret starts with its kind's prefix, which picks the table it
is looked up in and lets a secret scanner recognise it.

| | personal | service |
|---|---|---|
| prefix | `obp_` | `obs_` |
| acts as | the person who minted it, with their grants | itself, with its one grant |
| minted by | the person, from the browser, with a sign-in younger than ten minutes | an admin on the admin screen, or the shell for a process it starts |
| lifetime | 90 days, not renewed | admin-minted: chosen, at most a year; process: the life of the process |
| shown | once, when minted | once; a process gets it as a file |
| stored | SHA-256 | SHA-256 |
| revoked by | its owner, from the browser; an admin | an admin; the shell, when the process stops |

- Sent as `Authorization: Bearer <secret>`. A request with a bearer and a
  session cookie is refused.
- A bearer is not a cookie: a write with one is not held to the `Origin`
  check.
- A personal token reaches every app its owner may use. Scopes that narrow
  it are planned.
- A service token's grant is checked like a person's: the app sees its role
  in the principal.

## Desktop

- No sign-in. Every request is one local user, a real row under the reserved
  key `("!local", "desktop")`, which no provider can name.
- That user holds every role of every app. The admin screen is hidden.
- The shell's port A is on loopback only. It checks that `Host` is exactly
  `127.0.0.1:<A>` or `localhost:<A>`, against DNS rebinding.
- The local user exists only on port A, which no app container can reach.
  Port B, the containers' port, accepts service tokens only, on desktop as on
  the web
  ([processes.md](processes.md), "The shell's ports").
- Personal tokens can be minted for the local user, for scripts on the same
  machine.
- A database kept from desktop and opened in web mode hands nobody the local
  account: a session or token naming it is refused there.

## Routes

| route | purpose |
|---|---|
| `GET /auth/session` | who is signed in, their apps and roles, the providers; never a 401 |
| `GET /auth/login/{provider}` | start a sign-in |
| `GET /auth/callback/{provider}` | finish it |
| `POST /auth/logout` | sign out |
| `POST /auth/tokens` | mint a personal token |
| `GET /auth/tokens` | the person's personal tokens, without secrets |
| `DELETE /auth/tokens/{id}` | revoke one |
| `/admin/grants`, `/admin/service-tokens` | the admin screen's API; `oneberth:admin` only |

## Audit

- Sign-ins, refusals, sign-outs, grants made and taken back, and tokens
  minted and revoked are written to an audit log, with who did it.

## Linking phones

- A phone links to a person's account by QR code and number matching, as in
  Robinauts (`docs/architecture/device-pairing.md` there). The design and its
  code move here, for every app, in the first milestone.
- A linked phone holds a device session (`obd_`), sent as a bearer. It acts as
  its person, with their grants, in every app.
- "Linked devices" in the profile menu lists and removes them.

## Planned

- Optional sign-in on desktop.
- Scopes on personal tokens.

## Open

- Whether an admin may grant on a resource the app has not listed, or the
  app offers its resources to the admin screen.
- Sign-out at the identity provider.
