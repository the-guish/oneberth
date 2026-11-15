# The shell UI

The shell draws the rail, the frames, the sign-in page and the admin screen.
Everything else on screen is an app's.

## Stack

- React and TypeScript, built with Vite. `react` and `react-dom` are the
  only runtime dependencies.
- Plain CSS over the theme tokens of [protocol.md](protocol.md), one
  stylesheet per area. No CDN, no web font, no third-party origin.
- Built in CI and shipped inside the `oneberth` wheel. Never committed.
- Served at `/` and `/shell/`, under a strict Content-Security-Policy:
  scripts, styles and connections from the origin; `frame-src 'self'`;
  `frame-ancestors 'none'` for the shell's own page.

## The rail

- A 48 px column at the left, the full height of the window. No top bar.
- Top: one icon per app the person may use, in the configuration's order.
  The current app's icon is marked. A badge (a count, or a dot) sits on an
  icon when the app sends one.
- Foot: the theme toggle (light, dark, system), the admin screen for an
  admin, and the profile: the person's initials, which open a menu with
  their name, "API tokens", "Linked devices" and "Sign out".
- The rail is always 48 px wide. It is already the narrow form. An app
  collapses its own panels.
- An icon shows the app's title beside it on hover and on focus.
- The rail shows even with one app enabled. It holds the profile.

## The frames

- The shell creates one `<iframe>` per app, the first time the app is
  opened. The shell keeps the frame while the person switches to another
  app. The app keeps its state.
- The frame fills the window beside the rail. The shell page never scrolls.
- The shell shows a frame after the app sends `shell/initialized`. Until
  then the shell shows a quiet loading state. The shell waits 15 s for the
  handshake. After that it shows "The app did not start", with "Reload".
- Each frame has a `title`: the app's title.

## Routing

- The address bar is `#/<app id>/<app route>`. Hash routing: the static
  files need no fallback route.
- `#/` opens the first app of the rail.
- Back and Forward move between apps and within them. The shell writes the
  hash; the app moves by `shell/navigate`.
- The app refuses a route the person may not reach. The shell shows "No
  access" for an app the person may not use.

## The sign-in page

- The sign-in page stands in place of everything until there is a session.
  It has one text button per provider, such as "Sign in with Google". It
  shows no logos.
- A failed sign-in shows a fixed message for its code. The provider's words
  go to the log.
- After sign-in the person lands where they were.

## The admin screen

- The admin screen is for `oneberth:admin` alone. It opens from the rail's
  foot. It is a page of the shell, not an app.
- **People**: everyone who has signed in, their grants, and when they last
  signed in. Grant or take back a role of an app, with a resource where the
  role takes one.
- **Service tokens**: mint one for an app's role and resource, with a name
  and a lifetime. The secret is shown once. Revoke one.
- **Apps**: the enabled apps, each one's address and whether its health
  path answers. Read only.
- The first admins named in the configuration are marked, and cannot be
  taken out from the screen.

## "API tokens"

- The page lists the person's personal tokens, oldest first. Minting one
  needs a name and a sign-in younger than ten minutes. An older sign-in asks
  the person to sign in again. The secret is shown once.

## Phones and narrow screens

- Below 768 px wide the rail becomes a bottom tab bar, 56 px: up to four
  apps and "You" (the profile menu, the theme, the admin screen). With more
  than four apps, the fourth place is "More", a list of the rest.
- The app's panels are its own drawers. The shell and the app keep at most
  one drawer open, by `shell/drawer`.
- The shell tells the app `narrow` or `wide` by `shell/layout`.

## Accessibility

- The rail is a `nav` with a list of links. Each link's name is the app's
  title; a badge adds "3 new" to it. Up and Down move along the rail; Enter
  opens.
- The focus moves into the frame of the app the person opens.
- Each frame carries the app's title. Inside, the app keeps its own
  landmarks.
- The focus outline is visible everywhere. Animations stop under
  `prefers-reduced-motion: reduce`.
- Colour contrast meets WCAG 2.2 AA in both themes.

## Desktop

- The same UI. The profile shows "Local user", with no sign-out and no admin
  screen.
- The rail marks an app that is starting or that failed to start
  ([runtimes.md](runtimes.md)).
- The page sends a heartbeat to the shell every 5 s. The launcher reads the
  heartbeat to learn that the window closed.

## Open

- The bundle size budget.
- Whether the operator may order the rail's icons on the admin screen.
