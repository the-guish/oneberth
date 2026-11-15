// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * `@oneberth/ui`: the session, the sign-in page, the shell, the account
 * pages, the request helper and the design tokens (shell.md, "What
 * `@oneberth/ui` holds").
 */
export { Shell, checkApps, type ShellProps } from "./Shell";
export {
  ShellPanel,
  createCount,
  useAppVisible,
  useShellApp,
  type AppModule,
  type AppProps,
  type Count,
  type CountStore,
  type ShellApp,
} from "./apps";
export {
  ADMIN_ROLE,
  hasRole,
  loadSession,
  resetSession,
  signOut,
  useSession,
  userOf,
  type Principal,
  type Provider,
  type ServicePrincipal,
  type Session,
  type SessionState,
  type UserPrincipal,
} from "./session";
export { SignIn, SIGN_IN_ERRORS, loginHref } from "./SignIn";
export {
  ApiError,
  deleteJson,
  detailOf,
  getJson,
  isRefusal,
  onUnauthorized,
  postJson,
  refused,
  reportUnauthorized,
  request,
  type ErrorBody,
  type Method,
  type RequestOptions,
} from "./api";
export { applyRememberedTheme, applyTheme, rememberedTheme, type Theme } from "./theme";
