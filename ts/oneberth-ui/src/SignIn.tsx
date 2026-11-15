// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The page in place of every page until someone is signed in
 * (shell.md, "The account"; identity.md, "Through identity providers").
 *
 * One link per provider. Signing in is a navigation to
 * `/auth/login/{provider}?return_to=<where the person was>`; the backend
 * checks `return_to` again and comes back there. A failed sign-in comes back
 * to `#/sign-in?error=<code>`.
 *
 * The local mode has no sign-in page: the launcher opens the window signed
 * in. A local window whose session has ended says to start again.
 */
import type { Session } from "./session";
import "./signin.css";

/** What each code of a failed sign-in means, for a reader. A `Map`: the code comes from the address bar. */
export const SIGN_IN_ERRORS: ReadonlyMap<string, string> = new Map([
  ["expired", "The sign-in took too long, or its link was used already. Try again."],
  [
    "state_mismatch",
    "The sign-in came back to a different browser, or another sign-in began since. Try again.",
  ],
  [
    "not_allowed",
    "The provider knows who you are, but this deployment does not let that account in. Ask whoever runs it.",
  ],
  ["unknown_provider", "That is not a provider this deployment signs in with."],
  ["busy", "Too many sign-ins are under way. Try again in a few minutes."],
  ["provider_unavailable", "The identity provider could not be reached. Try again shortly."],
  ["provider_refused", "The identity provider did not sign you in."],
  [
    "invalid_id_token",
    "The identity provider's answer could not be trusted, so you were not signed in.",
  ],
]);

export const GENERIC_SIGN_IN_ERROR = "Signing in failed. Try again.";

/** The longest `return_to` a backend reads. */
const MAX_RETURN_TO = 512;

/**
 * Where to come back to once signed in: this page's path and a hash route.
 *
 * A path of this origin, printable ASCII, no backslash and no `//`, so that
 * the backend's own check passes it. The sign-in page itself is no place to
 * come back to; the shell's home stands in.
 */
export function returnTo(path: string, hash: string): string {
  const page = path.startsWith("/") && !path.startsWith("//") ? path : "/";
  const route =
    hash.startsWith("#/") && !hash.startsWith("#//") && !hash.startsWith("#/sign-in") ? hash : "";
  const target = page + route;
  if (target.includes("\\") || target.length > MAX_RETURN_TO) return page;
  for (const letter of target) {
    if (letter < "!" || letter > "~") return page;
  }
  return target;
}

/** The navigation that begins a sign-in with a provider, coming back to `hash`. */
export function loginHref(provider: string, hash: string): string {
  const target = encodeURIComponent(returnTo(location.pathname, hash));
  return `/auth/login/${encodeURIComponent(provider)}?return_to=${target}`;
}

function failure(code: string | null): string | null {
  if (code === null) return null;
  return SIGN_IN_ERRORS.get(code) ?? GENERIC_SIGN_IN_ERROR;
}

export function SignIn({
  session,
  title,
  error,
}: Readonly<{
  session: Session;
  /** The product's name: "Sign in to Robinauts". */
  title: string;
  /** The code a failed sign-in came back with. */
  error: string | null;
}>) {
  if (session.mode === "local") {
    return (
      <main className="oneberth-signin">
        <div className="oneberth-signin-card">
          <h1 className="oneberth-signin-title">{title}</h1>
          <p className="oneberth-signin-text">
            The session of this window has ended. Close the window and start {title} again.
          </p>
        </div>
      </main>
    );
  }
  const message = failure(error);
  const providers = session.providers;
  return (
    <main className="oneberth-signin">
      <div className="oneberth-signin-card">
        <h1 className="oneberth-signin-title">Sign in to {title}</h1>
        {message !== null && (
          <p role="alert" className="oneberth-signin-failed">
            {message}
          </p>
        )}
        {providers.length > 0 ? (
          <ul className="oneberth-signin-providers">
            {providers.map((provider) => (
              <li key={provider.id}>
                <a className="oneberth-signin-provider" href={loginHref(provider.id, location.hash)}>
                  Sign in with {provider.title}
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="oneberth-signin-text">
            This deployment has no identity provider configured. Ask whoever runs it.
          </p>
        )}
      </div>
    </main>
  );
}
