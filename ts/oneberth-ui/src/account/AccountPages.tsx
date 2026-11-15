// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The account pages, under `#/account/…`, in the application's area
 * (shell.md, "The account"). An admin also sees the service tokens.
 */
import { accountHash, type AccountPage } from "../routes";
import { ADMIN_ROLE, hasRole, type Session } from "../session";
import { DevicesPage } from "./DevicesPage";
import { ServicesPage } from "./ServicesPage";
import { TokensPage } from "./TokensPage";
import "./account.css";

const TITLES: Readonly<Record<AccountPage, string>> = {
  tokens: "Personal tokens",
  devices: "Linked devices",
  services: "Service tokens",
};

/** The account pages this person may open, in the order the menu lists them. */
export function accountPages(session: Session): AccountPage[] {
  return hasRole(session, ADMIN_ROLE) ? ["tokens", "devices", "services"] : ["tokens", "devices"];
}

export function accountTitle(page: AccountPage): string {
  return TITLES[page];
}

export function AccountPages({
  session,
  page,
}: Readonly<{ session: Session; page: AccountPage | null }>) {
  const pages = accountPages(session);
  const open = page !== null && pages.includes(page) ? page : null;
  return (
    <main className="oneberth-account">
      <div className="oneberth-account-page">
        <nav aria-label="Account" className="oneberth-account-tabs">
          {pages.map((one) => (
            <a
              key={one}
              href={accountHash(one)}
              aria-current={one === open ? "page" : undefined}
              className="oneberth-account-tab"
            >
              {TITLES[one]}
            </a>
          ))}
        </nav>
        {open === "tokens" && <TokensPage session={session} />}
        {open === "devices" && <DevicesPage session={session} />}
        {open === "services" && <ServicesPage session={session} />}
        {open === null && (
          <p role="alert" className="oneberth-account-refused">
            There is no such account page.
          </p>
        )}
      </div>
    </main>
  );
}
