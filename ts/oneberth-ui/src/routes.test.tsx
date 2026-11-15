// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { go, useHash } from "./routes";

function Shown() {
  return <p>{useHash()}</p>;
}

afterEach(() => {
  cleanup();
  history.replaceState(history.state, "", "#");
});

describe("go", () => {
  // A new hash fires `hashchange` a moment later. Until then the page of the old route would
  // still be shown, and what a person types would go to it.
  it.each([
    ["a new entry", false],
    ["the current entry replaced", true],
  ])("shows the new route at once: %s", (_, replace) => {
    render(<Shown />);
    act(() => go("#/notes/7", replace));
    // No wait: `act` flushes React, and no event of the browser has run.
    expect(screen.getByText("#/notes/7")).toBeTruthy();
  });

  it("does nothing for the hash already shown", () => {
    history.replaceState(history.state, "", "#/notes/7");
    render(<Shown />);
    const before = history.length;
    act(() => go("#/notes/7"));
    expect(history.length).toBe(before);
    expect(screen.getByText("#/notes/7")).toBeTruthy();
  });
});
