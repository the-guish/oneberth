# oneberth specs, second set

These specs describe one pattern for three repositories: oneberth, neorc and Robinauts.
They cover sign-in, tokens, roles, the application shell and the deployment shapes.

The pattern holds in four shapes:

- a cloud cluster;
- a desktop application made of operating system processes;
- a desktop application with some of its processes in Docker;
- a desktop window, which is Chrome or Chromium showing the interface without a navigation bar.

## Status

Proposed on 2026-11-15. Nothing here is built yet.

The specs were written from a request by the project owner, with an addition on
composition the same day, and from the code of both applications, read at neorc `26a30a0`
and Robinauts `e2f276d`.
[review.md](review.md) checks the request for consistency and feasibility.
Read it first: it lists what the request left open and what these specs decided in its place.

## Documents

| document | what it holds |
|---|---|
| [review.md](review.md) | the review of the request: findings, decisions taken here, open questions, the order of work |
| [core.md](core.md) | goals, what each repository ships, the dependencies, the shapes in one table |
| [identity.md](identity.md) | sign-in, users, sessions, tokens, roles and permissions |
| [composition.md](composition.md) | components, the contract, how oneberth builds the web application |
| [shapes.md](shapes.md) | the cluster, the two desktop shapes, the launcher, the window, untrusted workers |
| [shell.md](shell.md) | the interface: the rail of applications, the account pages, the node packages |
| [neorc-in-robinauts.md](neorc-in-robinauts.md) | how Robinauts serves neorc: composed or forwarded, credentials, versions |

## What these specs replace

The specs of neorc and Robinauts stay the authority on each application's own behaviour.
These specs replace their parts on sign-in, tokens, roles and deployment.
[review.md](review.md) lists the documents to update in each repository.

## Writing rules

These documents follow `state-rules-in-short-plain-sentences.md` in the scratchpad
repository: the fact first, then the rule, in short sentences that open with their subject.
