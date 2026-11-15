# Oneberth: core specs

These documents describe Oneberth as it is to be built. They hold what
Oneberth is, its parts, and the contracts between it and its apps. The
project's goals are in the [README](../../../README.md) at the root.

"Planned" means named and not yet specified. "Open" lists what is not
decided.

| document | what it holds |
|---|---|
| [overview.md](overview.md) | principles, the system in one page, the two setups |
| [apps.md](apps.md) | what an app is, its manifest, what it receives, what it must do |
| [identity.md](identity.md) | sign-in, users, sessions, roles, grants, the identity token, API tokens |
| [gateway.md](gateway.md) | how the shell checks a request and forwards it to an app |
| [runtimes.md](runtimes.md) | the cluster, the desktop launcher, Docker on desktop, the window |
| [protocol.md](protocol.md) | the shell protocol between the rail and an app's frame, version 1 |
| [shell-ui.md](shell-ui.md) | the rail, the sign-in page, the admin screen, phones, accessibility |
| [storage-and-config.md](storage-and-config.md) | Oneberth's database, the apps' databases, the configuration file |

The documents use short, plain sentences: the fact, then the rule.
