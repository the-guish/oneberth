# The shell protocol, version 1

How the shell's page and an app's frame talk. JSON-RPC 2.0 over
`postMessage`, between two windows of the same origin.

## Rules

- The app loads the client from the shell: `<script src="/shell/client.js">`.
  It is the client of the shell that is running, so the two always match.
  The app may also speak the protocol itself; this document is the contract.
- Each side reads a message only when `event.origin` is its own origin and
  `event.source` is the window it expects: the shell, its app's frame; the
  frame, `window.parent`. Each posts to its own origin, never to `"*"`.
- Messages are JSON-RPC 2.0: requests with an `id`, answered; notifications
  without one.
- Methods are named `shell/...`. The envelope and the handshake follow MCP
  Apps (SEP-1865), so the two can share one implementation; the names never
  collide.
- The shell sends nothing to a frame before it has sent `shell/initialized`.
- An unknown method is answered `-32601`. An unknown field is ignored.
- An app run without the shell (opened at `/apps/<id>/ui/` on its own) finds
  no parent that answers. The client then reports "no shell" and the app
  works without the rail.

## The handshake

`shell/initialize`, a request from the app:

```json
{"jsonrpc": "2.0", "id": 1, "method": "shell/initialize",
 "params": {"protocol": 1, "app": "flows"}}
```

Answered with:

```json
{"jsonrpc": "2.0", "id": 1, "result": {
  "protocol": 1,
  "route": "/runs/7f3a",
  "theme": {"mode": "dark", "tokens": {"--ground": "#161512", "...": "..."}},
  "layout": "wide",
  "user": {"name": "Ada Lovelace", "email": "ada@example.com"}}}
```

- A `protocol` the shell does not speak is answered with error `-32000`,
  and the shell shows, in the app's place, that the app needs another
  version of Oneberth.
- Then the app sends `shell/initialized`, a notification. The shell shows the
  frame only after it. A person sees the app only once it is drawn.

## Methods

| method | from | kind | params |
|---|---|---|---|
| `shell/navigate` | app → shell | notification | `{route, replace}`: the app moved; the shell writes `#/<id><route>` to the address bar, pushing or replacing |
| `shell/navigate` | shell → app | notification | `{route}`: the person moved (Back, a deep link, the rail); the app goes there and does not echo it back |
| `shell/title` | app → shell | notification | `{title}`: the browser tab reads `<title> · <app title>` |
| `shell/badge` | app → shell | notification | `{count}` (an integer, 0 clears) or `{dot: true}`: the app's rail icon |
| `shell/theme` | shell → app | notification | `{mode, tokens}`: the person changed the theme |
| `shell/open` | app → shell | request | `{app, route}`: show something in another app; answered `{opened: true}`, or an error if the app does not exist or the person may not see it |
| `shell/layout` | shell → app | notification | `{layout}`: `wide` or `narrow` |
| `shell/drawer` | both | notification | `{open}`: on a narrow screen, the app opened or closed its drawer, or the shell asks it to close it; at most one drawer is open |
| `shell/session-ended` | app → shell | notification | the app's API answered 401; the shell shows the sign-in page |

- A route is a string that starts with `/`, at most 2,048 characters. The
  shell does not interpret it.
- Badges are shown capped at "99+".

## Theme tokens

- The shell owns the light, dark and system choice, remembered per browser.
- `tokens` is a flat map of CSS custom properties, named by Oneberth:
  `--ground`, `--paper`, `--panel`, `--tint`, `--hover`, `--ink`,
  `--muted`, `--line`, `--edge`, `--accent`, `--on-accent`, `--link`,
  `--bad`, `--ok`, `--warn`, `--radius`, `--font`, `--mono`. They are
  Robinauts' tokens, which came from neorc.
- The client sets them on the frame's `:root` and sets `data-theme`. An app
  maps its own names to them once.

## Keys

- A key pressed inside a frame stays in the frame. Version 1 has no shell
  shortcut that must reach the shell from inside an app.

## The client

- `/shell/client.js` is an ES module with no dependencies. It exposes
  `connect({app})`, which runs the handshake and resolves with its result,
  or with `null` when there is no shell; `navigate`, `title`, `badge`,
  `open`, `drawer`; and `on(method, handler)`.
- Its source and its TypeScript types are in `ts/oneberth-protocol`. The
  types are published with the npm package for apps that want them.

## Versions

- The version is an integer. Adding an optional field or a new method keeps
  the version. A change of meaning, or a field becoming required, is a new
  version.
- The shell speaks every version it has shipped, until a major release of
  Oneberth drops one and says so.

## Planned

- A command palette (⌘K): apps offer their pages and actions
  (`shell/commands`), and the shell searches them.
