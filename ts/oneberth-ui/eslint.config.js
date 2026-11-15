// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
  },
  {
    files: ["*.{js,mjs,ts}", "scripts/**", "dev/vitePlugin.ts"],
    languageOptions: { globals: globals.node },
  },
);
