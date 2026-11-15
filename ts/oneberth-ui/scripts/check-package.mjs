// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

// The rules of shell.md, "How a package reaches an application", checked on
// what `npm pack` would ship: React and React DOM are the only peers, there
// is no runtime dependency and no install script, the TypeScript source is
// shipped, and the tests and the development page are not.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const here = new URL("..", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("package.json", here), "utf8"));
const failures = [];

const peers = Object.keys(manifest.peerDependencies ?? {}).sort();
if (peers.join(",") !== "react,react-dom") {
  failures.push(`the peers are ${peers.join(", ")}; they must be react and react-dom`);
}
for (const field of ["dependencies", "optionalDependencies", "bundleDependencies"]) {
  if (Object.keys(manifest[field] ?? {}).length > 0) failures.push(`${field} must be empty`);
}
const INSTALL_SCRIPTS = ["preinstall", "install", "postinstall", "prepare", "prepack", "postpack"];
for (const name of INSTALL_SCRIPTS) {
  if (manifest.scripts?.[name] !== undefined) failures.push(`the script ${name} must not exist`);
}
for (const [name, range] of Object.entries(manifest.devDependencies ?? {})) {
  if (!/^\d+\.\d+\.\d+$/.test(range)) failures.push(`${name} is pinned to ${range}, not an exact version`);
}
if (manifest.exports?.["."] !== "./src/index.ts") failures.push("the entry point must be ./src/index.ts");

const [packed] = JSON.parse(
  execFileSync("npm", ["pack", "--dry-run", "--json", "--ignore-scripts"], {
    cwd: here,
    encoding: "utf8",
  }),
);
const files = packed.files.map((file) => file.path);
for (const path of files) {
  if (/\.test\.tsx?$/.test(path) || path.startsWith("src/test/") || path.startsWith("dev/")) {
    failures.push(`${path} is shipped`);
  }
}
for (const needed of ["src/index.ts", "src/tokens.css", "LICENSE", "src/icons/LICENSE.lucide"]) {
  if (!files.includes(needed)) failures.push(`${needed} is not shipped`);
}

if (failures.length > 0) {
  console.error(failures.map((line) => `check-package: ${line}`).join("\n"));
  process.exit(1);
}
console.log(`check-package: ${files.length} files, React and React DOM as the only peers`);
