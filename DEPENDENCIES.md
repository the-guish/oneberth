# Dependency policy

Oneberth is Apache-2.0, and a dependency must not put that in question — for
a company running it, for a product embedding it, or for Robinauts and
neorc, which import it. The policy is the Apache Software Foundation's
category model, which is the strictest in common use, and it is Robinauts'
policy, copied: the three repositories hold their dependencies to one set of
rules. The reasoning is in
[docs/specs/open-source.md](docs/specs/open-source.md).

The policy applies to every dependency **and to everything it brings with
it**: the whole locked set is checked, not the direct dependencies alone.

The Python locked set is resolved for the platforms the project runs on,
**Linux and macOS**, and for no other: `[tool.uv] environments` in the root
`pyproject.toml` holds `uv.lock` to those two, as Robinauts does, so a
package that another platform alone would need is not locked, not checked
and not installed anywhere.

Today the packages have **no runtime dependencies at all**, Python or npm,
and the only locked packages are `pytest` and what it brings, for the tests
of the checks. A first runtime dependency is a pull request of its own.

## Categories

### Allowed

Apache-2.0, MIT, MIT-0, BSD-2-Clause, BSD-3-Clause, 0BSD, ISC, Zlib,
PostgreSQL, PSF-2.0, CNRI-Python, CC0-1.0, Unlicense.

The list is Robinauts', and so are the reasons for its two less common
entries. `CNRI-Python` is the licence CNRI released Python 1.6.1 under:
permissive and OSI-approved, with no copyleft term; the ASF's nearest entry
is the PSF licence, in Category A. `MIT-0` is the MIT text with the condition
that the notice be reproduced taken out: strictly more permissive than MIT,
and Category A. Both were added to Robinauts' list by its project owner's
decision (2026-09-28 and 2026-09-30).
SPDX `CNRI-Python`, `PSF-2.0` and `Python-2.0` are three **different
identifiers**, and so is `CNRI-Python-GPL-Compatible`: allowing the first
allows neither of the others.

### Restricted

MPL-2.0, EPL-2.0, CDDL-1.x.

Only as an **unmodified, unbundled** dependency, and only if it is listed
by name below with its reason. Never in a JavaScript bundle, which is
bundled code: a bundle uses the allowed list only.

### Forbidden

GPL (any version), AGPL, LGPL (any version, dynamic linking included),
SSPL, BSL, Elastic-2.0, Commons Clause, CC-BY-NC, CC-BY-ND, any "no
commercial use" or "do no evil" term, proprietary licences, and **no licence
at all**.

Forbidden means forbidden transitively, and for development-only and
test-only dependencies too.

## Development-only and test-only dependencies

They follow the same categories. One may be excepted only by name, in
["Excepted development-only dependencies"](#excepted-development-only-dependencies)
below, with the licence somebody read, the version they read it in, and the
reason.

## Where exceptions are written

There are four tables of exceptions below, and every one of them is in this
file — a dependency is excepted here or nowhere. Not all of them are about
development-only dependencies: a row of
["Restricted dependencies in use"](#restricted-dependencies-in-use) may be
runtime, and ["Excepted licence texts"](#excepted-licence-texts) is a separate
table that does not look at scope at all — it answers which licence a pasted
text is, for runtime and development-only dependencies alike.

Three are Python's,
["Restricted dependencies in use"](#restricted-dependencies-in-use),
["Excepted development-only dependencies"](#excepted-development-only-dependencies)
and ["Excepted licence texts"](#excepted-licence-texts), and
`scripts/licence_gate.py` reads them against the workspace's `uv.lock`. The
first two are held to that lock: every row names a package it has. The third
is not — a row there may name a package ahead of its adoption, and the gate
notes it as not locked rather than failing. The fourth is npm's,
["JavaScript build tooling"](#javascript-build-tooling), and
`ts/oneberth-protocol/scripts/check-licences.mjs` reads it against
`ts/oneberth-protocol/package-lock.json` and what npm installed. They are
separate tables because the two gates read two different lockfiles, not
because the rules differ; the rules are the ones on this page.

All four tables are **empty** today.

An exception is a signature, not a switch. It can cover metadata that names
a licence family and no more — the trove classifier
`License :: OSI Approved :: BSD License` names no version of the BSD licence,
and only a person can open the package and see which one it is. It can never
cover a forbidden licence, a package that states no licence at all, or
metadata nobody can read — with one narrow case, set out under
["Excepted licence texts"](#excepted-licence-texts): the whole licence *text*
pasted where its name belongs, which the gate can still hold the row to by
its title line and by what else it names. And it holds for the version it
names, so the next upgrade fails until somebody reads the licence again.

## Assets

Fonts, icons, images, fixtures, sample data, model files and tokenizers
need a stated licence on the allowed list, and an entry in
[docs/legal/third-party.md](docs/legal/third-party.md). No model weights or
datasets are shipped. No third-party logos are shipped.

## Adopting or upgrading a dependency

1. One dependency change per pull request, and the pull request says why
   the dependency is needed and what was considered instead.
2. The licence of the package and of everything it brings is on the allowed
   list — or restricted, and then added to the table below in the same
   pull request. The licence is re-checked on every upgrade: a minor
   version has changed a licence before.
3. The package is what it claims to be: look at what the registry actually
   serves, not only at the repository.
4. The version is at least ten days old, for a first pin as for a bump: the
   pull request says which publish dates were read (PyPI's upload times, or
   `npm view <pkg> time --json`). Dependabot keeps the same cooldown
   (`.github/dependabot.yml`).
5. The lockfile is committed.

Points 2 and 5 are enforced by CI, with a licence gate over the whole
locked set: a dependency that fails is a broken build, not a ticket. Run it
yourself with `scripts/check-licences.sh` (Python) and `scripts/check-npm.sh`
(npm), from the root of the repository. No check can enforce point 4: the
publish dates are not in the lockfiles.

The Python gate reads the categories above and the tables below out of this
document, so a dependency is excepted here or nowhere. It fails closed: a
licence it cannot resolve to an identifier stops the build as surely as a
forbidden one, save the single case
["Excepted licence texts"](#excepted-licence-texts) sets out — an allowed
licence's text pasted where its name belongs, excepted by name at one version,
with the text's title line checked against the row. Metadata that names only
a family resolves to nothing — the classifier
`License :: OSI Approved :: BSD License` names no version of the BSD licence,
and the gate will not guess one. It reads that metadata from the
environment `uv` synced from this lockfile, or — for a package locked from
PyPI and not installed here — from the very file this lockfile pins by hash,
whose metadata PyPI publishes with a digest of its own. Metadata it cannot
tie to the lock, or cannot verify, it does not use, and a package it cannot
read is a package that does not pass.

A package may state its licence three times over — in `License-Expression`,
in the free-text `License` field and in its classifiers — and the three do
not always agree. Every claim that names a licence counts, and the worst of
them decides: a package claiming MIT in one field and the GPL in another is a
question for a person, not something to settle in our own favour. A claim
that names no licence counts for nothing, because that field so often holds
the licence text rather than its name.

## Tools that are not dependencies

`reuse` and `pip-audit` run as isolated tools (`uvx`), in their own throwaway
environments, and are deliberately **not** in `uv.lock`: `reuse` brings
`python-debian`, which is GPL-3.0, and adding it would put a forbidden
licence in our locked set for the sake of a program that only reads our
files. Neither is imported, linked or shipped; each is a separate process
that looks at the tree and exits.

Both are pinned to an exact version in
[scripts/tool-versions.sh](scripts/tool-versions.sh) and bumped by hand —
Dependabot does not see them. The licence gates themselves need no tool at
all: the Python one is the standard library, the npm one is Node's.

## Restricted dependencies in use

Three things in each row below are checked against reality on every run, so a
dependency that changes under us breaks the build rather than slipping
through on its name:

- the **licence** must be the one the package's own metadata states, and the
  only restricted licence it states. A package offered under a choice of two
  restricted licences fails until the row says which one we rely on;
- the **scope**, where it says *development only*: the gate fails if the
  runtime dependencies ever bring the package in;
- the row must name a licence that is restricted at all — a row is not a way
  to invent a category.

This table is the **Python** locked set's, and a test asserts that every row
of it names a package `uv.lock` really has, so an npm package cannot go in
it. npm's restricted cases are rows of
["JavaScript build tooling"](#javascript-build-tooling) below, which is the
table the npm gate reads; the conditions they have to meet are the ones
stated here, and that gate checks them.

| package | licence | scope | why it is acceptable |
|---|---|---|---|

## Excepted development-only dependencies

The licence is the one that was read, and the version is the one it was read
in; the gate checks both. The table has no row at present.

| package | version | licence | why it is acceptable |
|---|---|---|---|

## Excepted licence texts

Some packages put the whole licence *text* in the free-text `License` field
and state no identifier anywhere: no `License-Expression`, no `License ::`
classifier. The gate reads that as nothing it can read, and it is right to — a
page of prose is not a name. A row here is a person saying which licence that
text is, for one version of one package, and each row is a one-off: it is not a
rule about a kind of metadata, it is a signature under one text somebody read.
The table is Robinauts' (its project owner's decision, 2026-09-28), kept here
so that the gate reads the same document shape in both repositories. It is
Python's only: the npm gate has no such table, and what ships in a JavaScript
bundle is excepted nowhere.

It is narrower than the development-only table, on purpose, and separate from
it — it is not a development-only rule. The gate holds every row to all of
this:

- the free-text field is the metadata's **only** licence claim, and it names
  nothing the gate can resolve — no identifier, no family, no expression with
  anything readable in it, `WITH` included. Metadata that names something is
  judged by what it names, and no row here changes that; a package that states
  no licence at all, or a forbidden or restricted one, is never reached;
- the **version** is the one the text was read in;
- the **licence** is on the allowed list;
- the row is checked against the text rather than believed. A licence text
  begins with its title, so the first line of the field has to name the very
  licence the row states: `MIT License` is MIT, and a text headed
  `BSD 3-Clause License` under a row saying MIT fails. The first line is not
  the licence — a person still reads the rest, and that is what the row signs —
  but it means a release that swaps the text for another licence fails, whatever
  the row says;
- and a tripwire over the rest of the text finds no other licence. It looks
  at every line, at the pieces of a line between punctuation and `AND`, `OR`
  and `WITH`, and at every word shaped like an identifier, which it also holds
  to the forbidden pattern: a text headed `MIT License` that says
  `Portions: GPL-3.0-only` or `Data: CC-BY-NC-4.0` further down fails, and so
  does one that names a second allowed licence, which is a second question the
  row did not answer. It is a tripwire, not a reading: a licence named only in
  running prose — "licensed under the GNU General Public License version 3"
  mid-sentence — is not seen. The safeguard there is the person who signs the
  row for that version, having read the whole text.

It holds for runtime and development-only dependencies alike: what a row
answers is which licence a text is, not where the package is used, and the
answer has to be on the allowed list either way.

A row may name a package **ahead of its adoption**. The gate then notes that
it is not locked and that a row here may be ahead of adoption, and the test
that holds the other tables to `uv.lock` does not hold this one.

| package | version | licence | why it is acceptable |
|---|---|---|---|

## JavaScript build tooling

The npm packages under `ts/` that are **not** shipped: build and test
tooling, and what it brings. They are not distributed — not in a bundle, not
in a wheel, not linked into anything — but this document asks the same
questions of a development dependency as of any other, so the ones whose
licence is not plainly on the allowed list are excepted here by name, with the
version the licence was read in.

The gate is `ts/oneberth-protocol/scripts/check-licences.mjs`, ported from
Robinauts' `frontend/scripts/check-licences.mjs`, which reads this table and
the licence of every package `ts/oneberth-protocol/package-lock.json` locks and
npm installed. A package outside the allowed list with no row here, or with a
row naming a different version or a different licence, fails the build; so
does a row for a package that is installed and no longer needs one. A
forbidden licence fails whatever a row says.

The **scope** column is `development` or `runtime`, and it is checked against
the lockfile rather than believed: npm marks a package `dev` only when every
path to it is a development dependency, so a row saying `development` for a
package the runtime dependencies reach is a failure. A **restricted** licence
— the MPL-2.0 family — may only ever be carried by a `development` row, which
is the restricted category's "unmodified, unbundled" condition made into a
check.

Two things need no row. A licence that is a **choice** including an allowed
one is allowed — `MIT OR CC0-1.0` is, because MIT is on the list. A licence
that is a **conjunction** is allowed only if every part of it is, so
`(MIT AND CC-BY-3.0)` would need a row here.

The table is **empty**, and so is the tree: `ts/oneberth-protocol` has no
dependencies of any kind yet.

| package | version | scope | licence | why it is acceptable |
|---|---|---|---|---|

### The bundle

Robinauts gates its **bundle** separately, at build time, with
`rollup-plugin-license` in its Vite configuration and a committed
`bundled-packages.txt`: what ships in a bundle is the allowed list or
nothing, excepted nowhere. Oneberth has no bundle yet — no shell UI, no
Vite — so that gate is **not here yet**. It comes with the first build of the
shell UI, in the same pull request, and this section then says what it can
and cannot see, as Robinauts' does.

## Known exclusions

| package | licence | consequence |
|---|---|---|
| `psycopg`, `psycopg-pool` | LGPL-3.0-only | not usable; a PostgreSQL store here is on `asyncpg`, as in Robinauts and neorc |
