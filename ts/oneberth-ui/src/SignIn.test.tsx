// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ShellApp } from "./apps";
import { Shell } from "./Shell";
import { GENERIC_SIGN_IN_ERROR, SIGN_IN_ERRORS } from "./SignIn";
import { serve } from "./test/server";

const load = vi.fn(() => Promise.resolve({ default: () => <p>Alpha</p> }));
const APPS: ShellApp[] = [{ name: "alpha", title: "Alpha", icon: null, load }];

function openAt(path: string) {
  history.replaceState(null, "", path);
  render(<Shell apps={APPS} title="Test" />);
}

describe("the sign-in page", () => {
  it("stands in place of every page, with a link per provider back to where the person was", async () => {
    load.mockClear();
    serve({ signedIn: false });
    openAt("/ui/#/alpha/item/4");
    expect(await screen.findByRole("heading", { name: "Sign in to Test" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in with Okta" })).toHaveAttribute(
      "href",
      `/auth/login/okta?return_to=${encodeURIComponent("/ui/#/alpha/item/4")}`,
    );
    expect(screen.getByRole("link", { name: "Sign in with Google" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(load).not.toHaveBeenCalled();
  });

  it.each([
    ["expired", SIGN_IN_ERRORS.get("expired")],
    ["not_allowed", SIGN_IN_ERRORS.get("not_allowed")],
    ["something_new", GENERIC_SIGN_IN_ERROR],
    ["__proto__", GENERIC_SIGN_IN_ERROR],
  ])("says what the code %s of a failed sign-in means", async (code, sentence) => {
    serve({ signedIn: false });
    openAt(`/#/sign-in?error=${code}`);
    expect(await screen.findByRole("alert")).toHaveTextContent(sentence ?? "");
    expect(screen.getByRole("link", { name: "Sign in with Okta" })).toHaveAttribute(
      "href",
      `/auth/login/okta?return_to=${encodeURIComponent("/")}`,
    );
  });

  it("leads a signed-in person from the sign-in route to the application", async () => {
    serve();
    openAt("/#/sign-in?error=expired");
    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(location.hash).toBe("#/alpha");
  });

  it("asks a local window whose session ended to start again, with no providers", async () => {
    serve({ mode: "local", signedIn: false });
    openAt("/");
    expect(
      await screen.findByText("The session of this window has ended. Close the window and start Test again."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("asks again when the first ask for the session fails", async () => {
    const fake = serve();
    let down = true;
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      down
        ? Promise.reject(new TypeError("Failed to fetch"))
        : fake.handle(new Request(new URL(String(input), location.href), init)),
    );
    openAt("/");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Who is signed in could not be read: The server could not be reached.",
    );
    down = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Alpha")).toBeInTheDocument();
  });
});
