// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ShellApp } from "../apps";
import { Shell } from "../Shell";
import { serve } from "../test/server";

const APPS: ShellApp[] = [
  { name: "alpha", title: "Alpha", icon: null, load: () => Promise.resolve({ default: () => <p>Alpha</p> }) },
];

function openAt(hash: string) {
  history.replaceState(null, "", `/${hash}`);
  render(<Shell apps={APPS} title="Test" />);
}

/** The poll of a pairing runs on a timer: the clock moves, nothing sleeps. */
async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("the account pages", () => {
  it("mints a personal token from a fresh sign-in, shows its secret once, and revokes it", async () => {
    const fake = serve();
    fake.makeStale();
    openAt("#/account/tokens");
    expect(await screen.findByText("No personal tokens.")).toBeInTheDocument();

    // A sign-in older than ten minutes: the page offers a fresh one, coming back here.
    fireEvent.click(screen.getByRole("button", { name: "New token" }));
    fireEvent.change(screen.getByLabelText("Name of the token"), { target: { value: "laptop" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByRole("heading", { name: "Sign in again to make a token" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in again with Okta" })).toHaveAttribute(
      "href",
      `/auth/login/okta?return_to=${encodeURIComponent("/#/account/tokens")}`,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    // Fresh: a name is needed, then the secret shows once.
    fake.signIn();
    fireEvent.click(screen.getByRole("button", { name: "New token" }));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(screen.getByRole("alert")).toHaveTextContent("A token needs a name.");
    fireEvent.change(screen.getByLabelText("Name of the token"), { target: { value: "laptop" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    const shown = await screen.findByRole("region", { name: "The new token" });
    expect(within(shown).getByText(/^ob_pat_/)).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Personal tokens" });
    expect(within(list).getByText("laptop")).toBeInTheDocument();
    fireEvent.click(within(shown).getByRole("button", { name: "Done" }));
    expect(screen.queryByText(/^ob_pat_/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Revoke laptop" }));
    expect(await screen.findByText("No personal tokens.")).toBeInTheDocument();
    expect(fake.tokens).toEqual([]);
    const write = fake.seen.find((one) => one.method === "POST" && one.url.endsWith("/auth/tokens"));
    expect(write?.headers.get("content-type")).toBe("application/json");
  });

  it("links a phone: the code waits, a phone claims it, a wrong number counts, the right one links", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fake = serve();
    openAt("#/account/devices");
    expect(await screen.findByText("No device is linked.")).toBeInTheDocument();

    // Closing the dialog while the code waits deletes the pairing.
    fireEvent.click(screen.getByRole("button", { name: "Link a phone" }));
    expect(await screen.findByText("Waiting for a phone to scan the code.")).toBeInTheDocument();
    expect(fake.pairings).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await tick(0);
    expect(fake.pairings).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Link a phone" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Link a phone" }));
    expect(await dialog.findByRole("img", { name: "QR code to scan with the app on your phone" })).toBeInTheDocument();
    const claimed = fake.claim(fake.latestCode() ?? "");
    expect(claimed).not.toBeNull();
    await tick(2000);
    expect(await dialog.findByText("A phone scanned your code. Type the number it shows.")).toBeInTheDocument();

    const field = dialog.getByLabelText("The number on the phone");
    fireEvent.change(field, { target: { value: "12345" } });
    fireEvent.click(dialog.getByRole("button", { name: "Link" }));
    expect(dialog.getByRole("alert")).toHaveTextContent("Type the six digits the phone shows.");
    fireEvent.change(field, { target: { value: "000 000" } });
    fireEvent.click(dialog.getByRole("button", { name: "Link" }));
    expect(await dialog.findByText("That is not the number. Two tries left.")).toBeInTheDocument();
    fireEvent.change(field, { target: { value: claimed?.number ?? "" } });
    fireEvent.click(dialog.getByRole("button", { name: "Link" }));
    expect(await dialog.findByText("Linked.")).toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "Done" }));

    const list = await screen.findByRole("list", { name: "Linked devices" });
    expect(within(list).getByText("Pixel 9")).toBeInTheDocument();
    expect(within(list).getByText("Android")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove Pixel 9" }));
    expect(await screen.findByText("No device is linked.")).toBeInTheDocument();
  });

  it("replaces a code that expires unclaimed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fake = serve();
    openAt("#/account/devices");
    fireEvent.click(await screen.findByRole("button", { name: "Link a phone" }));
    expect(await screen.findByText("Waiting for a phone to scan the code.")).toBeInTheDocument();
    const first = fake.latestCode();
    await tick(2 * 60_000 + 2000);
    await tick(2000);
    expect(await screen.findByText("Waiting for a phone to scan the code.")).toBeInTheDocument();
    expect(fake.latestCode()).not.toBeNull();
    expect(fake.latestCode()).not.toBe(first);
  });

  it("lets an admin make a service token with a role and a resource", async () => {
    const fake = serve({ roles: ["oneberth/admin"] });
    openAt("#/account/services");
    expect(await screen.findByText("No service tokens.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Service tokens" })).toHaveAttribute("aria-current", "page");

    fireEvent.click(screen.getByRole("button", { name: "New service token" }));
    fireEvent.change(screen.getByLabelText("Name of the token"), { target: { value: "worker-1" } });
    const role = screen.getByLabelText("Role");
    expect(await within(role).findByRole("option", { name: "neorc/worker" })).toBeInTheDocument();
    fireEvent.change(role, { target: { value: "neorc/worker" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(screen.getByRole("alert")).toHaveTextContent("The role neorc/worker needs a resource.");
    fireEvent.change(screen.getByLabelText("Resource"), { target: { value: "default" } });
    fireEvent.change(screen.getByLabelText("Days until it ends (empty for no end)"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(/^ob_svc_/)).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Service tokens" });
    expect(within(list).getByText("neorc/worker on default")).toBeInTheDocument();
    expect(within(list).getByText("Never")).toBeInTheDocument();
    expect(fake.services[0]).toMatchObject({ name: "worker-1", role: "neorc/worker", resource: "default", expires_at: null });

    fireEvent.click(screen.getByRole("button", { name: "Revoke worker-1" }));
    expect(await screen.findByText("No service tokens.")).toBeInTheDocument();
  });

  it("keeps the service tokens from a person who is no admin", async () => {
    serve();
    openAt("#/account/services");
    expect(await screen.findByRole("alert")).toHaveTextContent("There is no such account page.");
    expect(screen.queryByRole("link", { name: "Service tokens" })).toBeNull();
  });
});
