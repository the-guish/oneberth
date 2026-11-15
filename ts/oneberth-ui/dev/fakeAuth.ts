// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * A stand-in for oneberth's `/auth` routes (identity.md, "Routes"), in
 * memory, for the component tests and the development page.
 *
 * It answers a `Request` with a `Response`, so a test puts it in place of
 * `fetch` and the development server puts it behind its middleware. It holds
 * one browser's state: who is signed in, how fresh the sign-in is, the
 * tokens, the devices, the pairings and the service tokens. It applies the
 * checks the package depends on: a 401 without a session, `application/json`
 * on a write, a fresh sign-in to mint a person's credential, and the pairing
 * rules of two minutes, one claim and three wrong numbers.
 *
 * It is not the backend. Shapes and codes follow the contract the package
 * reads; the Python side is the authority once it exists.
 */

export interface FakeUser {
  id: string;
  name: string | null;
  email: string | null;
  provider: string;
}

export interface FakeOptions {
  mode?: "providers" | "local";
  providers?: { id: string; title: string }[];
  user?: FakeUser;
  roles?: string[];
  /** Whether the browser starts signed in. */
  signedIn?: boolean;
  /** Milliseconds since the epoch; `Date.now` by default. */
  now?: () => number;
}

interface Stored {
  id: string;
  name: string;
  created_at: string;
  expires_at: string;
}

interface StoredDevice extends Stored {
  platform: string;
  last_used_at: string;
}

interface StoredService {
  id: string;
  name: string;
  role: string;
  resource: string | null;
  created_at: string;
  expires_at: string | null;
}

interface Pairing {
  id: string;
  code: string;
  expiresAt: number;
  state: "waiting" | "claimed" | "approved";
  number: string | null;
  wrong: number;
  device: { name: string; platform: string; app_version: string | null } | null;
}

const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;
const FRESH_MS = 10 * MINUTE;
const PAIRING_MS = 2 * MINUTE;
const TRIES = 3;

export const ADA: FakeUser = {
  id: "8d4c2b9e-0000-4000-8000-000000000001",
  name: "Ada Lovelace",
  email: "ada@example.com",
  provider: "okta",
};

export const SERVICE_ROLES = [
  { name: "neorc/worker", needs_resource: true },
  { name: "neorc/scheduler", needs_resource: false },
  { name: "neorc/ci", needs_resource: false },
  { name: "robinauts/worker", needs_resource: true },
];

function refusal(status: number, error: string, detail: string): Response {
  return Response.json({ error, detail }, { status });
}

export class FakeAuth {
  readonly mode: "providers" | "local";
  readonly providers: { id: string; title: string }[];
  user: FakeUser;
  roles: string[];
  signedIn: boolean;
  /** When the browser's session was signed in, in milliseconds. */
  signedInAt: number;
  tokens: Stored[] = [];
  devices: StoredDevice[] = [];
  services: StoredService[] = [];
  pairings: Pairing[] = [];
  /** Every request, for a test to look at. */
  readonly seen: Request[] = [];
  private readonly now: () => number;
  private counter = 0;

  constructor(options: FakeOptions = {}) {
    this.mode = options.mode ?? "providers";
    this.providers =
      this.mode === "local"
        ? []
        : (options.providers ?? [
            { id: "okta", title: "Okta" },
            { id: "google", title: "Google" },
          ]);
    this.user = options.user ?? ADA;
    this.roles = options.roles ?? ["neorc/user", "robinauts/user"];
    this.signedIn = options.signedIn ?? true;
    this.now = options.now ?? (() => Date.now());
    this.signedInAt = this.now();
  }

  /** The sign-in is older than ten minutes. */
  makeStale(): void {
    this.signedInAt = this.now() - FRESH_MS - 1;
  }

  /** A fresh sign-in, as a provider's callback makes one. */
  signIn(): void {
    this.signedIn = true;
    this.signedInAt = this.now();
  }

  /** The session ends on the server, as a revocation or its end does. */
  endSession(): void {
    this.signedIn = false;
  }

  /** The code of the latest pairing that waits, as the phone reads it from the QR. */
  latestCode(): string | null {
    const waiting = this.pairings.filter((one) => one.state === "waiting" && this.alive(one));
    return waiting.at(-1)?.code ?? null;
  }

  /** What a phone does with a code: claims it, and gets a secret and a number. */
  claim(
    code: string,
    device = { name: "Pixel 9", platform: "android", app_version: "1.0.0" as string | null },
  ): { secret: string; number: string } | null {
    const pairing = this.pairings.find((one) => one.code === code);
    if (pairing === undefined || pairing.state !== "waiting" || !this.alive(pairing)) return null;
    pairing.state = "claimed";
    pairing.device = device;
    pairing.number = String(100_000 + (this.next() % 900_000));
    pairing.expiresAt = this.now() + PAIRING_MS;
    return { secret: `ob_dev_${this.id()}`, number: pairing.number };
  }

  private next(): number {
    this.counter += 1;
    return this.counter * 7919;
  }

  private id(): string {
    this.counter += 1;
    return `00000000-0000-4000-8000-${String(this.counter).padStart(12, "0")}`;
  }

  private iso(at: number): string {
    return new Date(at).toISOString();
  }

  private alive(pairing: Pairing): boolean {
    return pairing.expiresAt > this.now();
  }

  private sessionBody() {
    const user = this.signedIn ? this.user : null;
    return {
      mode: this.mode,
      providers: this.providers,
      principal: user === null ? null : { kind: "user", ...user },
      roles: user === null ? [] : this.roles,
    };
  }

  private fresh(): boolean {
    return this.mode === "local" || this.now() - this.signedInAt < FRESH_MS;
  }

  /** Answer one request. */
  async handle(request: Request): Promise<Response> {
    this.seen.push(request);
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;
    const parts = path.split("/").filter(Boolean);

    if (method === "GET" && path === "/auth/session") return Response.json(this.sessionBody());

    if (method === "GET" && parts[1] === "login" && parts.length === 3) {
      if (!this.providers.some((one) => one.id === parts[2])) {
        return Response.redirect(new URL("/#/sign-in?error=unknown_provider", url), 303);
      }
      this.signIn();
      const target = url.searchParams.get("return_to") ?? "/";
      const safe = target.startsWith("/") && !target.startsWith("//") ? target : "/";
      return Response.redirect(new URL(safe, url), 303);
    }
    if (method === "GET" && path === "/auth/local") {
      if (this.mode !== "local") return refusal(404, "NotFound", "The local mode is off.");
      this.signIn();
      return Response.redirect(new URL("/", url), 303);
    }

    let body: Record<string, unknown> = {};
    if (method === "POST" || method === "PUT" || method === "PATCH") {
      const type = request.headers.get("content-type") ?? "";
      if (!type.startsWith("application/json")) {
        return refusal(415, "UnsupportedMediaType", "A write is application/json.");
      }
      if (request.headers.get("sec-fetch-site") === "cross-site") {
        return refusal(403, "CrossSite", "A cross-site write is refused.");
      }
      try {
        body = (await request.json()) as Record<string, unknown>;
      } catch {
        return refusal(422, "InvalidBody", "The body is not JSON.");
      }
    }

    if (method === "POST" && path === "/auth/pairings/claim") {
      const claimed = this.claim(String(body.code ?? ""));
      if (claimed === null) return refusal(404, "NotFound", "That code is not waiting.");
      return Response.json(claimed);
    }

    if (!this.signedIn) return refusal(401, "Unauthorized", "Nobody is signed in.");

    if (method === "POST" && path === "/auth/logout") {
      this.signedIn = false;
      return new Response(null, { status: 204 });
    }

    if (parts[1] === "tokens") return this.tokensRoute(method, parts, body);
    if (parts[1] === "devices") return this.devicesRoute(method, parts);
    if (parts[1] === "pairings") return this.pairingsRoute(method, parts, body);
    if (parts[1] === "services") return this.servicesRoute(method, parts, body);
    return refusal(404, "NotFound", `No route ${method} ${path}.`);
  }

  private tokensRoute(method: string, parts: string[], body: Record<string, unknown>): Response {
    if (parts.length === 2 && method === "GET") return Response.json({ items: this.tokens });
    if (parts.length === 2 && method === "POST") {
      if (!this.fresh()) {
        return refusal(403, "FreshSignInRequired", "Sign in again: the sign-in is older than ten minutes.");
      }
      const name = String(body.name ?? "").trim();
      if (name === "") return refusal(422, "InvalidBody", "A token needs a name.");
      const now = this.now();
      const token = {
        id: this.id(),
        name,
        created_at: this.iso(now),
        expires_at: this.iso(now + 90 * DAY),
      };
      this.tokens.push(token);
      return Response.json({ ...token, secret: `ob_pat_${this.id()}` }, { status: 201 });
    }
    if (parts.length === 3 && method === "DELETE") {
      const before = this.tokens.length;
      this.tokens = this.tokens.filter((one) => one.id !== parts[2]);
      if (this.tokens.length === before) return refusal(404, "NotFound", "No such token.");
      return new Response(null, { status: 204 });
    }
    return refusal(405, "MethodNotAllowed", "Not on this route.");
  }

  private devicesRoute(method: string, parts: string[]): Response {
    if (parts.length === 2 && method === "GET") return Response.json({ items: this.devices });
    if (parts.length === 3 && method === "DELETE") {
      const before = this.devices.length;
      this.devices = this.devices.filter((one) => one.id !== parts[2]);
      if (this.devices.length === before) return refusal(404, "NotFound", "No such device.");
      return new Response(null, { status: 204 });
    }
    return refusal(405, "MethodNotAllowed", "Not on this route.");
  }

  private pairingsRoute(method: string, parts: string[], body: Record<string, unknown>): Response {
    if (parts.length === 2 && method === "POST") {
      if (!this.fresh()) {
        return refusal(403, "FreshSignInRequired", "Sign in again: the sign-in is older than ten minutes.");
      }
      const id = this.id();
      const code = `c${this.next().toString(36)}`;
      const expiresAt = this.now() + PAIRING_MS;
      this.pairings.push({ id, code, expiresAt, state: "waiting", number: null, wrong: 0, device: null });
      return Response.json({ id, expires_at: this.iso(expiresAt), qr_svg: fakeQr(code) }, { status: 201 });
    }
    const pairing = this.pairings.find((one) => one.id === parts[2]);
    if (pairing === undefined || (pairing.state !== "approved" && !this.alive(pairing))) {
      return refusal(404, "NotFound", "The code is gone.");
    }
    if (parts.length === 3 && method === "GET") {
      return Response.json({
        state: pairing.state,
        expires_at: this.iso(pairing.expiresAt),
        device: pairing.device,
      });
    }
    if (parts.length === 3 && method === "DELETE") {
      this.pairings = this.pairings.filter((one) => one !== pairing);
      return new Response(null, { status: 204 });
    }
    if (parts.length === 4 && parts[3] === "approve" && method === "POST") {
      if (pairing.state !== "claimed") return refusal(409, "Conflict", "No phone has claimed the code.");
      const typed = String(body.number ?? "").replace(" ", "");
      if (typed !== pairing.number) {
        pairing.wrong += 1;
        if (pairing.wrong >= TRIES) this.pairings = this.pairings.filter((one) => one !== pairing);
        return refusal(403, "WrongNumber", "That is not the number.");
      }
      pairing.state = "approved";
      const now = this.now();
      const device: StoredDevice = {
        id: this.id(),
        name: pairing.device?.name ?? "Phone",
        platform: pairing.device?.platform ?? "other",
        created_at: this.iso(now),
        last_used_at: this.iso(now),
        expires_at: this.iso(now + 30 * DAY),
      };
      this.devices.push(device);
      return Response.json(device);
    }
    return refusal(405, "MethodNotAllowed", "Not on this route.");
  }

  private servicesRoute(method: string, parts: string[], body: Record<string, unknown>): Response {
    if (!this.roles.includes("oneberth/admin")) {
      return refusal(403, "Forbidden", "Service tokens need oneberth/tokens:manage.");
    }
    if (parts.length === 3 && parts[2] === "roles" && method === "GET") {
      return Response.json({ items: SERVICE_ROLES });
    }
    if (parts.length === 2 && method === "GET") return Response.json({ items: this.services });
    if (parts.length === 2 && method === "POST") {
      const role = SERVICE_ROLES.find((one) => one.name === body.role);
      if (role === undefined) return refusal(422, "UnknownRole", "No such role.");
      const resource = typeof body.resource === "string" ? body.resource : null;
      if (role.needs_resource !== (resource !== null)) {
        return refusal(422, "InvalidGrant", `The role ${role.name} needs ${role.needs_resource ? "a" : "no"} resource.`);
      }
      const now = this.now();
      const days = typeof body.days === "number" ? body.days : null;
      const token: StoredService = {
        id: this.id(),
        name: String(body.name ?? ""),
        role: role.name,
        resource,
        created_at: this.iso(now),
        expires_at: days === null ? null : this.iso(now + days * DAY),
      };
      this.services.push(token);
      return Response.json({ ...token, secret: `ob_svc_${this.id()}` }, { status: 201 });
    }
    if (parts.length === 3 && method === "DELETE") {
      const before = this.services.length;
      this.services = this.services.filter((one) => one.id !== parts[2]);
      if (this.services.length === before) return refusal(404, "NotFound", "No such token.");
      return new Response(null, { status: 204 });
    }
    return refusal(405, "MethodNotAllowed", "Not on this route.");
  }
}

/**
 * A picture standing in for a QR: a pattern from the code, and the code in a
 * `<desc>`, where a browser test reads it. The real backend draws a QR.
 */
export function fakeQr(code: string): string {
  const cells: string[] = [];
  let seed = 0;
  for (const letter of code) seed = (seed * 31 + letter.charCodeAt(0)) >>> 0;
  for (let y = 0; y < 21; y += 1) {
    for (let x = 0; x < 21; x += 1) {
      seed = (seed * 1103515245 + 12345) >>> 0;
      const finder = (x < 7 && y < 7) || (x > 13 && y < 7) || (x < 7 && y > 13);
      const on = finder ? x % 6 === 0 || y % 6 === 0 || (x % 7 > 1 && x % 7 < 5 && y % 7 > 1 && y % 7 < 5) : (seed & 8) !== 0;
      if (on) cells.push(`<rect x="${x + 2}" y="${y + 2}" width="1" height="1"/>`);
    }
  }
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 25 25" shape-rendering="crispEdges">` +
    `<desc>pairing-code:${code}</desc><rect width="25" height="25" fill="#fff"/>` +
    `<g fill="#000">${cells.join("")}</g></svg>`
  );
}
