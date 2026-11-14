# Open source

Apache-2.0, safe inside a company, safe to embed in a commercial product,
and safe for Robinauts and neorc to import. The project follows the
"foundation-ready" policy, whose premise is that foundations and corporate
legal teams accept provenance, not code: for any line in the tree, one can
show who wrote it, when, under what licence, and that they had the right to.

This is Robinauts' policy (its `docs/specs/open-source.md`), adapted. A
library both projects import must not be the hole in either one's
supply-chain promise, so its gates exist from its first commit.

## Identity

- The name is Oneberth. The repository is `the-guish/oneberth`.

## Licence

- Apache-2.0, unmodified, for everything in the repository, documentation
  included. No dual licence, no added restriction.
  <!-- REUSE-IgnoreStart -->
- Every source file carries `SPDX-License-Identifier: Apache-2.0` and
  `Copyright The Oneberth Authors`. `REUSE.toml` covers files that cannot
  carry a header. Every byte in the tree has a stated licence.
  <!-- REUSE-IgnoreEnd -->
- `NOTICE` holds required attributions only.

## Contributions

- DCO sign-off on every commit, from the first. No CLA.
- AI coding assistants are allowed. By signing off, a contributor states
  that they reviewed every line, that it reproduces no incompatibly
  licensed code, and that substantially machine-generated files or blocks
  are disclosed in the pull request.
- No code from Stack Overflow or blogs. Nothing copied or ported from a
  forbidden or unlicensed source.
- Code that enters the tree other than through an ordinary signed-off pull
  request is recorded in `docs/legal/ip-clearance.md`: where it came from,
  at which commit, under what licence, where it landed, what was changed.
- Third-party assets and vendored code are listed in
  `docs/legal/third-party.md`. An upstream header is never stripped.
- No squash-imports; `main` is never force-pushed.

## Dependency licences

The ASF category model — the strictest in use. Written for contributors
in `DEPENDENCIES.md`, which both licence gates read.

- **Allowed:** Apache-2.0, MIT, MIT-0, BSD-2-Clause, BSD-3-Clause, 0BSD, ISC,
  Zlib, PostgreSQL, PSF-2.0, CNRI-Python, CC0-1.0, Unlicense.
- **Restricted:** MPL-2.0 (also EPL-2.0, CDDL), only as an unmodified,
  unbundled dependency, each one listed by name with its reason.
- **Forbidden, including transitively:** GPL, AGPL, LGPL (every version,
  dynamic linking included), SSPL, BSL, Elastic, Commons Clause,
  CC-BY-NC/ND, any "no commercial use" or "do no evil" term, proprietary,
  and **no licence at all**.
- Development-only and test-only dependencies follow the same lists. One
  may be excepted only by name, with a reason.
- One narrow exception to "unknown fails", for a **Python** dependency:
  metadata that pastes an allowed licence's *text* where its name belongs,
  and names nothing else, excepted by name at the version that was read
  (`DEPENDENCIES.md`, "Excepted licence texts"). The npm gate has no such
  exception, and bundled code is excepted nowhere.
- A JavaScript bundle is bundled code: the allowed list only.
- Assets — fonts, icons, images, fixtures, sample data, model files,
  tokenizers — need a stated licence on the allowed list. No model weights
  or datasets are shipped. No third-party logos are shipped.
- Adopting a dependency means: the gates pass at the pinned version; the
  package is what it claims to be; the version is at least ten days old;
  the reason for it is in the pull request. A licence is re-checked on every
  bump.

## Nothing phones home

- No telemetry, no CDN, no web font, no hosted service. The library will be
  embedded in hosts that promise their operators exactly that, and an
  air-gapped install has to work.

## Checks

On GitHub Actions, all blocking, all present from the first commit:

- Python: a licence gate over the full locked set, failing on unknown
  licences too; a vulnerability audit (`pip-audit`).
- JavaScript: a licence gate over everything installed, with exact pins;
  `npm audit`; `npm audit signatures`. The build-time allowlist over a
  bundle, and the committed list of bundled packages, come with the first
  bundle — the shell UI's.
- `reuse lint`; a DCO check. Secret scanning is planned.
- Dependabot for uv, npm and GitHub Actions, with a 10-day cooldown.
  Actions are pinned to commit SHAs.

## Releases

Planned, as Robinauts' and neorc's:

- One version for the repository, from a `v*` tag, by hatch-vcs.
- Built in CI from a signed tag; published by trusted publishing, with no
  long-lived token.
- `LICENSE`, `NOTICE` and the third-party licence texts are inside the
  wheel.
- Each release carries an SBOM.

## Details likely to change

- Tools: `pip-audit`; the project's own `scripts/licence_gate.py` for the
  Python gate and `ts/oneberth-protocol/scripts/check-licences.mjs` for npm,
  both ported from Robinauts.
- Known findings: `psycopg` and `psycopg-pool` are LGPL-3.0-only and
  excluded; a PostgreSQL store here is on `asyncpg`.
