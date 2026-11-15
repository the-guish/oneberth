// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The stand-in for oneberth's `/auth` routes, put where the network is: in
 * place of `fetch`. Nothing of the package is mocked.
 */
import { vi } from "vitest";

import { FakeAuth, type FakeOptions } from "../../dev/fakeAuth";

export function serve(options: FakeOptions = {}): FakeAuth {
  const fake = new FakeAuth(options);
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : new URL(String(input), location.href).href;
    return fake.handle(new Request(url, init));
  });
  return fake;
}

/** A window narrower than the breakpoint: the drawer layout. */
export function narrowWindow(): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}
