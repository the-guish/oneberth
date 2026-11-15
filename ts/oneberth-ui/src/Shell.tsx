// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The shell: the rail and the application's area (shell.md).
 *
 * `Shell` asks who is signed in. Until someone is, the sign-in page stands in
 * place of every page. Then the window has two parts: the rail, 48 px wide,
 * with one link per application at its top and the theme toggle and the
 * account button at its bottom; and the area, which belongs to the chosen
 * application whole, or to an account page.
 *
 * An application loads the first time it is chosen and stays mounted while
 * another is shown, so its scroll position and typed text are kept. A hidden
 * application gets `visible: false`.
 *
 * Below the breakpoint the rail becomes a row of icons at the top of a
 * drawer, under which the application's own panel goes (`ShellPanel`). One
 * button opens the drawer.
 */
import {
  Component,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type ErrorInfo,
  type ReactNode,
} from "react";

import { AccountMenu } from "./AccountMenu";
import { AccountPages, accountTitle } from "./account/AccountPages";
import {
  AppContext,
  PanelContext,
  useCount,
  type AppProps,
  type PanelPlace,
  type ShellApp,
} from "./apps";
import { useTrappedFocus, useWide } from "./drawer";
import { MenuIcon } from "./icons";
import {
  APP_NAME,
  RESERVED_NAMES,
  appHash,
  go,
  normalRoute,
  placeOf,
  useHash,
  type Place,
} from "./routes";
import { loadSession, useSession, type Session } from "./session";
import { SignIn } from "./SignIn";
import { remember, remembered } from "./storage";
import { ThemeToggle } from "./ThemeToggle";
import "./tokens.css";
import "./controls.css";
import "./shell.css";

export interface ShellProps {
  /** The applications, in the order of the rail. At least one. */
  apps: readonly ShellApp[];
  /** The product's name, for the sign-in page and the window's title: "Robinauts". */
  title: string;
}

const LAST_APP_KEY = "app";
const routeKey = (app: string) => `route.${app}`;

/** Refuses a list of applications the shell cannot route. */
export function checkApps(apps: readonly ShellApp[]): void {
  if (apps.length === 0) throw new Error("the shell needs at least one application");
  const seen = new Set<string>();
  for (const app of apps) {
    if (!APP_NAME.test(app.name) || RESERVED_NAMES.includes(app.name)) {
      throw new Error(`an application cannot be named ${JSON.stringify(app.name)}`);
    }
    if (seen.has(app.name)) throw new Error(`two applications are named ${app.name}`);
    seen.add(app.name);
  }
}

export function Shell({ apps, title }: Readonly<ShellProps>) {
  checkApps(apps);
  const state = useSession();
  const place = placeOf(useHash());
  if (state.session === null) {
    return (
      <main className="oneberth-signin">
        <div className="oneberth-signin-card">
          <h1 className="oneberth-signin-title">{title}</h1>
          {state.error === null ? (
            <p className="oneberth-signin-text">Loading…</p>
          ) : (
            <>
              <p role="alert" className="oneberth-signin-failed">
                {`Who is signed in could not be read: ${state.error.detail}`}
              </p>
              <button
                type="button"
                className="oneberth-signin-retry"
                onClick={() => void loadSession()}
              >
                Try again
              </button>
            </>
          )}
        </div>
      </main>
    );
  }
  if (state.status !== "signed-in") {
    return (
      <SignIn
        session={state.session}
        title={title}
        error={place.kind === "sign-in" ? place.error : null}
      />
    );
  }
  return <Frame apps={apps} title={title} session={state.session} place={place} />;
}

/** The route an application had last, in this page or in this browser. */
function lastRoute(routes: Readonly<Record<string, string>>, app: string): string {
  return routes[app] ?? normalRoute(remembered(routeKey(app)) ?? "");
}

function Frame({
  apps,
  title,
  session,
  place,
}: Readonly<{ apps: readonly ShellApp[]; title: string; session: Session; place: Place }>) {
  const wide = useWide();
  const first = apps[0] as ShellApp;
  const current = place.kind === "app" ? apps.find((app) => app.name === place.app) : undefined;
  const [mounted, setMounted] = useState<readonly string[]>([]);
  const [routes, setRoutes] = useState<Readonly<Record<string, string>>>({});

  // What the hash says now, kept as state during the render: the chosen
  // application is mounted, and its route is the one it shows.
  if (current !== undefined && place.kind === "app") {
    if (!mounted.includes(current.name)) setMounted([...mounted, current.name]);
    if (routes[current.name] !== place.route) setRoutes({ ...routes, [current.name]: place.route });
  }

  useEffect(() => {
    if (current === undefined || place.kind !== "app") return;
    remember(LAST_APP_KEY, current.name);
    remember(routeKey(current.name), place.route);
  }, [current, place]);

  // The home and a sign-in page, once signed in, lead to the last application.
  const home = place.kind === "home" || place.kind === "sign-in";
  useEffect(() => {
    if (!home) return;
    const last = apps.find((app) => app.name === remembered(LAST_APP_KEY)) ?? first;
    go(appHash(last.name, lastRoute({}, last.name)), true);
  }, [home, apps, first]);

  const [drawer, setDrawer] = useState(false);
  // The drawer's slot of each application, for its `ShellPanel`.
  const [slots, setSlots] = useState<Readonly<Record<string, HTMLElement | null>>>({});
  const slotRefs = useRef(new Map<string, (element: HTMLElement | null) => void>());
  const slotRef = useCallback((name: string) => {
    let ref = slotRefs.current.get(name);
    if (ref === undefined) {
      ref = (element) => {
        setSlots((was) => (was[name] === element ? was : { ...was, [name]: element }));
      };
      slotRefs.current.set(name, ref);
    }
    return ref;
  }, []);
  const hrefOf = useCallback((app: ShellApp) => appHash(app.name, lastRoute(routes, app.name)), [routes]);

  const area = (
    <div className="oneberth-area">
      {apps
        .filter((app) => mounted.includes(app.name))
        .map((app) => (
          <AppPane
            key={app.name}
            app={app}
            route={routes[app.name] ?? ""}
            visible={current?.name === app.name}
            session={session}
            wide={wide}
            slot={wide ? null : (slots[app.name] ?? null)}
          />
        ))}
      {place.kind === "account" && <AccountPages session={session} page={place.page} />}
      {place.kind === "app" && current === undefined && (
        <main className="oneberth-missing">
          <p role="alert">{`There is no application named "${place.app}".`}</p>
          <ul>
            {apps.map((app) => (
              <li key={app.name}>
                <a href={hrefOf(app)}>{app.title}</a>
              </li>
            ))}
          </ul>
        </main>
      )}
    </div>
  );

  const heading =
    current?.title ?? (place.kind === "account" && place.page !== null ? accountTitle(place.page) : title);

  if (wide) {
    return (
      <div className="oneberth-shell">
        <nav aria-label="Applications" className="oneberth-rail">
          <AppLinks apps={apps} current={current?.name ?? null} hrefOf={hrefOf} />
          <div className="oneberth-rail-bottom">
            <ThemeToggle />
            <AccountMenu session={session} place="rail" />
          </div>
        </nav>
        {area}
      </div>
    );
  }
  return (
    <Narrow
      apps={apps}
      current={current?.name ?? null}
      mounted={mounted}
      slotRef={slotRef}
      hrefOf={hrefOf}
      session={session}
      heading={heading}
      open={drawer}
      setOpen={setDrawer}
    >
      {area}
    </Narrow>
  );
}

/** The links to the applications, on the rail or in the drawer's row. */
function AppLinks({
  apps,
  current,
  hrefOf,
}: Readonly<{ apps: readonly ShellApp[]; current: string | null; hrefOf: (app: ShellApp) => string }>) {
  return (
    <ul className="oneberth-apps">
      {apps.map((app) => (
        <li key={app.name}>
          <AppLink app={app} chosen={app.name === current} href={hrefOf(app)} />
        </li>
      ))}
    </ul>
  );
}

function AppLink({ app, chosen, href }: Readonly<{ app: ShellApp; chosen: boolean; href: string }>) {
  const count = useCount(app.count);
  const shown = count !== null && count > 0 ? count : null;
  return (
    <a
      href={href}
      title={app.title}
      aria-current={chosen ? "page" : undefined}
      className="oneberth-app-link"
      data-app={app.name}
    >
      <span className="oneberth-app-icon" aria-hidden="true">
        {app.icon}
      </span>
      <span className="oneberth-visually-hidden">
        {shown === null ? app.title : `${app.title}, ${shown}`}
      </span>
      {shown !== null && (
        <span className="oneberth-app-count" aria-hidden="true">
          {shown > 99 ? "99+" : shown}
        </span>
      )}
    </a>
  );
}

/** The small-screen layout: one button, and the drawer it opens. */
function Narrow({
  apps,
  current,
  mounted,
  slotRef,
  hrefOf,
  session,
  heading,
  open,
  setOpen,
  children,
}: Readonly<{
  apps: readonly ShellApp[];
  current: string | null;
  mounted: readonly string[];
  slotRef: (name: string) => (element: HTMLElement | null) => void;
  hrefOf: (app: ShellApp) => string;
  session: Session;
  heading: string;
  open: boolean;
  setOpen: (open: boolean) => void;
  children: ReactNode;
}>) {
  const drawerId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const hash = useHash();
  useTrappedFocus(panel, open);

  // A navigation closes the drawer: a link in it was followed.
  const [openedAt, setOpenedAt] = useState(hash);
  if (open && hash !== openedAt) {
    setOpenedAt(hash);
    setOpen(false);
  }

  const wasOpen = useRef(open);
  useEffect(() => {
    if (open) panel.current?.focus();
    else if (wasOpen.current) opener.current?.focus();
    wasOpen.current = open;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const { body } = document;
    const before = body.style.overflow;
    body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      body.style.overflow = before;
    };
  }, [open, setOpen]);

  return (
    <div className="oneberth-shell oneberth-shell-narrow">
      <header className="oneberth-topbar">
        <button
          ref={opener}
          type="button"
          aria-label="Open the menu"
          aria-expanded={open}
          aria-controls={drawerId}
          onClick={() => {
            setOpenedAt(hash);
            setOpen(true);
          }}
          className="oneberth-topbar-button"
        >
          <MenuIcon className="oneberth-topbar-icon" />
        </button>
        <span className="oneberth-topbar-title">{heading}</span>
      </header>
      {open && (
        <div
          className="oneberth-backdrop"
          aria-hidden="true"
          onClick={() => {
            setOpen(false);
          }}
        />
      )}
      <div
        ref={panel}
        id={drawerId}
        className="oneberth-drawer"
        data-open={open}
        tabIndex={-1}
        inert={!open}
        {...(open ? { role: "dialog", "aria-modal": true, "aria-label": "Menu" } : {})}
      >
        <nav aria-label="Applications" className="oneberth-drawer-row">
          <AppLinks apps={apps} current={current} hrefOf={hrefOf} />
          <div className="oneberth-drawer-tools">
            <ThemeToggle />
            <AccountMenu session={session} place="drawer" />
          </div>
        </nav>
        {apps
          .filter((app) => mounted.includes(app.name))
          .map((app) => (
            <div
              key={app.name}
              ref={slotRef(app.name)}
              className="oneberth-drawer-slot"
              hidden={app.name !== current}
            />
          ))}
      </div>
      {children}
    </div>
  );
}

type Loaded =
  | { status: "loading" }
  | { status: "ready"; Root: ComponentType<AppProps> }
  | { status: "failed"; detail: string };

/** One mounted application: loaded once, kept while hidden. */
function AppPane({
  app,
  route,
  visible,
  session,
  wide,
  slot,
}: Readonly<{
  app: ShellApp;
  route: string;
  visible: boolean;
  session: Session;
  wide: boolean;
  /** The application's slot in the drawer, on a small screen. */
  slot: HTMLElement | null;
}>) {
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const { load } = app;
  useEffect(() => {
    let dropped = false;
    load().then(
      (module) => {
        if (!dropped) setLoaded({ status: "ready", Root: module.default });
      },
      (failure: unknown) => {
        if (!dropped) setLoaded({ status: "failed", detail: String(failure) });
      },
    );
    return () => {
      dropped = true;
    };
  }, [load, attempt]);

  const name = app.name;
  const props = useMemo<AppProps>(
    () => ({
      name,
      route,
      visible,
      session,
      navigate: (next, options) => {
        go(appHash(name, next), options?.replace === true);
      },
      href: (next) => appHash(name, next),
    }),
    [name, route, visible, session],
  );

  const panel = useMemo<PanelPlace>(() => ({ wide, slot }), [wide, slot]);

  return (
    <div
      className={visible ? "oneberth-app" : "oneberth-app oneberth-app-hidden"}
      data-app={name}
      inert={!visible}
      aria-hidden={visible ? undefined : true}
    >
      <AppContext.Provider value={props}>
        <PanelContext.Provider value={panel}>
          {loaded.status === "loading" && <p className="oneberth-app-note">Loading {app.title}…</p>}
          {loaded.status === "failed" && (
            <div className="oneberth-app-note">
              <p role="alert">{`${app.title} could not be loaded: ${loaded.detail}`}</p>
              <button
                type="button"
                className="oneberth-button"
                onClick={() => {
                  setLoaded({ status: "loading" });
                  setAttempt((count) => count + 1);
                }}
              >
                Try again
              </button>
            </div>
          )}
          {loaded.status === "ready" && (
            <AppBoundary title={app.title}>
              <loaded.Root {...props} />
            </AppBoundary>
          )}
        </PanelContext.Provider>
      </AppContext.Provider>
    </div>
  );
}

/** An application that throws while drawing shows that, and the rest of the shell stays. */
class AppBoundary extends Component<
  { title: string; children: ReactNode },
  { failure: string | null }
> {
  override state: { failure: string | null } = { failure: null };

  static getDerivedStateFromError(error: unknown): { failure: string } {
    return { failure: String(error) };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error(error, info.componentStack);
  }

  override render(): ReactNode {
    if (this.state.failure === null) return this.props.children;
    return (
      <div className="oneberth-app-note">
        <p role="alert">{`${this.props.title} stopped with an error: ${this.state.failure}`}</p>
        <button
          type="button"
          className="oneberth-button"
          onClick={() => {
            this.setState({ failure: null });
          }}
        >
          Try again
        </button>
      </div>
    );
  }
}
