// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0
import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { resetSession } from "../session";

// The default of 1 s is short for a role query on a busy machine.
configure({ asyncUtilTimeout: 5000 });

// One test leaves nothing to the next: the DOM, the stubs, the hash, the
// storage, the theme on <html> and the session store.
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  history.replaceState(null, "", "/");
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  resetSession();
});
