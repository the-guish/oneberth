// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";

import { typedNumber } from "./account/account";
import { initials } from "./AccountMenu";
import { appHash, normalRoute, placeOf } from "./routes";
import { returnTo } from "./SignIn";
import { nextTheme } from "./theme";

describe("placeOf", () => {
  it.each([
    ["", { kind: "home" }],
    ["#", { kind: "home" }],
    ["#/", { kind: "home" }],
    ["#neorc", { kind: "home" }],
    ["#/neorc", { kind: "app", app: "neorc", route: "" }],
    ["#/neorc/", { kind: "app", app: "neorc", route: "/" }],
    ["#/neorc/runs/7", { kind: "app", app: "neorc", route: "/runs/7" }],
    ["#/neorc?flow=a", { kind: "app", app: "neorc", route: "?flow=a" }],
    ["#/robinauts/c/1?x=2", { kind: "app", app: "robinauts", route: "/c/1?x=2" }],
    ["#/account/tokens", { kind: "account", page: "tokens" }],
    ["#/account/devices", { kind: "account", page: "devices" }],
    ["#/account/services", { kind: "account", page: "services" }],
    ["#/account", { kind: "account", page: null }],
    ["#/account/nothing", { kind: "account", page: null }],
    ["#/sign-in", { kind: "sign-in", error: null }],
    ["#/sign-in?error=expired", { kind: "sign-in", error: "expired" }],
    ["#/sign-in?error=__proto__", { kind: "sign-in", error: "__proto__" }],
  ])("%s", (hash, place) => {
    expect(placeOf(hash)).toEqual(place);
  });
});

describe("normalRoute and appHash", () => {
  it.each([
    ["", ""],
    ["/", ""],
    ["/runs", "/runs"],
    ["runs", "/runs"],
    ["?a=1", "?a=1"],
  ])("%s", (route, normal) => {
    expect(normalRoute(route)).toBe(normal);
    expect(appHash("neorc", route)).toBe(`#/neorc${normal}`);
  });
});

describe("returnTo", () => {
  it.each([
    ["/ui/", "#/neorc/runs", "/ui/#/neorc/runs"],
    ["/", "#/account/tokens", "/#/account/tokens"],
    ["/ui/", "", "/ui/"],
    ["/ui/", "#/sign-in?error=expired", "/ui/"],
    ["/ui/", "#//evil.example", "/ui/"],
    ["//evil.example/", "#/neorc", "/#/neorc"],
    ["/ui/", "#/neorc/\\x", "/ui/"],
    ["/ui/", "#/neorc/a b", "/ui/"],
    ["/ui/", `#/neorc/${"a".repeat(600)}`, "/ui/"],
  ])("%s %s", (path, hash, target) => {
    expect(returnTo(path, hash)).toBe(target);
  });
});

describe("initials", () => {
  it.each([
    ["Ada Lovelace", "ada@example.com", "AL"],
    ["Grace Brewster Hopper", null, "GB"],
    ["ada", null, "A"],
    [null, "bob@example.com", "B"],
    ["  ", null, "?"],
    [null, null, "?"],
  ])("%s %s", (name, email, letters) => {
    expect(initials(name, email)).toBe(letters);
  });
});

describe("typedNumber", () => {
  it.each([
    ["482913", "482913"],
    ["482 913", "482913"],
    [" 482 913 ", "482913"],
    ["48291", null],
    ["4829134", null],
    ["48a913", null],
    ["482  913", null],
  ])("%s", (typed, number) => {
    expect(typedNumber(typed)).toBe(number);
  });
});

describe("nextTheme", () => {
  it.each([
    ["system", "light"],
    ["light", "dark"],
    ["dark", "system"],
  ] as const)("%s", (theme, next) => {
    expect(nextTheme(theme)).toBe(next);
  });
});
