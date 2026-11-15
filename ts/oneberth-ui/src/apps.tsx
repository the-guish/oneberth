// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * What an application gives the shell, and what the shell gives it back
 * (shell.md, "An application in the shell").
 *
 * The host registers each application as a `ShellApp`: its name, its title,
 * its icon, how to load its root component, and optionally its count. The
 * shell imports no application.
 *
 * The root component gets `AppProps`. A component deeper in the application
 * reads the same through `useShellApp()`. `ShellPanel` holds the
 * application's left panel: beside its pages on a wide screen, and in the
 * shell's drawer on a small one.
 */
import {
  createContext,
  useCallback,
  useContext,
  useSyncExternalStore,
  type ComponentType,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import type { Session } from "./session";

/** A number the rail shows on an application's icon, such as the tasks that wait. */
export interface CountStore {
  subscribe(listener: () => void): () => void;
  /** The count; `null` or 0 shows none. */
  get(): number | null;
}

/** A count an application sets. */
export interface Count extends CountStore {
  set(count: number | null): void;
}

/** A count store, for an application to set and the shell to show. */
export function createCount(initial: number | null = null): Count {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    get: () => value,
    set(next) {
      if (next === value) return;
      value = next;
      for (const listener of [...listeners]) listener();
    },
  };
}

/** What the shell passes an application's root component, and `useShellApp` returns. */
export interface AppProps {
  /** The application's name, the first segment of its routes. */
  name: string;
  /**
   * The application's route: what follows `#/<name>` in the hash. It is
   * empty, or starts with `/` or `?`. It changes only while the application
   * is shown.
   */
  route: string;
  /** Go to a route of this application. `replace` takes the current entry's place. */
  navigate: (route: string, options?: { replace?: boolean }) => void;
  /** The `href` of a route of this application, for a plain link. */
  href: (route: string) => string;
  /**
   * Whether the application is shown. A hidden application stops its long
   * polls, and reads again when it is shown.
   */
  visible: boolean;
  /** Who is signed in. */
  session: Session;
}

/** The module an application loads its root component from. */
export interface AppModule {
  default: ComponentType<AppProps>;
}

/** An application, as the host registers it with the shell. */
export interface ShellApp {
  /** The first segment of its routes: a lowercase word, not `account` or `sign-in`. */
  name: string;
  /** What the rail and the drawer call it. */
  title: string;
  /** The icon on the rail: an element, such as an SVG, 20 px square. */
  icon: ReactNode;
  /**
   * Loads the root component, the first time the application is chosen:
   * `() => import("./NeorcApp")` for a module whose default export it is.
   */
  load: () => Promise<AppModule>;
  /** The count on the icon. */
  count?: CountStore;
}

export const AppContext = createContext<AppProps | null>(null);

/** The shell's props for the application this component is part of. */
export function useShellApp(): AppProps {
  const props = useContext(AppContext);
  if (props === null) throw new Error("useShellApp() is used outside an application of the shell");
  return props;
}

/** Whether the application this component is part of is shown. */
export function useAppVisible(): boolean {
  return useShellApp().visible;
}

/** Where an application's panel goes: inline, or into its slot of the drawer. */
export interface PanelPlace {
  wide: boolean;
  slot: HTMLElement | null;
}

export const PanelContext = createContext<PanelPlace>({ wide: true, slot: null });

/**
 * The application's left panel.
 *
 * On a wide screen it stands where the application puts it. On a small
 * screen the shell draws it in the drawer, under the row of applications.
 * Crossing the breakpoint draws the panel again, so state it holds itself
 * starts over.
 */
export function ShellPanel({ children }: Readonly<{ children: ReactNode }>) {
  const place = useContext(PanelContext);
  if (place.wide) return <>{children}</>;
  if (place.slot === null) return null;
  return createPortal(children, place.slot);
}

/** The count of a store, or `null`. */
export function useCount(store: CountStore | undefined): number | null {
  const subscribe = useCallback(
    (listener: () => void) => (store === undefined ? () => undefined : store.subscribe(listener)),
    [store],
  );
  const get = () => (store === undefined ? null : store.get());
  return useSyncExternalStore(subscribe, get, get);
}
