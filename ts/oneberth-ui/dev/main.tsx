// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The development page: the shell with two sample applications, as a host
 * mounts it. `npm run dev` serves it, against the stand-in for `/auth`.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { applyRememberedTheme, Shell } from "../src";
import { SAMPLE_APPS } from "./sampleApps";

applyRememberedTheme();

const root = document.getElementById("root");
if (root === null) throw new Error("index.html has no #root");

createRoot(root).render(
  <StrictMode>
    <Shell apps={SAMPLE_APPS} title="Sample" />
  </StrictMode>,
);
