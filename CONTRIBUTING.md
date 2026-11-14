# Contributing to Oneberth

Oneberth is Apache-2.0 and means to stay safe to run inside a company, safe
to embed in a commercial product, and safe for Robinauts and neorc to
import. Most of what follows exists to keep that true: for any line in the
tree, it must be possible to show who wrote it, under what licence, and that
they had the right to. The rules are summarised in
[docs/specs/open-source.md](docs/specs/open-source.md).

The repository is scaffolding today: the gates below exist, the product
code does not yet.

## Branching

`main` is the only long-lived branch and must always be releasable.
Changes reach it through pull requests only, and it is never force-pushed.

1. Create a short-lived branch from `main`, prefixed `feature/` or `fix/`.
2. Open a pull request against `main`.
3. Once the checks pass and the review is complete, a maintainer merges it.

One concern per pull request. A change of dependency is a pull request of
its own.

## Repository layout

    python/oneberth-core   the pure core package (`oneberth_core`), no I/O
    python/oneberth        the I/O package (`oneberth`)
    ts/oneberth-protocol   the shell protocol's npm package, private
    scripts/              the checks, one script per gate, which CI runs as they are
    tests/                the tests of those checks
    docs/                 the open-source policy, the JS rules, legal records

The Python packages are one [uv](https://docs.astral.sh/uv/) workspace, with
one `uv.lock` at the root, and take one version from the repository's `v*`
tags through hatch-vcs, as neorc's do.

## Development setup

From the root of the repository:

    uv sync

and, for the npm package, with the Node version of
`ts/oneberth-protocol/.nvmrc`:

    cd ts/oneberth-protocol && npm ci

## Checks

Every check is a script in [scripts/](scripts/), and CI runs only those
scripts, one per job, so a check can be run and debugged where it fails. CI
is not your machine, though: it installs the pinned uv from
[scripts/tool-versions.sh](scripts/tool-versions.sh), runs on Python 3.12
and on the Node of `ts/oneberth-protocol/.nvmrc`, so a failure that depends on
a version may show up in one place and not the other. Run them all before
opening a pull request, from the root of the repository:

    scripts/check-all.sh

or one at a time:

    scripts/check-tests.sh      pytest over tests/: the checks' own tests
    scripts/check-licences.sh   the Python dependency licence gate of
                                DEPENDENCIES.md, over uv.lock
    scripts/check-audit.sh      pip-audit over the whole locked set
    scripts/check-npm.sh        the npm package: npm ci, its licence gate and
                                that gate's tests, npm audit, npm audit
                                signatures
    scripts/check-reuse.sh      reuse lint: every file states its licence
    scripts/check-dco.sh        sign-off on every commit of the branch

Every one of them runs on every pull request, and a failure is a failure.
Making them *required* — so that GitHub refuses the merge button rather than
showing a red cross — is branch protection, which the project owner still
has to switch on.

`check-tests.sh`, `check-licences.sh` and `check-reuse.sh` pass their
arguments on to the tool they wrap, so `scripts/check-tests.sh -k licence`
does what you would expect. `check-dco.sh` takes a commit range and defaults
to what this branch adds to `main`; CI runs it over the commits of the pull
request. `check-audit.sh`, `check-npm.sh` and `check-all.sh` take no
arguments and say so rather than ignoring them — `check-audit.sh` reads
pip-audit's JSON to make sure every pinned package was really looked at, and
`check-npm.sh` is the npm package's whole CI job in order; an argument that
changed either would quietly turn the check off.

`reuse` and `pip-audit` are not dependencies of the project: they run as
isolated tools, from a version pinned in
[scripts/tool-versions.sh](scripts/tool-versions.sh) and bumped by hand. That
file is the one place for such pins, and CI reads uv's version from it too.
[DEPENDENCIES.md](DEPENDENCIES.md) says why they stay out of the lockfile.

## Licence header

Every source file starts with:

    # SPDX-License-Identifier: Apache-2.0
    # Copyright The Oneberth Authors

in the comment syntax of its language. A file that cannot carry a header is
covered by [REUSE.toml](REUSE.toml), which lists such files by name: a new
one is added to it. `reuse lint` must pass: every file in the tree has a
stated licence.

Never remove or alter a header that came with someone else's file.

## Developer Certificate of Origin

All contributions must be signed off under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/).
Add `-s` to your commit:

    git commit -s -m "component: short imperative summary"

which appends:

    Signed-off-by: Jane Doe <jane@example.com>

Use your real name and a reachable email address. Sign-off is a statement about
the provenance of your contribution, so pseudonymous sign-offs cannot be
accepted. If you are contributing on behalf of an employer, make sure you have
their authorization.

`scripts/check-dco.sh` checks this, and CI runs it on every pull request. The
sign-off may be the author's or the committer's: the DCO is certified by
whoever puts the commit here, and that is not always the person who wrote it.

A dependency update opened by Dependabot carries no sign-off, because a bot
certifies nothing. A maintainer takes such a change over before it is merged,
by one of:

    git cherry-pick -s <commit>          keeps Dependabot as the author and
                                         signs off as the committer
    git commit --amend -s --reset-author makes it your commit outright

Both pass the check. `git commit -s` on top of an unsigned commit does not:
the commit without the trailer is still in the range.

There is no contributor licence agreement. You keep the copyright in your
contribution and license it to everyone under Apache-2.0.

## AI-assisted contributions

AI coding assistants are allowed. By signing off, you certify that:

- you have reviewed and understand every line you submit;
- the contribution does not reproduce third-party code under a license
  incompatible with Apache-2.0, and does not carry attribution requirements
  we have not satisfied;
- you have disclosed in the PR description any substantially machine-generated
  file or block.

## Where code may come from

- Write it yourself, or take it from a source whose licence is on the
  allowed list in [DEPENDENCIES.md](DEPENDENCIES.md) — and then say so:
  keep the copyright line and the header that came with the file, add the
  text of its licence to [LICENSES/](LICENSES/) if it is not there yet, and
  record it as described below.
- Earlier work of your own is yours to contribute, published or not, as
  long as you alone hold the rights to it — no co-author, no employer with
  a claim. Signing off is your statement that this is so.
- **No code from Stack Overflow, blogs or forums.** Their licences are
  usually incompatible. Understand the idea, close the tab, write your own.
- **Nothing copied, ported or translated** from someone else's work that is
  GPL, AGPL, LGPL, proprietary, or has no licence at all. A repository without a
  licence file is "all rights reserved", not public domain.
- Code that enters the tree other than as your own work in an ordinary
  signed-off pull request — a vendored file, a component copied from a
  registry, code derived from another project (Robinauts and neorc
  included: they are other projects, with authors of their own), an asset —
  gets an entry in [docs/legal/ip-clearance.md](docs/legal/ip-clearance.md),
  in the same pull request. Third-party code and assets that stay in the
  tree are also listed in [docs/legal/third-party.md](docs/legal/third-party.md).
- Do not import a codebase in one commit.

## Dependencies

Adding or upgrading a dependency follows [DEPENDENCIES.md](DEPENDENCIES.md).
In short: its licence, and the licence of everything it brings, must be on
the allowed list; the pull request says why the dependency is needed; the
version is at least ten days old, and the pull request says which publish
dates were read; and the lockfile is committed. `scripts/check-licences.sh`
enforces the licence rules over the whole Python locked set, and a licence it
cannot resolve fails as surely as a forbidden one.

npm has rules of its own:
[docs/contributing/js-dependencies.md](docs/contributing/js-dependencies.md).
Read it before touching anything under `ts/`.
`ts/oneberth-protocol/scripts/check-licences.mjs` applies the policy of
[DEPENDENCIES.md](DEPENDENCIES.md) to **everything the lockfile pins and npm
installed**, with the development exceptions named — by package, version,
scope and licence — in that document's "JavaScript build tooling" table, and
it refuses a version in `package.json` that is not exact.
`scripts/check-npm.sh` runs it. The second npm gate Robinauts has, over what
a **bundle** ships, comes with the first bundle: there is none yet.
