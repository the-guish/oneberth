// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The hash routes of the shell (shell.md, "Routes").
 *
 * The first segment names the application: `#/neorc/runs/7` is the
 * application `neorc` with the route `/runs/7`. The shell's own pages are
 * `#/account/<page>` and `#/sign-in`, where a failed sign-in comes back with
 * `?error=<code>`.
 */
import { useSyncExternalStore } from "react";

/** The account pages. */
export const ACCOUNT_PAGES = ["tokens", "devices", "services"] as const;
export type AccountPage = (typeof ACCOUNT_PAGES)[number];

/** The first segments the shell keeps for itself. */
export const RESERVED_NAMES: readonly string[] = ["account", "sign-in"];

/** An application's name: a lowercase word that can be a path segment. */
export const APP_NAME = /^[a-z][a-z0-9-]*$/;

export type Place =
  | { kind: "home" }
  | { kind: "app"; app: string; route: string }
  | { kind: "account"; page: AccountPage | null }
  | { kind: "sign-in"; error: string | null };

/**
 * Where a hash points.
 *
 * An application's route is what follows its name: empty, or starting with
 * `/` or `?`. A segment that is no application name is still an `app` place;
 * the shell says it has nothing there.
 */
export function placeOf(hash: string): Place {
  const path = hash.replace(/^#/, "");
  if (path === "" || path === "/") return { kind: "home" };
  if (!path.startsWith("/")) return { kind: "home" };
  const rest = path.slice(1);
  const end = rest.search(/[/?]/);
  const first = end === -1 ? rest : rest.slice(0, end);
  const tail = end === -1 ? "" : rest.slice(end);
  if (first === "sign-in") {
    const query = tail.startsWith("?") ? tail.slice(1) : "";
    return { kind: "sign-in", error: new URLSearchParams(query).get("error") };
  }
  if (first === "account") {
    const page = tail.replace(/^\//, "").split(/[/?]/)[0] ?? "";
    const known = (ACCOUNT_PAGES as readonly string[]).includes(page);
    return { kind: "account", page: known ? (page as AccountPage) : null };
  }
  return { kind: "app", app: first, route: tail };
}

/** An application's route as the shell keeps it: empty, or from `/` or `?`. */
export function normalRoute(route: string): string {
  if (route === "" || route === "/") return "";
  if (route.startsWith("/") || route.startsWith("?")) return route;
  return `/${route}`;
}

/** The hash of an application's route. */
export function appHash(app: string, route: string): string {
  return `#/${app}${normalRoute(route)}`;
}

/** The hash of an account page. */
export function accountHash(page: AccountPage): string {
  return `#/account/${page}`;
}

const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of [...listeners]) listener();
}

function subscribe(listener: () => void): () => void {
  if (listeners.size === 0) window.addEventListener("hashchange", notify);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener("hashchange", notify);
  };
}

/** The current hash, kept up to date. */
export function useHash(): string {
  return useSyncExternalStore(
    subscribe,
    () => location.hash,
    () => "",
  );
}

/**
 * Go to a hash. `replace` takes the place of the current entry in the
 * history, and the shell is told, since replacing fires no `hashchange`.
 */
export function go(hash: string, replace = false): void {
  if (location.hash === hash) return;
  if (replace) {
    history.replaceState(history.state, "", hash);
    notify();
  } else {
    location.hash = hash;
  }
}
