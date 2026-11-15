// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The small-screen layout's needs that CSS cannot meet: which layout is on,
 * and Tab kept inside the open drawer (shell.md, "A small screen").
 *
 * The breakpoint is the one of `shell.css`, read again through `matchMedia`,
 * because `inert`, the dialog role and the focus trap are set from React.
 * Both are written in `rem`, so a browser resolves them alike.
 */
import { useEffect, useSyncExternalStore, type RefObject } from "react";

export const WIDE = "(min-width: 48rem)";

function media(): MediaQueryList | null {
  try {
    return typeof window.matchMedia === "function" ? window.matchMedia(WIDE) : null;
  } catch {
    return null;
  }
}

function subscribe(changed: () => void): () => void {
  const query = media();
  if (query === null) return () => undefined;
  query.addEventListener("change", changed);
  return () => {
    query.removeEventListener("change", changed);
  };
}

/** Wide enough for the rail. Without `matchMedia`, the answer is wide. */
export function useWide(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => media()?.matches ?? true,
    () => true,
  );
}

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "select:not([disabled])",
  "input:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]",
]
  .map((one) => `${one}:not([tabindex="-1"])`)
  .join(", ");

/** The elements inside `node` that Tab stops on, in order. */
export function tabStops(node: HTMLElement): HTMLElement[] {
  const named = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (element) => element.closest("[hidden], [inert], [aria-hidden='true']") === null,
  );
  // jsdom lays nothing out and reports no boxes at all; a browser does.
  if (node.getClientRects().length === 0) return named;
  return named.filter((element) => element.getClientRects().length > 0);
}

/** While `open`, Tab and Shift+Tab go round inside `panel`. */
export function useTrappedFocus(panel: RefObject<HTMLElement | null>, open: boolean): void {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const node = panel.current;
      if (node === null) return;
      const stops = tabStops(node);
      const first = stops[0];
      const last = stops.at(-1);
      if (first === undefined || last === undefined) return;
      const active = document.activeElement;
      if (!node.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [panel, open]);
}
