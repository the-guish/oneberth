// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/** What the account pages share: dates, lists, a secret shown once, a fresh sign-in. */
import { useEffect, useRef, useState, type ReactNode } from "react";

import { detailOf } from "../api";
import { accountHash, type AccountPage } from "../routes";
import type { Session } from "../session";
import { loginHref } from "../SignIn";
import { shownDate, type Listed } from "./account";

/** An instant, in the browser's locale, with the instant itself on hover. */
export function When({ instant }: Readonly<{ instant: string }>) {
  return (
    <time dateTime={instant} title={instant}>
      {shownDate(instant)}
    </time>
  );
}

/** A list as it stands: loading, refused, empty, or its rows. */
export function Items<T>({
  listed,
  empty,
  label,
  what,
  row,
}: Readonly<{
  listed: Listed<T>;
  empty: string;
  label: string;
  what: string;
  row: (item: T) => ReactNode;
}>) {
  if (listed.status === "loading") return <p className="oneberth-account-note">Loading {what}…</p>;
  if (listed.status === "failed") {
    return (
      <p role="alert" className="oneberth-account-refused">
        {`The list of ${what} could not be loaded: ${listed.detail}`}
      </p>
    );
  }
  if (listed.items.length === 0) return <p className="oneberth-account-note">{empty}</p>;
  return (
    <ul aria-label={label} className="oneberth-account-list">
      {listed.items.map(row)}
    </ul>
  );
}

export const SHOWN_ONCE =
  "Copy it now. It will not be shown again: only its name and dates are kept.";

const COPIED_MS = 2000;

/** The secret of a token just made, once, with a way to copy it. */
export function Secret({
  name,
  secret,
  onDone,
}: Readonly<{ name: string; secret: string; onDone: () => void }>) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const done = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    done.current?.focus();
    return () => {
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, []);
  const copy = () => {
    const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard;
    // No clipboard on an insecure origin: selecting the text still works.
    if (typeof clipboard?.writeText !== "function") return;
    clipboard.writeText(secret).then(
      () => {
        if (timer.current !== null) clearTimeout(timer.current);
        setCopied(true);
        timer.current = setTimeout(() => {
          timer.current = null;
          setCopied(false);
        }, COPIED_MS);
      },
      () => undefined,
    );
  };
  return (
    <section aria-label="The new token" className="oneberth-account-box">
      <h3 className="oneberth-account-box-title">{`The token "${name}"`}</h3>
      <p className="oneberth-account-note">{SHOWN_ONCE}</p>
      <code className="oneberth-account-secret">{secret}</code>
      <div className="oneberth-account-actions">
        <button type="button" onClick={copy} className="oneberth-button oneberth-button-primary">
          {copied ? "Copied" : "Copy"}
        </button>
        <button ref={done} type="button" onClick={onDone} className="oneberth-button">
          Done
        </button>
      </div>
      <p aria-live="polite" className="oneberth-visually-hidden">
        {copied ? "The token is on the clipboard." : ""}
      </p>
    </section>
  );
}

/**
 * What a mint refused with `FreshSignInRequired` turns into: one way per
 * provider to sign in again, coming back to the account page.
 */
export function FreshSignIn({
  session,
  detail,
  page,
}: Readonly<{ session: Session; detail: string; page: AccountPage }>) {
  const providers = session.mode === "providers" ? session.providers : [];
  if (providers.length === 0) return <p className="oneberth-account-refused">{detail}</p>;
  return (
    <>
      <p className="oneberth-account-note">
        This needs a sign-in less than ten minutes old. You will come back to this page.
      </p>
      <ul className="oneberth-account-providers">
        {providers.map((provider) => (
          <li key={provider.id}>
            <a
              href={loginHref(provider.id, accountHash(page))}
              className="oneberth-button oneberth-button-primary"
            >
              Sign in again with {provider.title}
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}

/** A row's button that ends something, with the refusal beside it. */
export function EndButton({
  label,
  verb,
  end,
  onEnded,
}: Readonly<{
  /** The accessible name: "Revoke ci". */
  label: string;
  /** What the button says: "Revoke". */
  verb: string;
  end: () => Promise<unknown>;
  onEnded: () => void;
}>) {
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const run = async () => {
    if (busy) return;
    setBusy(true);
    setRefused(null);
    try {
      await end();
      onEnded();
    } catch (failure) {
      setRefused(detailOf(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="oneberth-account-row-actions">
      <button
        type="button"
        aria-label={label}
        aria-disabled={busy}
        onClick={() => void run()}
        className="oneberth-button"
      >
        {verb}
      </button>
      {refused !== null && (
        <p role="alert" className="oneberth-account-refused">
          {`Not done: ${refused}`}
        </p>
      )}
    </div>
  );
}
