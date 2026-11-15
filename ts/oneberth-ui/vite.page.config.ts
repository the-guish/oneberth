// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

// The development page (`index.html`, `dev/`) built as a host builds its
// interface: one bundle, served under `/ui/` by a composed backend. The
// browser journey of the Python library runs on it. `dist-page/` is never
// shipped.
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const here = import.meta.dirname;

export default defineConfig({
  plugins: [react()],
  base: "/ui/",
  build: {
    outDir: resolve(here, "dist-page"),
    emptyOutDir: true,
  },
});
