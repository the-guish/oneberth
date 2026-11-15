// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The account button and its menu (shell.md, "The account"): the person's
 * name and email, personal tokens, linked devices, the service tokens for an
 * admin, and sign-out. The local mode has no sign-out: its session lasts
 * until the application stops.
 */
import { useEffect, useId, useRef, useState } from "react";

import { detailOf } from "./api";
import { accountPages, accountTitle } from "./account/AccountPages";
import { LogOutIcon } from "./icons";
import { accountHash } from "./routes";
import { signOut, userOf, type Session } from "./session";

/** Up to two letters for the button: the initials of the name, or of the email. */
export function initials(name: string | null, email: string | null): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length > 0) {
    return words
      .slice(0, 2)
      .map((word) => [...word][0]?.toUpperCase() ?? "")
      .join("");
  }
  const first = [...(email ?? "").trim()][0];
  return first === undefined ? "?" : first.toUpperCase();
}

export function AccountMenu({
  session,
  place,
}: Readonly<{ session: Session; place: "rail" | "drawer" }>) {
  const user = userOf(session);
  const [open, setOpen] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const menuId = useId();
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // The menu closes first; the drawer around it closes on the next Escape.
      event.stopImmediatePropagation();
      setOpen(false);
      button.current?.focus();
    };
    const onPointer = (event: PointerEvent) => {
      if (!(event.target instanceof Node) || box.current?.contains(event.target) !== true) {
        setOpen(false);
      }
    };
    const onHash = () => {
      setOpen(false);
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer);
    window.addEventListener("hashchange", onHash);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("hashchange", onHash);
    };
  }, [open]);

  if (user === null) return null;
  const name = user.name ?? user.email ?? "Signed in";

  const leave = async () => {
    if (busy) return;
    setBusy(true);
    setRefused(null);
    try {
      await signOut();
    } catch (failure) {
      setRefused(detailOf(failure));
      setBusy(false);
    }
  };

  return (
    <div ref={box} className="oneberth-account-menu-box">
      <button
        ref={button}
        type="button"
        title={name}
        aria-label="Account"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => {
          setOpen(!open);
        }}
        className="oneberth-rail-button oneberth-account-button"
      >
        <span aria-hidden="true">{initials(user.name, user.email)}</span>
      </button>
      {open && (
        <div
          id={menuId}
          role="group"
          aria-label="Account"
          className={`oneberth-account-menu oneberth-account-menu-${place}`}
        >
          <div className="oneberth-account-menu-who">
            <span className="oneberth-account-menu-name">{name}</span>
            {user.email !== null && user.email !== name && (
              <span className="oneberth-account-menu-email">{user.email}</span>
            )}
          </div>
          <ul className="oneberth-account-menu-links">
            {accountPages(session).map((page) => (
              <li key={page}>
                <a href={accountHash(page)} className="oneberth-account-menu-link">
                  {accountTitle(page)}
                </a>
              </li>
            ))}
          </ul>
          {session.mode === "providers" && (
            <button
              type="button"
              aria-disabled={busy}
              onClick={() => void leave()}
              className="oneberth-account-menu-link oneberth-account-menu-signout"
            >
              <LogOutIcon className="oneberth-account-menu-icon" />
              Sign out
            </button>
          )}
          {refused !== null && (
            <p role="alert" className="oneberth-account-menu-refused">
              {`Not signed out: ${refused}`}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
