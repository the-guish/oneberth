// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * Personal tokens, at `#/account/tokens` (identity.md, "Credentials").
 *
 * A personal token has the roles of its person and lives 90 days. It is a
 * bearer for a script. **New token** asks for a name and shows the secret
 * once; **Revoke** ends a token.
 */
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";

import { detailOf } from "../api";
import type { Session } from "../session";
import {
  listTokens,
  mintToken,
  needsFreshSignIn,
  revokeToken,
  useListed,
  type NewToken,
  type Token,
} from "./account";
import { EndButton, FreshSignIn, Items, Secret, When } from "./parts";

export const NO_TOKENS = "No personal tokens.";

type Making =
  | { kind: "idle" }
  | { kind: "naming" }
  | { kind: "fresh"; detail: string }
  | { kind: "made"; token: NewToken };

export function TokensPage({ session }: Readonly<{ session: Session }>) {
  const [round, setRound] = useState(0);
  const tokens = useListed(listTokens, round);
  const refresh = useCallback(() => {
    setRound((count) => count + 1);
  }, []);
  const [making, setMaking] = useState<Making>({ kind: "idle" });
  const opener = useRef<HTMLButtonElement>(null);
  const headingId = useId();
  const done = () => {
    setMaking({ kind: "idle" });
    opener.current?.focus();
  };
  return (
    <section aria-labelledby={headingId} className="oneberth-account-section">
      <div className="oneberth-account-head">
        <h1 id={headingId} className="oneberth-account-title">
          Personal tokens
        </h1>
        <button
          ref={opener}
          type="button"
          aria-expanded={making.kind === "naming"}
          aria-disabled={making.kind === "made"}
          onClick={() => {
            if (making.kind !== "made") setMaking({ kind: "naming" });
          }}
          className="oneberth-button"
        >
          New token
        </button>
      </div>
      <p className="oneberth-account-note">
        A personal token lets a script act as you, with your roles, for 90 days.
      </p>
      {making.kind === "naming" && (
        <NameForm
          label="Name of the token"
          onMade={(token) => {
            setMaking({ kind: "made", token });
            refresh();
          }}
          onFresh={(detail) => {
            setMaking({ kind: "fresh", detail });
          }}
          onCancel={done}
        />
      )}
      {making.kind === "fresh" && (
        <div className="oneberth-account-box">
          <h2 className="oneberth-account-box-title">Sign in again to make a token</h2>
          <FreshSignIn session={session} detail={making.detail} page="tokens" />
          <div className="oneberth-account-actions">
            <button type="button" onClick={done} className="oneberth-button">
              Cancel
            </button>
          </div>
        </div>
      )}
      {making.kind === "made" && (
        <Secret name={making.token.name} secret={making.token.secret} onDone={done} />
      )}
      <Items
        listed={tokens}
        empty={NO_TOKENS}
        label="Personal tokens"
        what="the tokens"
        row={(token) => <TokenRow key={token.id} token={token} onRevoked={refresh} />}
      />
    </section>
  );
}

function TokenRow({ token, onRevoked }: Readonly<{ token: Token; onRevoked: () => void }>) {
  return (
    <li className="oneberth-account-item">
      <div className="oneberth-account-what">
        <span className="oneberth-account-name">{token.name}</span>
      </div>
      <dl className="oneberth-account-dates">
        <div className="oneberth-account-date">
          <dt>Created</dt>
          <dd>
            <When instant={token.created_at} />
          </dd>
        </div>
        <div className="oneberth-account-date">
          <dt>Expires</dt>
          <dd>
            <When instant={token.expires_at} />
          </dd>
        </div>
      </dl>
      <EndButton
        label={`Revoke ${token.name}`}
        verb="Revoke"
        end={() => revokeToken(token.id)}
        onEnded={onRevoked}
      />
    </li>
  );
}

/** Asks for a name, and mints. */
function NameForm({
  label,
  onMade,
  onFresh,
  onCancel,
}: Readonly<{
  label: string;
  onMade: (token: NewToken) => void;
  onFresh: (detail: string) => void;
  onCancel: () => void;
}>) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const box = useRef<HTMLInputElement>(null);
  const boxId = useId();
  const errorId = useId();
  useEffect(() => {
    box.current?.focus();
  }, []);
  const make = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const trimmed = name.trim();
    if (trimmed === "") {
      setRefused("A token needs a name.");
      return;
    }
    setBusy(true);
    setRefused(null);
    try {
      onMade(await mintToken(trimmed));
    } catch (failure) {
      if (needsFreshSignIn(failure)) onFresh(detailOf(failure));
      else setRefused(detailOf(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      onSubmit={(event) => void make(event)}
      onKeyDown={(event) => {
        if (event.key === "Escape") onCancel();
      }}
      className="oneberth-account-box"
    >
      <label htmlFor={boxId} className="oneberth-account-label">
        {label}
      </label>
      <input
        ref={box}
        id={boxId}
        value={name}
        readOnly={busy}
        aria-invalid={refused !== null}
        aria-describedby={refused === null ? undefined : errorId}
        onChange={(event) => {
          setName(event.target.value);
        }}
        className="oneberth-input"
      />
      {refused !== null && (
        <p id={errorId} role="alert" className="oneberth-account-refused">
          {refused}
        </p>
      )}
      <div className="oneberth-account-actions">
        <button type="submit" aria-disabled={busy} className="oneberth-button oneberth-button-primary">
          Create
        </button>
        <button type="button" onClick={onCancel} className="oneberth-button">
          Cancel
        </button>
      </div>
    </form>
  );
}
