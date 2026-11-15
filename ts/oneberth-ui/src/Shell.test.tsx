// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";

import { getJson } from "./api";
import { createCount, ShellPanel, useAppVisible, type AppProps, type ShellApp } from "./apps";
import { checkApps, Shell } from "./Shell";
import { narrowWindow, serve } from "./test/server";

/** What each sample application was told about being shown, in order. */
type Told = Record<string, boolean[]>;

function sampleApps(told: Told) {
  const count = createCount(2);
  function Visibility({ name }: Readonly<{ name: string }>) {
    const visible = useAppVisible();
    useEffect(() => {
      (told[name] ??= []).push(visible);
    }, [name, visible]);
    return null;
  }
  function Sample({ name, route, navigate, href }: Readonly<AppProps>) {
    return (
      <div>
        <Visibility name={name} />
        <ShellPanel>
          <nav aria-label={`${name} panel`}>
            <a href={href("/item/1")}>{`${name} item 1`}</a>
          </nav>
        </ShellPanel>
        <p>{`${name} at "${route}"`}</p>
        <label>
          {`${name} draft`}
          <input />
        </label>
        <button
          type="button"
          onClick={() => {
            navigate("/item/3");
          }}
        >
          {`${name}: open item 3`}
        </button>
        <button type="button" onClick={() => void getJson("/auth/tokens").catch(() => undefined)}>
          {`${name}: ask`}
        </button>
      </div>
    );
  }
  const alphaLoad = vi.fn(() => Promise.resolve({ default: Sample }));
  const betaLoad = vi.fn(() => Promise.resolve({ default: Sample }));
  const apps: ShellApp[] = [
    { name: "alpha", title: "Alpha", icon: <svg />, load: alphaLoad },
    { name: "beta", title: "Beta", icon: <svg />, load: betaLoad, count },
  ];
  return { apps, count, alphaLoad, betaLoad };
}

function rail() {
  return within(screen.getByRole("navigation", { name: "Applications" }));
}

/** A link click, as a browser follows it: the hash changes. */
async function follow(link: HTMLElement) {
  await act(async () => {
    location.hash = link.getAttribute("href") ?? "";
    await Promise.resolve();
  });
}

describe("the shell", () => {
  it("loads each application once, keeps it mounted, routes it and tells it when it is hidden", async () => {
    const fake = serve();
    const told: Told = {};
    const { apps, count, alphaLoad, betaLoad } = sampleApps(told);
    render(<Shell apps={apps} title="Test" />);

    // The home leads to the first application, which loads; the second waits.
    expect(await screen.findByText('alpha at ""')).toBeInTheDocument();
    expect(location.hash).toBe("#/alpha");
    expect(alphaLoad).toHaveBeenCalledTimes(1);
    expect(betaLoad).not.toHaveBeenCalled();
    expect(rail().getByRole("link", { name: "Alpha" })).toHaveAttribute("aria-current", "page");
    expect(rail().getByRole("link", { name: "Beta, 2" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("navigation", { name: "alpha panel" })).toBeInTheDocument();

    // The application changes its route through the shell, and types.
    fireEvent.change(screen.getByLabelText("alpha draft"), { target: { value: "half a thought" } });
    fireEvent.click(screen.getByRole("button", { name: "alpha: open item 3" }));
    expect(await screen.findByText('alpha at "/item/3"')).toBeInTheDocument();
    expect(location.hash).toBe("#/alpha/item/3");

    // Choosing the second application loads it, and hides the first.
    await follow(rail().getByRole("link", { name: "Beta, 2" }));
    expect(await screen.findByText('beta at ""')).toBeInTheDocument();
    expect(betaLoad).toHaveBeenCalledTimes(1);
    expect(told.alpha).toEqual([true, false]);
    expect(told.beta).toEqual([true]);
    const alphaPane = document.querySelector<HTMLElement>('.oneberth-app[data-app="alpha"]');
    expect(alphaPane).toHaveAttribute("inert");
    expect(screen.queryByText('alpha at "/item/3"')).not.toBeNull();

    // The first comes back on its last route, as it was left, without loading again.
    const alphaLink = rail().getByRole("link", { name: "Alpha" });
    expect(alphaLink).toHaveAttribute("href", "#/alpha/item/3");
    await follow(alphaLink);
    expect(await screen.findByLabelText("alpha draft")).toHaveValue("half a thought");
    expect(alphaPane).not.toHaveAttribute("inert");
    expect(alphaLoad).toHaveBeenCalledTimes(1);
    expect(told.alpha).toEqual([true, false, true]);
    expect(told.beta).toEqual([true, false]);
    expect(localStorage.getItem("oneberth.app")).toBe("alpha");
    expect(localStorage.getItem("oneberth.route.alpha")).toBe("/item/3");

    // The count is the application's.
    act(() => {
      count.set(120);
    });
    expect(rail().getByRole("link", { name: "Beta, 120" })).toHaveTextContent("99+");
    act(() => {
      count.set(0);
    });
    expect(rail().getByRole("link", { name: "Beta" })).toBeInTheDocument();

    // The theme toggle goes from the system's to light, to dark, and back.
    const theme = rail().getByRole("button", { name: /^Theme: System/ });
    fireEvent.click(theme);
    expect(document.documentElement.dataset.theme).toBe("light");
    fireEvent.click(rail().getByRole("button", { name: /^Theme: Light/ }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    fireEvent.click(rail().getByRole("button", { name: /^Theme: Dark/ }));
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(localStorage.getItem("oneberth.theme")).toBe("system");

    // The account menu: who is signed in, the account pages, sign-out.
    fireEvent.click(rail().getByRole("button", { name: "Account" }));
    const menu = within(screen.getByRole("group", { name: "Account" }));
    expect(menu.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(menu.getByText("ada@example.com")).toBeInTheDocument();
    expect(menu.queryByRole("link", { name: "Service tokens" })).toBeNull();
    await follow(menu.getByRole("link", { name: "Personal tokens" }));
    expect(await screen.findByRole("heading", { name: "Personal tokens" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Account" })).toBeNull();
    expect(told.alpha?.at(-1)).toBe(false);
    expect(await screen.findByText("No personal tokens.")).toBeInTheDocument();

    // A first segment that names no application.
    await act(async () => {
      location.hash = "#/nothing/here";
      await Promise.resolve();
    });
    expect(screen.getByRole("alert")).toHaveTextContent('There is no application named "nothing".');

    // Sign-out puts the sign-in page in place of every page.
    fireEvent.click(rail().getByRole("button", { name: "Account" }));
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in to Test" })).toBeInTheDocument();
    expect(fake.signedIn).toBe(false);
    expect(screen.getByRole("link", { name: "Sign in with Okta" })).toHaveAttribute(
      "href",
      `/auth/login/okta?return_to=${encodeURIComponent("/#/nothing/here")}`,
    );
  });

  it("goes back to the application and route this browser was on last", async () => {
    serve();
    localStorage.setItem("oneberth.app", "beta");
    localStorage.setItem("oneberth.route.beta", "/item/9");
    const { apps, alphaLoad } = sampleApps({});
    render(<Shell apps={apps} title="Test" />);
    expect(await screen.findByText('beta at "/item/9"')).toBeInTheDocument();
    expect(location.hash).toBe("#/beta/item/9");
    expect(alphaLoad).not.toHaveBeenCalled();
  });

  it("forgets the user when an application's request is answered 401", async () => {
    const fake = serve();
    const { apps } = sampleApps({});
    render(<Shell apps={apps} title="Test" />);
    fireEvent.click(await screen.findByRole("button", { name: "alpha: ask" }));
    expect(fake.seen.filter((one) => one.url.endsWith("/auth/session"))).toHaveLength(1);
    fake.endSession();
    fireEvent.click(screen.getByRole("button", { name: "alpha: ask" }));
    expect(await screen.findByRole("heading", { name: "Sign in to Test" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in with Google" })).toBeInTheDocument();
  });

  it("shows the service tokens to an admin, and no sign-out in the local mode", async () => {
    serve({ mode: "local", roles: ["neorc/user", "oneberth/admin"] });
    const { apps } = sampleApps({});
    render(<Shell apps={apps} title="Test" />);
    await screen.findByRole("navigation", { name: "Applications" });
    fireEvent.click(rail().getByRole("button", { name: "Account" }));
    const menu = within(screen.getByRole("group", { name: "Account" }));
    expect(menu.getByRole("link", { name: "Service tokens" })).toHaveAttribute("href", "#/account/services");
    expect(menu.queryByRole("button", { name: "Sign out" })).toBeNull();
  });

  it("says when an application could not be loaded, and loads it again on request", async () => {
    serve();
    const { apps } = sampleApps({});
    const first = apps[0] as ShellApp;
    let fails = true;
    const load = vi.fn(() =>
      fails ? Promise.reject(new Error("offline")) : Promise.resolve({ default: () => <p>Loaded at last</p> }),
    );
    render(<Shell apps={[{ ...first, load }, ...apps.slice(1)]} title="Test" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Alpha could not be loaded: Error: offline");
    fails = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Loaded at last")).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("puts the rail and the application's panel in a drawer on a small screen", async () => {
    narrowWindow();
    serve();
    const { apps } = sampleApps({});
    render(<Shell apps={apps} title="Test" />);
    expect(await screen.findByText('alpha at ""')).toBeInTheDocument();
    const opener = screen.getByRole("button", { name: "Open the menu" });
    expect(opener).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(opener);
    const drawer = within(screen.getByRole("dialog", { name: "Menu" }));
    expect(drawer.getByRole("link", { name: "Alpha" })).toHaveAttribute("aria-current", "page");
    expect(drawer.getByRole("button", { name: "Account" })).toBeInTheDocument();
    const item = drawer.getByRole("link", { name: "alpha item 1" });

    // Following a link in the drawer closes it.
    await follow(item);
    expect(await screen.findByText('alpha at "/item/1"')).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();

    // Escape closes it too.
    fireEvent.click(opener);
    expect(screen.getByRole("dialog", { name: "Menu" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  it.each([
    [[], "the shell needs at least one application"],
    [[{ name: "account" }], 'an application cannot be named "account"'],
    [[{ name: "Neorc" }], 'an application cannot be named "Neorc"'],
    [[{ name: "a" }, { name: "a" }], "two applications are named a"],
  ])("refuses the applications %j", (named, message) => {
    const apps = named.map(({ name }) => ({ name, title: name, icon: null, load: () => new Promise<never>(() => {}) }));
    expect(() => {
      checkApps(apps);
    }).toThrow(message);
  });
});
