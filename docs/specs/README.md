# oneberth specs

These specs describe one pattern for three repositories: oneberth, neorc and Robinauts.
They cover sign-in, tokens, roles, the web application, the application shell and the
deployment shapes.

The pattern holds in four shapes:

- a cloud cluster;
- a desktop application made of operating system processes;
- a desktop application with some of its processes in Docker;
- a desktop window, which is Chrome or Chromium showing the interface without a navigation bar.

## Documents

| document | what it holds |
|---|---|
| [core.md](core.md) | goals, what each repository ships, the dependencies, the shapes in one table |
| [identity.md](identity.md) | sign-in, users, sessions, tokens, roles and permissions |
| [composition.md](composition.md) | components, how oneberth builds the web application |
| [shapes.md](shapes.md) | the cluster, the two desktop shapes, the launcher, the window, untrusted workers |
| [shell.md](shell.md) | the interface: the rail of applications, the account pages, the node packages |
| [neorc-in-robinauts.md](neorc-in-robinauts.md) | how Robinauts serves neorc: composed or forwarded, credentials, versions |

## What a spec holds

- A spec describes the desired state: how the three projects work with the pattern in place.
- A spec says nothing of the code as it is. The gap and the plan are in
  [working-notes](../working-notes/).
- The specs of neorc and Robinauts are the authority on each application's own behaviour.
