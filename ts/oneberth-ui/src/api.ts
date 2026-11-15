// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The request helper: same-origin requests, JSON writes, one error shape.
 *
 * A backend is served at the root of its origin, so a path such as
 * `/auth/session` or `/neorc/runs` is the address. The browser then sends the
 * session cookie, `Sec-Fetch-Site: same-origin` and an `Origin` the backend
 * checks a write against (identity.md, "Checks on a request").
 *
 * A write with a body is `application/json`, the one content type a backend
 * accepts. A POST without a body sends `{}`.
 *
 * Every refusal becomes an `ApiError` with the backend's `error` and
 * `detail`. A 401 tells the listeners of `onUnauthorized` first: the session
 * store listens and forgets the user.
 */

/** Every refusal of a backend, as composition.md writes it. */
export interface ErrorBody {
  error: string;
  detail: string;
}

/** A refusal, as something to catch. */
export class ApiError extends Error {
  readonly status: number;
  readonly error: string;
  readonly detail: string;

  constructor(status: number, error: string, detail: string) {
    super(`${status} ${error}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.error = error;
    this.detail = detail;
  }
}

/** Whether a failure is the backend refusing with the error of that name. */
export function isRefusal(failure: unknown, error: string): boolean {
  return failure instanceof ApiError && failure.error === error;
}

/** The sentence to show a person when a call did not work. */
export function detailOf(failure: unknown): string {
  if (failure instanceof ApiError) return failure.detail;
  if (failure instanceof Error) return failure.message;
  return String(failure);
}

const unauthorized = new Set<() => void>();

/**
 * Call `listener` whenever a request is answered 401. Returns the function
 * that stops it.
 */
export function onUnauthorized(listener: () => void): () => void {
  unauthorized.add(listener);
  return () => {
    unauthorized.delete(listener);
  };
}

/**
 * Tell the listeners that a request was answered 401.
 *
 * `request` does it itself. An application that reads a backend with its
 * own `fetch`, such as a stream, calls this, or `refused`, on a 401.
 */
export function reportUnauthorized(): void {
  for (const listener of [...unauthorized]) {
    try {
      listener();
    } catch {
      // A listener's own failure must not hide the refusal.
    }
  }
}

/** A response that is not ok, as an `ApiError`; a 401 is reported first. */
export async function refused(response: Response): Promise<ApiError> {
  if (response.status === 401) reportUnauthorized();
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON: a proxy's page, say. The status still names the failure.
  }
  if (isErrorBody(body)) return new ApiError(response.status, body.error, body.detail);
  return new ApiError(
    response.status,
    `HTTP${response.status}`,
    `The server answered ${response.status} ${response.statusText}`.trim(),
  );
}

function isErrorBody(body: unknown): body is ErrorBody {
  return (
    typeof body === "object" &&
    body !== null &&
    typeof (body as ErrorBody).error === "string" &&
    typeof (body as ErrorBody).detail === "string"
  );
}

export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  /** The JSON body of a write. */
  body?: unknown;
  /** Query parameters; an undefined or null value is left out. */
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

/** The path with its query, on this origin. */
export function withQuery(path: string, query: RequestOptions["query"]): string {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) search.set(name, String(value));
  }
  const tail = search.toString();
  return tail === "" ? path : `${path}?${tail}`;
}

/**
 * One request to a backend of this origin, answered with its JSON, or with
 * `undefined` for a 204.
 */
export async function request<T>(
  method: Method,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new TypeError(`a path on this origin starts with one "/": ${path}`);
  }
  const headers: Record<string, string> = { accept: "application/json" };
  const init: RequestInit = { method, headers, credentials: "same-origin" };
  if (options.signal !== undefined) init.signal = options.signal;
  const writes = method === "POST" || method === "PUT" || method === "PATCH";
  if (writes || options.body !== undefined) {
    headers["content-type"] = "application/json";
    init.body = JSON.stringify(options.body ?? {});
  }
  const response = await fetch(withQuery(path, options.query), init);
  if (!response.ok) throw await refused(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getJson<T>(
  path: string,
  query?: RequestOptions["query"],
  signal?: AbortSignal,
): Promise<T> {
  const options: RequestOptions = {};
  if (query !== undefined) options.query = query;
  if (signal !== undefined) options.signal = signal;
  return request<T>("GET", path, options);
}

export function postJson<T>(path: string, body: unknown = {}): Promise<T> {
  return request<T>("POST", path, { body });
}

export function deleteJson<T = void>(path: string): Promise<T> {
  return request<T>("DELETE", path);
}
