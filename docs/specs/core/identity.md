# Identity: sign-in, roles, tokens

The shell signs people in, keeps their sessions, stores their roles in each
app and issues tokens. An app trusts the identity token alone.

## Providers

- Google and Okta, over OpenID Connect. One generic client serves both.
- The sign-in client is written on `httpx`.
- Authorization code flow with `state`, `nonce` and PKCE (S256).
- Discovery happens at the first sign-in, not at start-up. The issuer must
  match the configured one.
- The ID token comes from the token endpoint over TLS. Its claims are
  checked: `iss`, `aud`, `azp`, `exp` and `iat` with 60 s of skew, `nonce`,
  `sub`.
- Google's `email_verified` is trusted only with `hd`, or for `gmail.com`.

## Who may sign in

- The configuration holds an allow list. Each entry names a provider and one
  matcher: `everyone` (Okta only), `subject`, `email`, `email_domain` (Okta
  only), `hosted_domain` (Google only), `group`.
- A configuration with providers and no allow entry refuses the start.
- The allow list is checked at sign-in. It is checked again on every use of
  a credential, at most once a minute.
- A person's groups are read at sign-in. A person removed from a group at
  the provider keeps their access until their session ends
  ("Leavers" below).

## Users

- The first sign-in creates a user, keyed by `(provider, subject)`. Later
  sign-ins refresh the name, the verified email, the hosted domain and the
  groups.
- A user has a stable id, a UUID. Apps key their own records by it.
- An app learns of a user from the first request that names the user.

## Sessions

- A session is a row. The cookie holds a random 256-bit secret. The row
  holds its SHA-256.
- Cookie: `__Host-oneberth_session`, `HttpOnly`, `SameSite=Lax`, `Secure`,
  `Path=/`. On a loopback `http` origin the prefix and `Secure` are left
  out.
- A session lasts `session_hours`, 12 by default, and is not renewed. The
  desktop's session lasts the launch.
- Sign-out deletes the row and clears the cookie.

## Roles and grants

- Each app declares its roles in its manifest ([apps.md](apps.md)).
- A **grant** gives a user, or a service token, one role of one app,
  optionally on one resource: `neorc:responder@queue:approvals`. The
  resource is a string the app interprets.
- The shell has its own app id, `oneberth`, with two roles: `admin` and
  `user`. An admin sees the admin screen and manages every grant and every
  service token.
- People's grants are made on the admin screen and stored in the shell's
  database.
- **The first admins** are named in the configuration, with the allow list's
  matchers. They are admins whatever the database says.
- An app's `default` role is held by every signed-in person.
- The rail lists an app to a person who holds a role of it.
- **The shell checks the first question**: does this person hold any role of
  this app? A person with none gets 403.
- **The app checks the rest.** The app reads the roles from the identity
  token and decides what each may do.

## The identity token

The identity token is what an app receives with every request. It says who
is asking and which roles they hold in that app.

- A JWT signed with ES256.
- The shell sends it in the header `Oneberth-Identity`. A process that calls
  an app directly sends it as `Authorization: Bearer`. An app accepts both.

| claim | meaning |
|---|---|
| `iss` | the origin people use, `public_url` |
| `aud` | the app's id |
| `iat`, `exp` | issued at; expiry |
| `jti` | a random id |
| `sub` | the user's id, or the service token's id |
| `kind` | `person`, `service` or `local` |
| `name`, `email` | a person's, as the provider said |
| `roles` | this app's roles: `["user", "responder@queue:approvals"]` |
| `via` | `session`, `personal-token`, `device`, `service-token` or `local` |
| `auth_time` | when the person signed in |

- **Lifetime.** A token the shell adds to a forwarded request lasts 60
  seconds. A token from an exchange lasts 5 minutes.
- **The app's check.** The app checks that `alg` is `ES256`, then the
  signature, `iss`, `aud` and `exp`. It reads who is asking from the token
  alone.
- **Keys.** The shell makes a P-256 key pair at its first start and keeps it
  in its database. One replica makes it, under a database lock. The public
  keys are served at `GET /auth/keys`, as a JWK set, without a credential.
- **Fetching keys.** An app fetches the set at `ONEBERTH_KEYS_URL` and keeps
  it in memory. It replaces the set once an hour. It also fetches when a
  token names a `kid` it does not hold, at most once a minute.
- **Rotation.** `oneberth keys rotate` adds a new key to the set. Every
  replica reads the keys again once a minute. A replica signs with the new
  key 10 minutes after it was added. The old key stays in the set for 24
  hours.
- **Dependency.** Signing and checking ES256 needs a cryptography library.
  The shell uses `cryptography`. A Python app uses it too, through
  `oneberth-core`.

## API tokens

There are three kinds. A secret starts with its kind's prefix, which lets a
secret scanner recognise it.

| | personal | service | device |
|---|---|---|---|
| prefix | `obp_` | `obs_` | `obd_` |
| acts as | the person who minted it, with their grants | itself, with its one grant | the person who linked the phone |
| minted by | the person, in the browser, after a fresh sign-in | an admin, on the admin screen or with `oneberth tokens create`; the launcher, for a process it starts | linking a phone |
| lifetime | 90 days | chosen, at most a year; a launcher's token lasts one launch | 30 days |
| shown | once | once; a process gets it as a file | once, to the phone |
| stored | SHA-256 | SHA-256 | SHA-256 |
| revoked by | its owner; an admin | an admin; the launcher, at the next start | its owner; an admin |

- A token is sent to the shell as `Authorization: Bearer <secret>`. The
  shell turns it into an identity token, as it does for a session.
- A request with a bearer and a session cookie is refused.
- A personal token reaches every app its owner may use.
- A service token holds one role of one app, with an optional resource.

## Exchange

A process inside the deployment calls an app directly. It first exchanges
its token for an identity token.

- `POST /auth/exchange`, with the token as bearer and `{"app": "<id>"}` as
  body.
- The answer is `{"token": "<identity token>", "expires_at": "<RFC 3339
  time>"}`.
- An error is `{"error": "<code>", "message": "<text>"}`. The codes are
  `invalid_token` (401), `no_role` (403) and `unknown_app` (404).
- The token file holds the secret alone, on one line. The process reads the
  file at each exchange. A rotated secret then needs no restart.
- The process keeps the identity token until shortly before its expiry, then
  exchanges again.
- A background process exchanges for its own app. An app that calls another
  app holds a service token with a role there ([apps.md](apps.md), "Calls to
  other apps").

## Revocation

- An ended session, a revoked token or a withdrawn grant stops working
  within two minutes through the shell: up to 60 seconds in the shell's
  memory, then up to 60 seconds of the last identity token.
- An identity token from an exchange works until it expires, at most 5
  minutes later.
- The shell closes a forwarded stream or WebSocket when its credential ends.
  It checks each open one once a minute.
- An app ends a stream of a direct call when the call's identity token
  expires. The caller connects again with a new token.

## Leavers

- **Disable a person.** An admin disables a person on the admin screen. The
  shell deletes every session and token of theirs and refuses their sign-in.
- **Tokens need a recent sign-in.** A personal token or a device token works
  while its owner signed in within `reauth_days`, 30 by default. A person
  removed at the provider cannot sign in, and their tokens stop.
- **Device tokens expire.** A device token lasts 30 days. The phone links
  again after that.

## Fresh sign-in

- The admin routes and minting a personal token need a fresh sign-in at the
  provider.
- The shell sends the person to the provider with `prompt=login` and
  `max_age=0`. It checks that the ID token's `auth_time` is under ten
  minutes old.
- A session's age alone does not count. A script on the page cannot make a
  fresh sign-in without the person typing their credentials.
- On a desktop the local session counts as fresh.

## Request protection

- The shell checks `Host` and `Origin` on every request that carries a
  cookie ([gateway.md](gateway.md), "Checks").
- A bearer is exempt from the `Origin` check.

## Desktop

- A desktop has no sign-in. One local user exists, a real row under the
  reserved key `("!local", "desktop")`.
- The local user holds every role of every app. The admin screen is hidden.
- **The window signs in with a ticket.** The launcher writes a single-use
  ticket before it opens the window. The shell exchanges the ticket for a
  session cookie ([runtimes.md](runtimes.md), "The window").
- The local session has no expiry. The launcher deletes it at the next
  start.
- Every request needs that session or a token, as on a server. A process on
  the same machine holds neither by default.
- The shell listens on loopback. A request with the cookie must carry the
  `Host` `127.0.0.1:<port>` exactly.
- Personal tokens can be minted for the local user, for scripts on the same
  machine.
- A server refuses a session or a token that names the local user.

## Linking phones

- A phone links to a person's account by QR code and number matching. The
  design and its code come from Robinauts.
- A linked phone holds a device token, sent as a bearer. It acts as its
  person, with their grants, in every app.
- "Linked devices" in the profile menu lists and removes them.
- Linking is part of the first milestone. Its routes and rules get a
  document of their own, in a later pull request.

## Routes

| route | purpose |
|---|---|
| `GET /auth/session` | who is signed in, their apps and roles, the providers |
| `GET /auth/login/{provider}` | start a sign-in |
| `GET /auth/callback/{provider}` | finish it |
| `POST /auth/logout` | sign out |
| `GET /auth/keys` | the public keys, as a JWK set |
| `POST /auth/exchange` | exchange a token for an identity token |
| `GET /auth/launch` | desktop: exchange the window's ticket for the local session |
| `POST /auth/tokens` | mint a personal token |
| `GET /auth/tokens` | the person's personal tokens, without secrets |
| `DELETE /auth/tokens/{id}` | revoke one |
| `/admin/grants`, `/admin/service-tokens`, `/admin/people` | the admin screen's API, for `oneberth:admin` |

- `/admin/` and minting a personal token accept a session with a fresh
  sign-in. A bearer is refused there.

## Audit

- Sign-ins, refusals, sign-outs, grants made and taken back, and tokens
  minted and revoked are written to an audit log, with who did it.

## Planned

- Optional sign-in on desktop.
- Scopes on personal tokens.
- A call on behalf of a person: an app exchanges the person's identity token
  for one that names another app.

## Open

- Whether an admin may grant on a resource the app has not listed, or the
  app offers its resources to the admin screen.
- Sign-out at the identity provider.
