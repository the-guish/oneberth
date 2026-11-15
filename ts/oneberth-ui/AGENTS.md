# For coding agents working in ts/oneberth-ui

This package runs in a browser with a signed-in person's session cookie.
Any code in it can do whatever that person may. Its dependency rules are
neorc's `contributing/js-dependencies.md`, summed up in [README.md](README.md).

Do not:

- add a runtime dependency. React and React DOM are the peers, and the only ones.
- add, remove or bump a development dependency as part of another change.
  Pin a version published at least ten days ago.
- run `npm install`. Installs are `npm ci`.
- add an install script, or a `prepare` or `prepack` script.
- commit `dist/` or `node_modules/`, or edit `bundled-packages.txt` by hand.
- mock a module of the package in a test. The tests put `dev/fakeAuth.ts` in
  place of `fetch`.
- write a class name without the `oneberth-` prefix, or a colour outside `src/tokens.css`.

Do:

- run `npm run lint`, `npm run typecheck`, `npm test` and `npm run build`
  before calling a change done.
- start every new file with the licence header.
