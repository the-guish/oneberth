// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * Serves the in-memory stand-in for `/auth` (`./fakeAuth.ts`) from the
 * development server, for the development page.
 *
 * ONEBERTH_UI_MODE=local starts it in the local mode. The development-only
 * routes under `/__dev/` let a browser test act as the phone and age the
 * sign-in:
 *
 * - `GET /__dev/pairings/latest`: `{code}` of the latest pairing that waits;
 * - `POST /__dev/claim`: claims that pairing, answers `{secret, number}`;
 * - `POST /__dev/stale`: makes the sign-in older than ten minutes;
 * - `POST /__dev/end-session`: ends the session on the server;
 * - `POST /__dev/reset`: starts again from nothing.
 */
import type { IncomingMessage, ServerResponse } from "node:http";

import type { Plugin } from "vite";

import { FakeAuth, type FakeOptions } from "./fakeAuth.ts";

function options(): FakeOptions {
  const local = process.env.ONEBERTH_UI_MODE === "local";
  return {
    mode: local ? "local" : "providers",
    roles: ["neorc/user", "robinauts/user", "oneberth/admin"],
  };
}

async function readBody(req: IncomingMessage): Promise<Buffer> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks);
}

async function send(res: ServerResponse, response: Response): Promise<void> {
  res.statusCode = response.status;
  response.headers.forEach((value, name) => {
    res.setHeader(name, value);
  });
  res.end(Buffer.from(await response.arrayBuffer()));
}

function json(res: ServerResponse, status: number, body: unknown): void {
  res.statusCode = status;
  res.setHeader("content-type", "application/json");
  res.end(JSON.stringify(body));
}

export function fakeAuthPlugin(): Plugin {
  let fake = new FakeAuth(options());
  return {
    name: "oneberth-ui-fake-auth",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url ?? "/";
        if (url.startsWith("/__dev/")) {
          if (req.method === "GET" && url === "/__dev/pairings/latest") {
            json(res, 200, { code: fake.latestCode() });
          } else if (req.method === "POST" && url === "/__dev/claim") {
            const code = fake.latestCode();
            const claimed = code === null ? null : fake.claim(code);
            json(res, claimed === null ? 404 : 200, claimed ?? { error: "NotFound", detail: "No code waits." });
          } else if (req.method === "POST" && url === "/__dev/stale") {
            fake.makeStale();
            json(res, 200, {});
          } else if (req.method === "POST" && url === "/__dev/end-session") {
            fake.endSession();
            json(res, 200, {});
          } else if (req.method === "POST" && url === "/__dev/reset") {
            fake = new FakeAuth(options());
            json(res, 200, {});
          } else {
            json(res, 404, { error: "NotFound", detail: url });
          }
          return;
        }
        if (url !== "/auth" && !url.startsWith("/auth/") && !url.startsWith("/auth?")) {
          next();
          return;
        }
        void (async () => {
          const body = req.method === "GET" || req.method === "HEAD" ? null : await readBody(req);
          const headers = new Headers();
          for (const [name, value] of Object.entries(req.headers)) {
            if (typeof value === "string") headers.set(name, value);
          }
          const request = new Request(`http://${req.headers.host ?? "localhost"}${url}`, {
            method: req.method ?? "GET",
            headers,
            ...(body === null ? {} : { body: new Uint8Array(body) }),
          });
          await send(res, await fake.handle(request));
        })().catch(next);
      });
    },
  };
}
