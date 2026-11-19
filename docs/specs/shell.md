# The application shell

The shell is the frame every interface of the three projects shares.
It lives in `@oneberth/ui`, oneberth's node package.

## The layout

The window has two parts: a rail on the left, and the application's area beside it.

- **The rail** is a column of icons, 48 px wide. It shows one icon per application at its
  top. It shows the theme toggle and the account button at its bottom.
- **The application's area** belongs to the chosen application, whole. The application draws
  everything there: its own left panel, its pages and its side panel.
- Choosing an icon replaces the area with that application. The rail marks the chosen icon.
- An icon may show a count, such as the tasks that wait for the person. The application
  gives the shell that count.
- The rail is always shown, with one application too.

Robinauts shows two icons, Robinauts and neorc. Standalone neorc shows one.
A further application adds an icon.

## An application in the shell

- The host application registers its applications with the shell. Each has a name, an icon
  and a root component.
- The shell imports no application. Robinauts' interface imports the shell and neorc's
  package, and gives both applications to the shell.
- An application's code loads when its icon is first chosen.
- An application chosen once stays mounted while another is shown. Its scroll position and
  typed text are kept. Nothing of it is drawn, whatever its own styles say.
- A hidden application stops its long polls and reads again when shown.

## Routes

- The first segment of the hash names the application: `#/robinauts/…`, `#/neorc/…`.
- The shell reads that segment. The application gets the rest and changes it through the shell.
- The shell remembers the last route of each application, per browser.
- The account pages are the shell's own, under `#/account/…`.

## The account

- The account button opens a menu: the person's name and email, personal tokens, linked
  devices, and sign-out.
- The pages for tokens and devices are oneberth's. An admin also sees the service tokens.
- The sign-in page stands in place of every page until someone is signed in.
- The local mode has no sign-in page. The launcher opens the window already signed in.

## A small screen

- The rail becomes a row of icons at the top of the application's drawer.
- The drawer opens from one button.

## Styles

- The design tokens are CSS custom properties in `@oneberth/ui`. Every application uses them.
- Every class name starts with its package's prefix.
- The theme follows the operating system. The toggle is in the rail.

## What `@oneberth/ui` holds

| part | what it does |
|---|---|
| the session | asks `GET /auth/session` once, and forgets the user on a 401 |
| the sign-in page | the providers' buttons, the error codes, the return to where the person was |
| the shell | the rail, the application's area, the routes |
| the account pages | personal tokens, linked devices and pairing, service tokens, the fresh sign-in |
| the request helper | same-origin requests, JSON writes, the error shape |
| the tokens | colours, radii and fonts as custom properties |

- React and React DOM are its peer dependencies. It brings no other runtime dependency.
- The session uses React's own store hook.

## The neorc interface as a package

- neorc ships its interface twice: as built files in a wheel, for the standalone
  application, and as a node package of components, for a host such as Robinauts.
- The package exports one root component, the whole neorc application with its own left panel.
- The root component takes the address of neorc's API. Robinauts gives it `/neorc/`.
- The package names React, React DOM and `@oneberth/ui` as peer dependencies.
- It brings a query library and two graph libraries. Each passes the host's licence gate.

## What each application draws

| application | draws in its area |
|---|---|
| Robinauts | a left panel of conversations and projects, the chat, the side panel |
| neorc | a left panel of runs, flows and queues, and its pages |

The shell draws the rail, the sign-in page and the account pages. An application draws none of them.

## How a package reaches an application

- An application pins a node package to one exact version or commit.
- A package ships its TypeScript source. The application's own build compiles it, and no
  install script runs.
- The three repositories move React together. A package accepts the host's React 19.

## Details likely to change

- The icons, and the width of the rail.
- The names of the packages and of the root component.
- Robinauts' bundle budget.
