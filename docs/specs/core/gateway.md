# The gateway

The gateway is the part of the shell that receives every browser request to
an app. It checks the credential, adds the identity token and forwards the
request.

## One origin

- The shell and every app share one origin, `public_url`. Each app lives
  under `/apps/<id>/`.
- An app's frame is same-origin with the shell's page.
- One hostname and one certificate serve everything.

## Checks

The gateway runs these checks on every request, in this order.

1. **Host.** `Host` must match `public_url`. On a desktop it must be exactly
   `127.0.0.1:<port>` or `localhost:<port>`.
2. **Credential.** The request carries a session cookie or a bearer token. A
   request with both is refused.
3. **Origin.** A write with a cookie must carry `Origin` equal to
   `public_url`, and a `Sec-Fetch-Site` of `same-origin` when the browser
   sends one. A WebSocket upgrade with a cookie must carry the same
   `Origin`. A write may have any content type.
4. **Who.** The gateway resolves the credential to a principal
   ([identity.md](identity.md)). It reads the session or token and the
   principal's grants in the app.
5. **Any role.** A principal with no role of the app gets 403.

- The gateway keeps the answer of steps 4 and 5 in memory for up to 60
  seconds, per credential and app.
- A request to a path under the app's `public` list skips steps 2 to 5.

## Forwarding

- The gateway sends the request to the app's address: a loopback port on a
  desktop, the configured `url` on a server.
- **Path.** The gateway removes the `/apps/<id>` prefix. The app receives
  `/tasks/42/complete` for `/apps/neorc/tasks/42/complete`.
- **Headers added.** `Oneberth-Identity` holds the identity token.
  `X-Forwarded-Prefix` holds `/apps/<id>`. `X-Forwarded-Host` and
  `X-Forwarded-Proto` hold the public origin's.
- **Headers removed.** The gateway removes `Cookie`, `Authorization` and any
  incoming `Oneberth-Identity`. An app never sees a session secret or an API
  token.
- **Public paths.** A request to a public path is forwarded without
  `Oneberth-Identity`.
- **Bodies.** The gateway streams request and response bodies. It buffers
  neither.
- **Streams.** Server-sent events, long polls and WebSockets are forwarded.
  A WebSocket gets its identity token at the upgrade.

## Answers

- The gateway removes `Set-Cookie`, `Service-Worker-Allowed` and
  `Clear-Site-Data` from an app's answer.
- The gateway adds `X-Content-Type-Options: nosniff`.
- The gateway adds `Content-Security-Policy: frame-ancestors 'self'` to an
  answer that sets no policy.

| case | answer |
|---|---|
| no credential, a page | the shell's sign-in page |
| no credential, an API call | 401 |
| no role of the app | 403 |
| the app is not enabled | 404 |
| the app does not answer | 503 |

## What the gateway leaves to the app

- The app checks the identity token on every request. A caller that reaches
  the app's port directly, without a token, gets 401 from the app.
- The app decides what each role may do.
- The app checks the sender of a request to a public path.

## Direct calls

- A process inside the deployment may call an app directly, with an
  identity token from an exchange ([identity.md](identity.md), "Exchange").
- A direct call skips the gateway. The app's own check is the same.

## Scaling

- The gateway holds no state of its own. Sessions, tokens and grants are in
  the shell's database.
- A cluster runs several shell replicas behind its load balancer. Any
  replica serves any request.

## Planned

- The cluster's own proxy forwards, and asks the shell for the identity
  token with a small request per call. Apps see the same token either way.

## Open

- The library for the WebSocket relay.
- Limits the gateway sets: body size, idle time of a stream.
- Whether the gateway caps the life of a stream.
