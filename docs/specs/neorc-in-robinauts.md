# neorc inside Robinauts

Robinauts' interface talks to Robinauts' backend alone.
The backend answers neorc's API under `/neorc/`, and the interface shows neorc's
components over that address ([shell.md](shell.md)).

## Two ways behind one address

| | composed | forwarded |
|---|---|---|
| used by | the desktop | the cluster |
| neorc's manager runs | inside Robinauts' backend process | as a deployment of its own |
| a request crosses | a function call | HTTP |
| the component named `neorc` | neorc's own, from `new_manager_webapp` | oneberth's forwarding component |

- The interface sees the same address and the same answers both ways.
- The shape decides the way, where the backend is composed ([composition.md](composition.md),
  "The compositions").
- Robinauts imports neorc in two places: where it composes, and in `orchestrator/adapters/neorc/`.

## Composed

- Robinauts composes its own component with neorc's. One process serves both.
- Every request to `/neorc/` is checked for its credential and its neorc permission, like
  any other route of the composition.
- neorc's records are in the database of the backend, in the file `neorc.db`.
- neorc's scheduler is one of the things neorc's component starts.
- neorc's worker routes are served on the worker listener ([shapes.md](shapes.md), "Listeners").

## Forwarded

- The forwarding component passes on the method, the path after `/neorc`, the query and the body.
- The composition first applies its own checks on the request: the session, and the `Origin` of a write.
- The component sends the person's credential as a bearer. neorc's manager finds it in the
  shared store and decides the permission ([identity.md](identity.md), "Between two backends").
- The answer goes back unchanged: the status, the error body, the long poll as it arrives.
- A forwarded long poll holds one connection on each side. The component waits longer than
  neorc's own long poll, which is 25 seconds.
- The component passes on a fixed list of headers, and never a cookie.

## One version

- A Robinauts release pins one neorc version. The Python packages and the node package of
  that release come from the same commit.
- The composed way cannot disagree: one install holds both.
- The forwarding component reads the manager's version at its start and at each health check.
  It answers `/neorc/` with 503 and the two versions while they differ. The rest of Robinauts
  keeps working.
- The oneberth store has a version of its own ([identity.md](identity.md), "One store per deployment").

## neorc's own address

- The cluster's manager is standalone neorc. It serves its own interface at a public URL of its own.
  A person opens Robinauts' URL for both applications, or neorc's URL for neorc alone.
- Both addresses sign in from the same store. A person is the same user at both, with the same roles.
- Each origin has its own session. A person signs in once per origin, and the provider's
  session makes the second one quick.
- The desktop has one address, Robinauts'.

## The form that starts a run

- neorc has a basic form to start a run, with one field per input of the flow.
- A host application overrides that form for a flow. It supplies a description of the form in
  A2UI, and neorc draws it.
- Robinauts supplies its forms this way. A Robinauts form has lists of values that Robinauts
  fills: the repositories with their branches, the agents and the models.
- The host gives neorc's root component its source of forms. neorc draws the basic form for
  a flow the host has no form for.
- A form sends the flow's inputs, whoever described it.

## Requests of the backend's own

- Robinauts' backend uploads the flows it ships. It uses a service token with the role `neorc/ci`.
- A run started for a person is sent with that person's credential. The run is then that person's in neorc.

## A handler that calls Robinauts

- Some flow handlers drive Robinauts' API: the handlers Robinauts ships start conversations
  and turns.
- A run records the person who started it. The conversations a handler creates for that run
  belong to that person.
- Such a handler runs on a trusted worker and has a token for the front listener.
- An untrusted worker has no route to the front listener, and these handlers do not run there.

## Details likely to change

- The list of headers passed on.
- How often the version is read.

## Open

- The credential a handler uses to act for the person who started its run.
- Who owns the conversations of a run that a service started.
