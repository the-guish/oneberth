# Oneberth

Oneberth hosts web apps behind one sign-in. It draws an icon rail, signs
people in, holds their roles and tokens, and frames the apps. It has no app
of its own.

The same apps run on a company's cluster and on one person's desktop.

The specs are in [docs/specs/core/](docs/specs/core/README.md).

## Goals

### 1. One place for sign-in, roles and tokens

- Oneberth signs people in through the company's identity provider. It
  stores who holds which role in which app. It issues and revokes API
  tokens.
- An app keeps no sign-in code, no session and no token table. It learns who
  is asking from Oneberth.

### 2. The same apps in every setup

- A cloud cluster runs the apps as its own services.
- A desktop runs them as OS processes of one person.
- A desktop runs some of those processes in Docker containers.
- The desktop window is the installed Chrome or Chromium, without a
  navigation bar.
- An app is written once. It runs unchanged in all of these.

### 3. Apps in any language

- An app's server is written in any language. An app's pages are shown in a
  frame.
- Every contract between Oneberth and an app is plain HTTP, JSON, a signed
  token or `postMessage`.

### 4. Secure, and fit for a company

- Sign-in is through Google and Okta, over OpenID Connect.
- Every request to an app carries a signed statement of who is asking. The
  app checks the signature.
- A process is trusted for the credential it holds. Its place on the network
  gives it no rights.

### 5. Nothing leaves the host

- Oneberth sends no telemetry and loads nothing from a CDN or a hosted
  service.
- Oneberth's only outbound traffic goes to the identity providers, at
  sign-in.

### 6. Apache-2.0 without restrictions

- Everything here is Apache-2.0.
- Every dependency is scanned, transitively, against a licence allowlist. A
  dependency that fails the scan breaks the build.

### 7. Compose over build

- Oneberth uses an existing component where one fits. A cluster's own
  tools start and restart the processes there.
- Oneberth builds the parts that are missing.

### 8. A small footprint

- A cluster adds one service, the shell, and one database for it.
- A desktop adds one launcher and one shell process. Docker is needed only
  for a process that ships as an image.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
