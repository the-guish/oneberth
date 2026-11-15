// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

// The window's page: it reads a route that needs the local user's session.
fetch("/notes/items").then(async (answer) => {
  document.getElementById("items").textContent = await answer.text();
});
