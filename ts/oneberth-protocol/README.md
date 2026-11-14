# oneberth-protocol

The shell protocol's npm package: the types and a small client an app uses to
talk to the Oneberth shell. **Empty for now**: the repository is scaffolding,
and the protocol is not written yet. The package is `private`, has no
dependencies of any kind, and is never published.

What is here are the gates it will be held to:

- `.npmrc`: exact versions, and no install scripts.
- `.nvmrc`: the Node version, Robinauts'.
- `package-lock.json`: committed; installs are `npm ci`.
- `scripts/check-licences.mjs`: the licence policy of
  [../../DEPENDENCIES.md](../../DEPENDENCIES.md) over everything installed,
  and the exact pins. Ported from Robinauts.
- `tests/check-licences.test.mjs`: that gate's refusals, on node's own test
  runner.

`scripts/check-npm.sh`, from the root of the repository, runs all of it, and
`npm audit` with it. The rules are
[../../docs/contributing/js-dependencies.md](../../docs/contributing/js-dependencies.md).
