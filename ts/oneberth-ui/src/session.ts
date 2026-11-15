// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * Who is signed in, and signing out.
 *
 * `GET /auth/session` is asked once, when the page starts. It is never a 401:
 * "nobody is signed in" is an answer. A module-level store holds the answer,
 * and React reads it through `useSyncExternalStore`.
 *
 * Two events change it without asking: signing out, and any request answered
 * 401, which forgets the user at once. The sign-in page then stands in place
 * of every page, and keeps the providers of the last answer.
 */
import { useEffect, useSyncExternalStore } from "react";

import { ApiError, getJson, onUnauthorized, postJson } from "./api";

/** One provider the sign-in page offers a button for. */
export interface Provider {
  id: string;
  title: string;
}

/** A person, as `GET /auth/session` names them. */
export interface UserPrincipal {
  kind: "user";
  id: string;
  name: string | null;
  email: string | null;
  provider: string;
}

/** A program with a token of its own. */
export interface ServicePrincipal {
  kind: "service";
  id: string;
  name: string;
}

export type Principal = UserPrincipal | ServicePrincipal;

/** What `GET /auth/session` answers. */
export interface Session {
  /** How the deployment signs people in: through providers, or locally. */
  mode: "providers" | "local";
  /** The providers of the deployment; empty in the local mode. */
  providers: Provider[];
  /** Who is asking, or `null` when nobody is signed in. */
  principal: Principal | null;
  /** The roles of the principal; empty when nobody is signed in. */
  roles: string[];
  /**
   * For a phone whose claim waits on the person's approval: how the pairing
   * stands. `null` for everyone else, and absent from an older backend.
   */
  pairing?: { state: "waiting" | "claimed" | "approved" } | null;
}

/** The role whose holder manages the service tokens. */
export const ADMIN_ROLE = "oneberth/admin";

/** Whether the session's principal holds that role. */
export function hasRole(session: Session, role: string): boolean {
  return session.roles.includes(role);
}

/** The person signed in, or `null`. */
export function userOf(session: Session): UserPrincipal | null {
  return session.principal?.kind === "user" ? session.principal : null;
}

/**
 * Where the page stands.
 *
 * `session` is the last answer, kept after a sign-out for its providers.
 * It is `null` only while the first ask runs or when it failed; `error`
 * then says why.
 */
export interface SessionState {
  status: "loading" | "signed-in" | "signed-out";
  session: Session | null;
  error: ApiError | null;
}

const LOADING: SessionState = { status: "loading", session: null, error: null };

let state: SessionState = LOADING;
const listeners = new Set<() => void>();

function publish(next: SessionState): void {
  state = next;
  for (const listener of [...listeners]) listener();
}

export function subscribeSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function sessionSnapshot(): SessionState {
  return state;
}

function statusOf(session: Session): SessionState["status"] {
  return userOf(session) === null ? "signed-out" : "signed-in";
}

/**
 * Ask again who is signed in.
 *
 * A failure keeps the session there was: a dropped request is no sign-out.
 */
export async function loadSession(): Promise<void> {
  publish({
    status: state.session === null ? "loading" : state.status,
    session: state.session,
    error: null,
  });
  try {
    const session = await getJson<Session>("/auth/session");
    publish({ status: statusOf(session), session, error: null });
  } catch (failure) {
    publish({
      status: state.session === null ? "signed-out" : state.status,
      session: state.session,
      error:
        failure instanceof ApiError
          ? failure
          : new ApiError(0, "NetworkError", "The server could not be reached."),
    });
  }
}

let started = false;

/** The one ask a page makes. Called again, it does nothing. */
export function startSession(): Promise<void> {
  if (started) return Promise.resolve();
  started = true;
  return loadSession();
}

/** Back to a freshly loaded page; for tests. */
export function resetSession(): void {
  started = false;
  publish(LOADING);
}

/** Nobody is signed in, said without asking. The providers stay. */
function forgetUser(): void {
  if (state.session === null || userOf(state.session) === null) return;
  publish({
    status: "signed-out",
    session: { ...state.session, principal: null, roles: [] },
    error: null,
  });
}

/**
 * End the session, and ask again.
 *
 * A 401 is a session that had gone already. Any other refusal is thrown to
 * the caller, because the session is still open.
 */
export async function signOut(): Promise<void> {
  try {
    await postJson<void>("/auth/logout");
  } catch (failure) {
    if (!(failure instanceof ApiError && failure.status === 401)) throw failure;
  }
  forgetUser();
  await loadSession();
}

onUnauthorized(forgetUser);

/** The state, and the one ask that starts it. */
export function useSession(): SessionState {
  const current = useSyncExternalStore(subscribeSession, sessionSnapshot, sessionSnapshot);
  useEffect(() => {
    void startSession();
  }, []);
  return current;
}
