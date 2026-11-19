// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";

import shellCss from "./shell.css?raw";

/** The declarations of the one rule whose selector is exactly `selector`. */
function declarations(css: string, selector: string): Map<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rule = new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, "m").exec(
    css.replace(/\/\*[\s\S]*?\*\//g, ""),
  );
  if (rule === null) throw new Error(`no rule for ${selector}`);
  const found = new Map<string, string>();
  for (const part of (rule[1] ?? "").split(";")) {
    const at = part.indexOf(":");
    if (at > 0) found.set(part.slice(0, at).trim(), part.slice(at + 1).trim());
  }
  return found;
}

describe("a hidden application", () => {
  // jsdom draws nothing, so no render test can see what a hidden pane
  // paints. A descendant with `visibility: visible` -- every node React Flow
  // has measured -- shows through `visibility: hidden`; only
  // `content-visibility: hidden` keeps the whole subtree off the screen.
  it("draws none of its subtree, and keeps its boxes", () => {
    const hidden = declarations(shellCss, ".oneberth-app-hidden");
    expect(hidden.get("content-visibility")).toBe("hidden");
    expect(hidden.get("visibility")).toBe("hidden");
    expect(hidden.get("pointer-events")).toBe("none");
    // `display: none` would lose the scroll positions shell.md keeps.
    expect(hidden.has("display")).toBe(false);
  });
});
