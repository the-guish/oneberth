# IP clearance log

An entry is appended whenever something enters the tree other than as a
contributor's own work in an ordinary signed-off pull request: vendored
code, a component copied from a registry, code or text derived from another
project, an asset. The entry is part of the pull request that brings it in.

Each entry states where it came from and at which commit, under what
licence, where it landed, what was changed, and where attribution was
added.

Entries are never edited after the fact; a correction is a new entry.

---

<!-- REUSE-IgnoreStart -->
<!-- The entries quote other projects' copyright and licence lines. They
     are statements about those projects, not about this file. -->

<!-- REUSE-IgnoreEnd -->

### 2026-11-14 — the scaffolding and the specs, from Robinauts and neorc

- Source: https://github.com/the-guish/robinauts at `e2f276d`, and
  https://github.com/open-shipyard/neorc at `26a30a0`.
- Their licence: Apache-2.0. The project owner holds the copyright of both
  and of this repository.
- What came in: Robinauts' licence and audit gates
  (`scripts/licence_gate.py`, `scripts/licence-fixtures.json`,
  `scripts/audit_requirements.py`, the `check-*.sh` scripts, the npm gate
  `check-licences.mjs` and their tests), its contribution rules, dependency
  policy and open-source spec, adapted; neorc's package layout (hatchling,
  hatch-vcs, one version from tags). The specs under `docs/specs/core/`
  restate Robinauts' sign-in design (`docs/specs/sign-in.md`), which is
  neorc's.
- Where it landed: `scripts/`, `tests/tooling/`, `ts/oneberth-protocol/`,
  `CONTRIBUTING.md`, `DEPENDENCIES.md`, `docs/`.
- What changed: names, the parts specific to Robinauts dropped, the npm gate
  moved to Node's own test runner, an empty npm tree accepted.
- Attribution: none needed beyond this entry; the copyright holder is the
  same.
