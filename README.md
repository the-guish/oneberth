# oneberth

Oneberth will be an empty shell that hosts apps: an icon rail, sign-in,
sessions, API tokens, roles and an app registry. Robinauts' Chat and neorc are
its first apps. The same apps run on a desktop, for one person, and on a
server, for a company. What is decided so far is in
[docs/decisions.md](docs/decisions.md).

**This repository is scaffolding.** It holds the licence, the contribution
rules and the supply-chain gates, and no product code yet: no sign-in, no
shell UI, no protocol.

    python/oneberth-core    the pure core package (empty)
    python/oneberth         the I/O package (empty)
    ts/oneberth-protocol    the shell protocol's client (empty, private)
    scripts/                the checks, one script per gate, which CI runs
    tests/                  the tests of those checks
    docs/                   the decisions, the open-source policy, the JS
                            rules, legal records

Run every check with `scripts/check-all.sh`. How to contribute is in
[CONTRIBUTING.md](CONTRIBUTING.md); the dependency policy is
[DEPENDENCIES.md](DEPENDENCIES.md).

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
