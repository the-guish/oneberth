// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * Light, dark, or what the operating system says (shell.md, "Styles").
 *
 * The choice is an attribute on `<html>`, which `tokens.css` reads:
 * `data-theme="light"`, `data-theme="dark"`, or none for the operating
 * system's. This browser remembers it.
 */
import { remember, remembered } from "./storage";

export type Theme = "system" | "light" | "dark";

export const THEME_KEY = "theme";

/** The order the toggle goes through. */
export const THEMES: readonly Theme[] = ["system", "light", "dark"];

export const THEME_LABELS: Readonly<Record<Theme, string>> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

function isTheme(value: string | null): value is Theme {
  return value === "system" || value === "light" || value === "dark";
}

/** What this browser chose last; the operating system's until it chooses. */
export function rememberedTheme(): Theme {
  const kept = remembered(THEME_KEY);
  return isTheme(kept) ? kept : "system";
}

/** Put the choice on `<html>`, and remember it. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
  remember(THEME_KEY, theme);
}

/**
 * The remembered choice, applied before the first paint. A host calls it
 * before it renders, so a dark choice on a light machine does not flash.
 */
export function applyRememberedTheme(): void {
  applyTheme(rememberedTheme());
}

/** The theme after this one. */
export function nextTheme(theme: Theme): Theme {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length] ?? "system";
}
