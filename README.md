# oneberth

oneberth is the shared base of [neorc](https://github.com/the-guish/neorc) and
[Robinauts](https://github.com/the-guish/robinauts). It holds sign-in, sessions, tokens
and roles, the web application, the application shell, the admin scripts and the
desktop launcher.

It ships two packages:

- `oneberth`, a Python library, under [python/oneberth](python/oneberth);
- `@oneberth/ui`, a node package of interface components, under [ts](ts).

## What is built

- The identity core, `oneberth.identity`: users, the four kinds of credential, device
  pairing, the allow list, roles and the decision of a permission. It runs on a store
  port, with a memory store and the store's contract suite.

## Documents

- [docs/specs](docs/specs/README.md): the specs. They describe the desired state, and
  they are the authority.
- [docs/working-notes](docs/working-notes): the gap between the code and the specs, and
  the plan that closes it.
- [CONTRIBUTING.md](CONTRIBUTING.md): the branching model, the checks and the rules.

oneberth is licensed under the [Apache License 2.0](LICENSE).
