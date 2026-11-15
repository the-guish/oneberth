// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The calls behind the account pages (identity.md, "Credentials", "Device
 * pairing", "Routes"), and the little state they share.
 *
 * Every call runs on the browser's session cookie. A person's credential is
 * minted from a session younger than ten minutes; an older one is refused
 * with `FreshSignInRequired`, and the page offers a fresh sign-in.
 */
import { useEffect, useState } from "react";

import { ApiError, deleteJson, detailOf, getJson, isRefusal, postJson } from "../api";

/** A personal token, as listed. The secret is never listed. */
export interface Token {
  id: string;
  name: string;
  created_at: string;
  expires_at: string;
}

/** A token just minted, with its secret, shown once. */
export interface NewToken extends Token {
  secret: string;
}

/** A linked device. */
export interface Device {
  id: string;
  name: string;
  platform: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
}

/** A pairing just minted: the code is in the picture alone. */
export interface MintedPairing {
  id: string;
  expires_at: string;
  qr_svg: string;
}

/** How a pairing is doing. */
export interface PairingView {
  state: "waiting" | "claimed" | "approved";
  expires_at: string;
  device: { name: string; platform: string; app_version: string | null } | null;
}

/** A service token, as listed. */
export interface ServiceToken {
  id: string;
  name: string;
  role: string;
  resource: string | null;
  created_at: string;
  /** `null` for a token without an end. */
  expires_at: string | null;
}

export interface NewServiceToken extends ServiceToken {
  secret: string;
}

/** A role a service token may hold. */
export interface ServiceRole {
  name: string;
  /** Whether a grant of it names one resource, such as a queue. */
  needs_resource: boolean;
}

export interface ServiceTokenRequest {
  name: string;
  role: string;
  resource: string | null;
  /** Days until it ends; `null` for no end. */
  days: number | null;
}

/** The refusal of a mint whose session is older than ten minutes (403). */
export const FRESH_SIGN_IN_REQUIRED = "FreshSignInRequired";
/** A number that is not the one the phone shows (403). */
export const WRONG_NUMBER = "WrongNumber";
/** More codes waiting than a person may have at once (429). */
export const BUSY = "Busy";
/** A deployment that allows no devices, among other refusals (403). */
export const FORBIDDEN = "Forbidden";
/** An approval of a pairing no phone has claimed (409). */
export const CONFLICT = "Conflict";

export function needsFreshSignIn(failure: unknown): boolean {
  return isRefusal(failure, FRESH_SIGN_IN_REQUIRED);
}

/** Whether a call was answered 404: what it named is gone. */
export function isGone(failure: unknown): boolean {
  return failure instanceof ApiError && failure.status === 404;
}

const id = encodeURIComponent;

export const listTokens = (signal: AbortSignal) =>
  getJson<{ items: Token[] }>("/auth/tokens", undefined, signal);
export const mintToken = (name: string) => postJson<NewToken>("/auth/tokens", { name });
export const revokeToken = (token: string) => deleteJson(`/auth/tokens/${id(token)}`);

export const listDevices = (signal: AbortSignal) =>
  getJson<{ items: Device[] }>("/auth/devices", undefined, signal);
export const removeDevice = (device: string) => deleteJson(`/auth/devices/${id(device)}`);

export const mintPairing = () => postJson<MintedPairing>("/auth/pairings");
export const pairingState = (pairing: string) =>
  getJson<PairingView>(`/auth/pairings/${id(pairing)}`);
export const approvePairing = (pairing: string, number: string) =>
  postJson<Device>(`/auth/pairings/${id(pairing)}/approve`, { number });
export const deletePairing = (pairing: string) => deleteJson(`/auth/pairings/${id(pairing)}`);

export const listServices = (signal: AbortSignal) =>
  getJson<{ items: ServiceToken[] }>("/auth/services", undefined, signal);
export const listServiceRoles = (signal: AbortSignal) =>
  getJson<{ items: ServiceRole[] }>("/auth/services/roles", undefined, signal);
export const mintService = (body: ServiceTokenRequest) =>
  postJson<NewServiceToken>("/auth/services", body);
export const revokeService = (token: string) => deleteJson(`/auth/services/${id(token)}`);

/** The QR as the `src` of an image: a picture runs nothing, whatever it holds. */
export function qrSource(svg: string): string {
  return `data:image/svg+xml;base64,${btoa(svg)}`;
}

const NUMBER = /^[0-9]{3} ?[0-9]{3}$/;

/** The six digits the phone shows, as the backend takes them, or `null`. */
export function typedNumber(typed: string): string | null {
  const trimmed = typed.trim();
  return NUMBER.test(trimmed) ? trimmed.replace(" ", "") : null;
}

const PLATFORMS = new Map([
  ["android", "Android"],
  ["ios", "iOS"],
  ["desktop", "Desktop"],
  ["other", "Other"],
]);

export function platformName(platform: string): string {
  return PLATFORMS.get(platform) ?? platform;
}

const DATES = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

/** An instant in the browser's locale; the text as it came if unreadable. */
export function shownDate(instant: string): string {
  const at = Date.parse(instant);
  return Number.isFinite(at) ? DATES.format(at) : instant;
}

/** A list, as far as its call has got. */
export type Listed<T> =
  | { status: "loading" }
  | { status: "ready"; items: T[] }
  | { status: "failed"; detail: string };

/**
 * The list `ask` answers, asked again whenever `round` changes. The list
 * stays on the screen while the next one comes. `ask` is a module function.
 */
export function useListed<T>(
  ask: (signal: AbortSignal) => Promise<{ items: T[] }>,
  round: number,
): Listed<T> {
  const [listed, setListed] = useState<Listed<T>>({ status: "loading" });
  useEffect(() => {
    const dropped = new AbortController();
    ask(dropped.signal).then(
      (answer) => {
        setListed({ status: "ready", items: answer.items });
      },
      (failure: unknown) => {
        if (!dropped.signal.aborted) setListed({ status: "failed", detail: detailOf(failure) });
      },
    );
    return () => {
      dropped.abort();
    };
  }, [ask, round]);
  return listed;
}
