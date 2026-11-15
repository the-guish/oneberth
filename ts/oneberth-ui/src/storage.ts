// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * What this browser remembers about the shell: the theme, the last
 * application, and the last route of each application.
 *
 * Keys start with `oneberth.`, because `localStorage` belongs to the whole
 * origin. Storage may be off, as in a private window that blocks site data,
 * so every read and write is wrapped.
 */
const PREFIX = "oneberth.";

export function remembered(key: string): string | null {
  try {
    return localStorage.getItem(PREFIX + key);
  } catch {
    return null;
  }
}

export function remember(key: string, value: string): void {
  try {
    localStorage.setItem(PREFIX + key, value);
  } catch {
    // Off, or full. The preference lasts as long as the page.
  }
}
