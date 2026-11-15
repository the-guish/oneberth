// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * Service tokens, at `#/account/services`, for an admin
 * (identity.md, "Credentials").
 *
 * A service token names a program and holds one role, with one resource
 * when the role needs one, such as the queue of `neorc/worker`. **New
 * service token** asks for a name, a role, a resource and a life in days,
 * and shows the secret once.
 */
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";

import { detailOf } from "../api";
import type { Session } from "../session";
import {
  listServiceRoles,
  listServices,
  mintService,
  needsFreshSignIn,
  revokeService,
  useListed,
  type NewServiceToken,
  type ServiceRole,
  type ServiceToken,
} from "./account";
import { EndButton, FreshSignIn, Items, Secret, When } from "./parts";

export const NO_SERVICES = "No service tokens.";

type Making =
  | { kind: "idle" }
  | { kind: "form" }
  | { kind: "fresh"; detail: string }
  | { kind: "made"; token: NewServiceToken };

export function ServicesPage({ session }: Readonly<{ session: Session }>) {
  const [round, setRound] = useState(0);
  const tokens = useListed(listServices, round);
  const roles = useListed(listServiceRoles, 0);
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
          Service tokens
        </h1>
        <button
          ref={opener}
          type="button"
          aria-expanded={making.kind === "form"}
          aria-disabled={making.kind === "made"}
          onClick={() => {
            if (making.kind !== "made") setMaking({ kind: "form" });
          }}
          className="oneberth-button"
        >
          New service token
        </button>
      </div>
      <p className="oneberth-account-note">
        A service token lets a program, such as a worker or a CI job, act with one role.
      </p>
      {making.kind === "form" && (
        <ServiceForm
          roles={roles.status === "ready" ? roles.items : []}
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
          <FreshSignIn session={session} detail={making.detail} page="services" />
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
        empty={NO_SERVICES}
        label="Service tokens"
        what="the service tokens"
        row={(token) => <ServiceRow key={token.id} token={token} onRevoked={refresh} />}
      />
    </section>
  );
}

function ServiceRow({
  token,
  onRevoked,
}: Readonly<{ token: ServiceToken; onRevoked: () => void }>) {
  return (
    <li className="oneberth-account-item">
      <div className="oneberth-account-what">
        <span className="oneberth-account-name">{token.name}</span>
        <span className="oneberth-account-kind">
          {token.resource === null ? token.role : `${token.role} on ${token.resource}`}
        </span>
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
          <dd>{token.expires_at === null ? "Never" : <When instant={token.expires_at} />}</dd>
        </div>
      </dl>
      <EndButton
        label={`Revoke ${token.name}`}
        verb="Revoke"
        end={() => revokeService(token.id)}
        onEnded={onRevoked}
      />
    </li>
  );
}

const DEFAULT_DAYS = "90";

function ServiceForm({
  roles,
  onMade,
  onFresh,
  onCancel,
}: Readonly<{
  roles: ServiceRole[];
  onMade: (token: NewServiceToken) => void;
  onFresh: (detail: string) => void;
  onCancel: () => void;
}>) {
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [resource, setResource] = useState("");
  const [days, setDays] = useState(DEFAULT_DAYS);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const first = useRef<HTMLInputElement>(null);
  const ids = { name: useId(), role: useId(), resource: useId(), days: useId(), error: useId() };
  useEffect(() => {
    first.current?.focus();
  }, []);
  const chosen = roles.find((one) => one.name === role);
  const make = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const trimmed = name.trim();
    const daysText = days.trim();
    const life = daysText === "" ? null : Number(daysText);
    if (trimmed === "") return setRefused("A token needs a name.");
    if (role === "") return setRefused("A token needs a role.");
    if (chosen?.needs_resource === true && resource.trim() === "") {
      return setRefused(`The role ${role} needs a resource.`);
    }
    if (life !== null && !(Number.isInteger(life) && life > 0)) {
      return setRefused("The days are a whole number above zero, or empty for no end.");
    }
    setBusy(true);
    setRefused(null);
    try {
      onMade(
        await mintService({
          name: trimmed,
          role,
          resource: chosen?.needs_resource === true ? resource.trim() : null,
          days: life,
        }),
      );
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
      aria-describedby={refused === null ? undefined : ids.error}
    >
      <label htmlFor={ids.name} className="oneberth-account-label">
        Name of the token
      </label>
      <input
        ref={first}
        id={ids.name}
        value={name}
        readOnly={busy}
        onChange={(event) => {
          setName(event.target.value);
        }}
        className="oneberth-input"
      />
      <label htmlFor={ids.role} className="oneberth-account-label">
        Role
      </label>
      <select
        id={ids.role}
        value={role}
        disabled={busy}
        onChange={(event) => {
          setRole(event.target.value);
        }}
        className="oneberth-input"
      >
        <option value="">Choose a role</option>
        {roles.map((one) => (
          <option key={one.name} value={one.name}>
            {one.name}
          </option>
        ))}
      </select>
      {chosen?.needs_resource === true && (
        <>
          <label htmlFor={ids.resource} className="oneberth-account-label">
            Resource
          </label>
          <input
            id={ids.resource}
            value={resource}
            readOnly={busy}
            onChange={(event) => {
              setResource(event.target.value);
            }}
            className="oneberth-input"
          />
        </>
      )}
      <label htmlFor={ids.days} className="oneberth-account-label">
        Days until it ends (empty for no end)
      </label>
      <input
        id={ids.days}
        value={days}
        inputMode="numeric"
        readOnly={busy}
        onChange={(event) => {
          setDays(event.target.value);
        }}
        className="oneberth-input"
      />
      {refused !== null && (
        <p id={ids.error} role="alert" className="oneberth-account-refused">
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
