# Oneberth — core specs

These documents describe Oneberth as it is to be built. They are the
stable view: what Oneberth is, its parts, and the contracts between it and
its apps. The answers they rest on are in
[../../decisions.md](../../decisions.md). Where a spec and that file
disagree, the file wins until the spec is corrected.

"Planned" means named, not yet specified. "Open" lists what is not decided.

| document | what it holds |
|---|---|
| [overview.md](overview.md) | goals, principles, the system in one page, the two modes |
| [apps.md](apps.md) | what an app is, its manifest, the two kinds, URLs, discovery |
| [identity.md](identity.md) | sign-in, users, the allow list, roles, grants, tokens, the identity token |
| [processes.md](processes.md) | the web process, background processes, supervision, the RPC pattern |
| [protocol.md](protocol.md) | the shell protocol, version 1 |
| [shell-ui.md](shell-ui.md) | the rail, the sign-in page, the admin screen, phones, theme, accessibility |
| [storage-and-config.md](storage-and-config.md) | the database, SQLite on desktop, the configuration file |

Written in short, plain sentences: the fact, then the rule.
