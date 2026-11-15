// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, deleteJson, getJson, onUnauthorized, postJson, request } from "./api";

/** A stand-in at the network boundary that records what it was sent. */
function network(answer: () => Response) {
  const sent: Request[] = [];
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
    sent.push(new Request(new URL(String(input), location.href), init));
    return Promise.resolve(answer());
  });
  return sent;
}

describe("the request helper", () => {
  const stops: (() => void)[] = [];
  afterEach(() => {
    for (const stop of stops.splice(0)) stop();
  });

  it("writes JSON, sends {} for a POST without a body, and reads a 204", async () => {
    const sent = network(() => new Response(null, { status: 204 }));
    await postJson("/auth/tokens", { name: "ci" });
    await postJson("/auth/logout");
    await deleteJson("/auth/tokens/1");
    await getJson("/neorc/runs", { flow: "a", before: undefined, root_only: true });
    expect(sent.map((one) => `${one.method} ${new URL(one.url).pathname}${new URL(one.url).search}`)).toEqual([
      "POST /auth/tokens",
      "POST /auth/logout",
      "DELETE /auth/tokens/1",
      "GET /neorc/runs?flow=a&root_only=true",
    ]);
    expect(sent[0]?.headers.get("content-type")).toBe("application/json");
    expect(await sent[0]?.text()).toBe('{"name":"ci"}');
    expect(await sent[1]?.text()).toBe("{}");
    expect(sent[2]?.headers.get("content-type")).toBeNull();
    expect(sent[3]?.headers.get("accept")).toBe("application/json");
  });

  it("turns a refusal into an ApiError, and tells the listeners of a 401 first", async () => {
    const told = vi.fn();
    stops.push(onUnauthorized(told));
    network(() => Response.json({ error: "Unauthorized", detail: "Nobody is signed in." }, { status: 401 }));
    const failure = await getJson("/neorc/runs").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 401, error: "Unauthorized", detail: "Nobody is signed in." });
    expect(told).toHaveBeenCalledTimes(1);
  });

  it("names the status of a refusal that is not the error shape", async () => {
    network(() => new Response("<html>bad gateway</html>", { status: 502, statusText: "Bad Gateway" }));
    await expect(getJson("/neorc/runs")).rejects.toMatchObject({
      status: 502,
      error: "HTTP502",
      detail: "The server answered 502 Bad Gateway",
    });
  });

  it.each(["auth/session", "//evil.example/auth", "https://evil.example/auth"])(
    "refuses the path %s, which is not one of this origin",
    async (path) => {
      await expect(request("GET", path)).rejects.toThrow(TypeError);
    },
  );
});
