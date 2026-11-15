# @oneberth/ui

oneberth's application shell, as a node package of React components
([docs/specs/shell.md](../../docs/specs/shell.md)). It holds the session, the
sign-in page, the rail of applications, the account pages, the request helper
and the design tokens. It talks to the `/auth` routes of
[docs/specs/identity.md](../../docs/specs/identity.md).

The package ships its TypeScript source. A host's build compiles it, and no
install script runs. React and React DOM are its peers, at any React 19.
It brings no other runtime dependency.

## Using it in a host

A host gives the shell its applications. Each application has a name, a
title, an icon, a loader of its root component and, if it likes, a count.
The shell imports no application.

```tsx
import { applyRememberedTheme, createCount, Shell, type ShellApp } from "@oneberth/ui";

export const waitingTasks = createCount();

const apps: ShellApp[] = [
  { name: "robinauts", title: "Robinauts", icon: <RobinautsIcon />, load: () => import("./RobinautsApp") },
  { name: "neorc", title: "neorc", icon: <NeorcIcon />, load: () => import("./NeorcApp"), count: waitingTasks },
];

applyRememberedTheme();
createRoot(root).render(<Shell apps={apps} title="Robinauts" />);
```

- A name is a lowercase word. `account` and `sign-in` belong to the shell.
- A loader resolves to a module whose default export is the root component.
  It runs the first time the application is chosen.
- The root component gets `AppProps`: `name`, `route`, `navigate`, `href`,
  `visible` and `session`. A deeper component reads them with `useShellApp()`.
- The route is what follows `#/<name>` in the hash. An application changes it
  with `navigate`, and links to it with `href`.
- A hidden application gets `visible: false`. It stops its long polls, and
  reads again once it is shown.
- `ShellPanel` holds the application's left panel. On a small screen the
  shell draws it in its drawer.
- A count is a store with `subscribe` and `get`. `createCount()` makes one
  with `set`. The rail shows a count above zero.
- An application's own requests use `request`, `getJson`, `postJson` and
  `deleteJson`, or call `reportUnauthorized()` on a 401 of their own. A 401
  signs the person out of the page.
- Every class name of the package starts with `oneberth-`. An application
  styles with the tokens of `tokens.css`, such as `var(--panel)`.

## Installing it from a checkout

No package is published in this version. A host installs it from a checkout
of the pinned oneberth commit:

```sh
git -C vendor/oneberth checkout <commit>
npm pack ./vendor/oneberth/ts/oneberth-ui --pack-destination vendor/
npm install --save-exact ./vendor/oneberth-ui-0.0.0.tgz   # once; then npm ci
```

The tarball holds what `files` names: the source without its tests, the
licences and this file. The lock file records its integrity. A link to the
directory works too (`file:` with `install-links=true` in the host's
`.npmrc`). A host that links the directory without copying it adds
`resolve.dedupe: ["react", "react-dom"]` to its Vite configuration, so that
one React runs.

## Working on it

Node.js at the version in `.nvmrc`. Installs are `npm ci`, never `npm install`.

| script | what it does |
|---|---|
| `npm run dev` | serves the development page: the shell with two sample applications |
| `npm run lint` | ESLint |
| `npm run typecheck` | the type check, with the strictest flags of both hosts |
| `npm test` | the component tests, with Vitest |
| `npm run build` | the gate in place of a build: the type check, a build of the source as a host builds it, the licence allowlist, the size budget, and `scripts/check-package.mjs` |

The development page uses an in-memory stand-in for `/auth`
(`dev/fakeAuth.ts`). `ONEBERTH_UI_MODE=local npm run dev` starts it in the
local mode. `ONEBERTH_UI_BACKEND=http://127.0.0.1:8000 npm run dev` sends
`/auth` to a real backend instead. The stand-in also serves `/__dev/` routes
for a browser test (`dev/vitePlugin.ts`).

The tests put the same stand-in in place of `fetch`. They mock nothing of the
package.

## Dependencies

The rules are neorc's `contributing/js-dependencies.md`. Every dependency is
a development dependency, pinned to an exact version. `.npmrc` turns install
scripts off. The build fails on a bundled licence outside the allowlist, and
on more than 24 KB gzipped added to a host's bundle. It writes
`bundled-packages.txt`, which lists no package while the peers are all.

## Provenance

The session store, the sign-in page, the account pages and the dialog that
links a phone are written from Robinauts' `frontend/src/session/` and
`frontend/src/devices/` (Apache-2.0, The Robinauts Authors). Their design is
neorc's (Apache-2.0, The neorc Authors). The tokens are the palette both
share. The icon path data is lucide's, under `src/icons/LICENSE.lucide`.
