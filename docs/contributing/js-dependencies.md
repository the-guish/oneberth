# JavaScript dependencies

Rules for the packages under `ts/`. Today that is one package,
`ts/oneberth-protocol`, private and with no dependencies of any kind. When the
shell UI exists, its code will ship inside the `oneberth` wheel, compiled into
a bundle nobody reads, and run in a browser beside a signed-in person's
session, able to do whatever they may. Every dependency is code the project
vouches for, at every version it takes.

These are Robinauts' rules (its `docs/contributing/js-dependencies.md`),
adapted. The policy behind the licence rules is
[../../DEPENDENCIES.md](../../DEPENDENCIES.md); this file says how it is
applied to npm.

## Keep them few

- Add a runtime dependency only when writing the code would cost more than
  vetting the package, and its transitive tree, now and at every update.
- `dependencies` is what ships; `devDependencies` is build and test tooling.
  Keep the first list as short as it can be. The protocol package is meant to
  have **none**: apps copy or install it, and every dependency it took would
  land in each of them.

## Vet before adding

- Maintained: recent releases, issues answered, and **more than one
  maintainer — or a single maintainer with years of settled releases and wide
  adoption**. The judgement is **written down** where the package is adopted:
  which of the two it is, and why.
- Small: `npm view <pkg> dependencies` is short.
- Licensed on the list below.
- Published with provenance, `npm view <pkg> dist.attestations` — **required
  of a release published after npm had provenance, which is April 2023**. An
  older release cannot carry one and is not refused for that; it is accepted
  when the package has years of settled history behind it, and, again, the
  judgement is written down.
- Needs no install script, `npm view <pkg> hasInstallScript`. A package that
  does is a reason to pick another.
- Read what npm serves, `npm pack <pkg>` and look inside; the GitHub
  repository is not necessarily what was published.

## Licences

Every package carries a licence on the **allowed list of
[../../DEPENDENCIES.md](../../DEPENDENCIES.md)**, and that document is where
the list is — `ts/oneberth-protocol/scripts/check-licences.mjs` reads it out of
the two Categories paragraphs, so the list is written once. Extending the list
is a reviewed change to `DEPENDENCIES.md`, with a stated reason.

What is not plainly on the allowed list is excepted by name and version in the
**"JavaScript build tooling"** table of
[../../DEPENDENCIES.md](../../DEPENDENCIES.md) — the one place an npm
exception may be written. The gate enforces it over everything the lockfile
pins and npm installed: no row, a row naming another version, a row naming
another licence, a row for a package that no longer needs one, and the build
is red. A forbidden licence fails whatever a row says, and the list of what
is forbidden is shared with the Python gate through
`scripts/licence-fixtures.json`, which both test suites read.

Each row also states a **scope**, `development` or `runtime`, which is
checked against the lockfile: npm marks a package `dev` only when every path
to it is a development dependency. A restricted licence — the MPL-2.0 family
— may only be carried by a `development` row.

The gate also refuses a version in `package.json` that is not exact, in
`dependencies`, `devDependencies`, `optionalDependencies`, `peerDependencies`
and `overrides` alike.

**The bundle has a gate of its own in Robinauts**, at build time: the allowed
list with no exception at all over what ships, and a committed
`bundled-packages.txt` the build compares with what it wrote. There is no
bundle here yet, so there is no such gate yet; it is added with the first
build, in the same pull request ([../../DEPENDENCIES.md](../../DEPENDENCIES.md),
"The bundle").

## Installing and updating

- Exact versions in `package.json`, no ranges. `package-lock.json` is
  committed and installs are `npm ci`, never `npm install`.
- `.npmrc` sets `ignore-scripts=true` and `save-exact=true`; install scripts
  do not run on any machine or in CI.
- Updates come from Dependabot, with a cooldown: no version published fewer
  than 10 days ago. Do not update by hand to a version younger than that;
  compromised releases are usually withdrawn within days.
- **The cooldown holds when a package is first adopted, not only when it is
  bumped.** `latest` is often a release of that morning, and a first pin is
  exactly as good a place to plant a compromised version as an upgrade is.
  Pin the newest version published at least ten days ago:
  `npm view <pkg> time --json` lists every version with the day it appeared.
  No script can check this after the fact — the dates are not in the lockfile
  — so it is checked when the pin is written, and the dates that were read go
  in the pull request.
- One dependency change per pull request, never as a side effect of a feature.
- CI runs `npm audit --audit-level=low` for known advisories on everything
  installed, and `npm audit signatures --omit=dev` for registry signatures and
  provenance on what ships: the registry does not hold attestations for every
  dev-only package. npm refuses to verify an empty set, so while nothing that
  ships is locked, `scripts/check-npm.sh` says so instead of running it.
- Node.js at the version in `.nvmrc`, Robinauts' version.

## In the browser

- No CDN, no external font and no request outside the host's own origin.
  Every asset will be in the wheel, so the shell works on air-gapped hosts.

## Releases

Bundles will be built in CI, from the committed lockfile and `.nvmrc`. Built
assets are never committed, and a bundle built on a laptop is never released.

## Where this is enforced

- `ts/oneberth-protocol/scripts/check-licences.mjs`: the policy over everything
  installed, the exceptions table of `DEPENDENCIES.md`, the scopes, and the
  exact pins. Its own refusals are tested in
  `ts/oneberth-protocol/tests/check-licences.test.mjs`.
- `ts/oneberth-protocol/.npmrc`: exact versions and no install scripts.
- `scripts/licence-fixtures.json`: what the policy forbids, read by both
  gates' test suites so that the Python and npm copies cannot drift.
- `scripts/check-npm.sh`, and the `npm` job of `.github/workflows/ci.yml`
  that runs it: the install, the gate, its tests and the audits.
- `.github/dependabot.yml`: the updates and their cooldown.
- [../../AGENTS.md](../../AGENTS.md): the same rules, as short sentences for
  coding agents.
