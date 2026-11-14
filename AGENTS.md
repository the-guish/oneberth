# For coding agents working in this repository

This repository is scaffolding. It holds the licence, the contribution rules
and the supply-chain gates, and no product code yet. Do not add sign-in, a
shell UI or the protocol unless the task asks for it.

Read these before you change anything:

- [CONTRIBUTING.md](CONTRIBUTING.md): the layout, the checks, the rules.
- [DEPENDENCIES.md](DEPENDENCIES.md): the licence policy the gates read.
- [docs/specs/open-source.md](docs/specs/open-source.md): why the rules exist.
- [docs/contributing/js-dependencies.md](docs/contributing/js-dependencies.md):
  before you touch anything under `ts/`.

Every commit carries a DCO sign-off. Commit with `git commit -s`, under a real
name.

<!-- REUSE-IgnoreStart -->
Every file carries the SPDX header: `SPDX-License-Identifier: Apache-2.0` and
`Copyright The Oneberth Authors`, in the file's comment syntax. A file that
cannot carry one goes in [REUSE.toml](REUSE.toml).
<!-- REUSE-IgnoreEnd -->

A dependency change is a pull request of its own. Do not add, remove or bump
a package as part of another change.

The cooldown is ten days, for a first pin as for a bump. Read the publish
dates (`npm view <pkg> time --json`, or PyPI's upload times), pin the newest
version at least ten days old, and say in the pull request which dates you
read. No check can catch this for you.

The packages have no runtime dependencies. Keep it that way unless the task
is that dependency change.

Installs are `npm ci` and `uv sync`. Do not run `npm install`; `save-exact`
and `ignore-scripts` stay on in `.npmrc`. Commit `uv.lock` and
`package-lock.json`.

Nothing phones home. Add no CDN, no web font, no third-party origin, no
telemetry and no hosted service.

Do not loosen a gate to make a change pass. Choose another package, or write
the code.

Code from another project, Robinauts and neorc included, gets an entry in
[docs/legal/ip-clearance.md](docs/legal/ip-clearance.md) in the same pull
request.

Run `scripts/check-all.sh` from the root before declaring a change done. CI
runs the same scripts.
