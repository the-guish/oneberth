# oneberth

Oneberth will be a shared library: an app shell with OIDC sign-in, sessions,
API tokens, roles and an app registry, imported by Robinauts and neorc. Why
it exists is ADR 0008 of Robinauts, "A shell of apps, in a repository of its
own".

**This repository is scaffolding.** It holds the licence, the contribution
rules and the supply-chain gates, and no product code yet: no sign-in, no
shell UI, no protocol.

    python/oneberth-core     the pure core package (empty)
    python/oneberth          the I/O package (empty)
    ts/oneberth-protocol     the shell protocol's npm package (empty, private)
    scripts/                the checks, one script per gate, which CI runs
    tests/                  the tests of those checks
    docs/                   the open-source policy, the JS rules, legal records

Run every check with `scripts/check-all.sh`. How to contribute is in
[CONTRIBUTING.md](CONTRIBUTING.md); the dependency policy is
[DEPENDENCIES.md](DEPENDENCIES.md).

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
