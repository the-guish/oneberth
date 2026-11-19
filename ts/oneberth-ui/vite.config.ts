// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

// The package ships its TypeScript source, and a host's build compiles it.
// `npm run build` builds that source once, the way a host would, as the gate
// that stands in for a build: React stays outside, the licence allowlist runs
// on anything else that would be bundled, and what the package adds to a
// host's bundle stays under a budget. `dist/` is never shipped.
//
// `npm run dev` serves the development page (`index.html`, `dev/`), with an
// in-memory stand-in for oneberth's `/auth` routes, or a real backend when
// ONEBERTH_UI_BACKEND names one.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { gzipSync } from "node:zlib";

import react from "@vitejs/plugin-react";
import license from "rollup-plugin-license";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

import { fakeAuthPlugin } from "./dev/vitePlugin.ts";

/** Licences a bundled package may carry: neorc's contributing/js-dependencies.md. */
const ALLOWED_LICENSES = [
  "MIT",
  "ISC",
  "0BSD",
  "BSD-2-Clause",
  "BSD-3-Clause",
  "Apache-2.0",
  "CC0-1.0",
  "Unlicense",
];

/** What the package adds to a host's bundle, gzipped. */
const SIZE_BUDGET_BYTES = 24 * 1024;

const here = import.meta.dirname;

/** The packages the build would bundle besides the package itself; written by the build. */
const BUNDLED_PACKAGES = resolve(here, "bundled-packages.txt");

function gzippedSize(dir: string): number {
  let total = 0;
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) total += gzippedSize(path);
    else if (!name.endsWith(".txt")) total += gzipSync(readFileSync(path)).length;
  }
  return total;
}

function sizeBudget(): Plugin {
  return {
    name: "oneberth-ui-size-budget",
    apply: "build",
    closeBundle() {
      const size = gzippedSize(resolve(here, "dist"));
      if (size > SIZE_BUDGET_BYTES) {
        throw new Error(
          `the package adds ${size} bytes gzipped to a bundle, over the budget of ${SIZE_BUDGET_BYTES}`,
        );
      }
      console.log(`@oneberth/ui adds ${size} bytes gzipped (budget ${SIZE_BUDGET_BYTES})`);
    },
  };
}

const backend = process.env.ONEBERTH_UI_BACKEND;

export default defineConfig({
  plugins: [react(), sizeBudget(), ...(backend ? [] : [fakeAuthPlugin()])],
  server: backend ? { proxy: { "/auth": backend } } : {},
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    // Stylesheets are left out, but for one read as text by a test.
    css: { include: [/\.css\?raw$/] },
    testTimeout: 20_000,
  },
  build: {
    lib: {
      entry: resolve(here, "src/index.ts"),
      formats: ["es"],
      fileName: "oneberth-ui",
      cssFileName: "oneberth-ui",
    },
    rollupOptions: {
      external: ["react", "react-dom", "react-dom/client", "react/jsx-runtime"],
      plugins: [
        license({
          thirdParty: {
            allow: {
              test: (dependency) => ALLOWED_LICENSES.includes(dependency.license ?? ""),
              failOnUnlicensed: true,
              failOnViolation: true,
            },
            output: [
              {
                file: BUNDLED_PACKAGES,
                template: (dependencies) =>
                  [
                    "# Packages the package brings into a host's bundle, written by the build.",
                    "# React and React DOM are peers and are not listed. A new line is reviewed.",
                    ...dependencies.map((d) => `${d.name} ${d.version} ${d.license}`).sort(),
                  ].join("\n") + "\n",
              },
            ],
          },
        }),
      ],
    },
  },
});
