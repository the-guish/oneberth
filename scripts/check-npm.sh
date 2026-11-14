#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright The Oneberth Authors
#
# Every gate the npm package has, in the order that fails fastest: the install
# from the lock, the licence gate, the gate's own tests, then the two audits,
# which are the only steps that need the network for anything but installing.
# Ported from Robinauts' scripts/check-frontend.sh, less what needs a bundle:
# there is no lint, type check or build to run yet (DEPENDENCIES.md, "The
# bundle").
#
# Takes no arguments: what it does is the whole of the npm job, and an
# argument that changed one step would quietly turn it off.
set -eu

if [ "$#" -ne 0 ]; then
    printf '%s takes no arguments (got: %s)\n' "$0" "$*" >&2
    exit 2
fi

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root/ts/oneberth-protocol"

# nvm, if this machine has it, so that a laptop with an older Node in its PATH
# runs the version .nvmrc names -- the one CI uses. It is a bash script, and
# this one is not, so the re-exec goes through bash; a machine without either
# carries on with whatever `node` is, and the version check below decides.
#
# Not on CI, whatever the runner has installed: setup-node has already put the
# Node of .nvmrc on the PATH, and sourcing nvm there would hand the job over to
# nvm's own default alias instead.
if [ -z "${CI:-}" ] && [ -z "${ONEBERTH_NODE_CHOSEN:-}" ] &&
    [ -s "$HOME/.nvm/nvm.sh" ] && command -v bash >/dev/null 2>&1; then
    ONEBERTH_NODE_CHOSEN=1
    export ONEBERTH_NODE_CHOSEN
    exec bash -c '. "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 && nvm use >/dev/null 2>&1
        exec "$@"' bash "$root/scripts/check-npm.sh" "$@"
fi

if ! command -v node >/dev/null 2>&1; then
    printf 'no node on the PATH; install the version in ts/oneberth-protocol/.nvmrc\n' >&2
    exit 2
fi

# .nvmrc may name a whole version, a line, or an alias; only the major is
# compared, and only when it is a number, because "lts/krypton" is not one.
nvmrc=$(cat .nvmrc)
wanted=${nvmrc%%.*}
running=$(node --version | sed 's/^v//; s/\..*//')
case $wanted in
    '' | *[!0-9]*)
        printf 'ts/oneberth-protocol/.nvmrc says %s, which is not a version to compare\n' \
            "$nvmrc" >&2
        exit 2
        ;;
    *) ;;
esac
if [ "$running" -lt "$wanted" ]; then
    printf 'node %s is older than the %s ts/oneberth-protocol/.nvmrc asks for\n' \
        "$(node --version)" "$wanted" >&2
    exit 2
fi

# --ignore-scripts as well as .npmrc: the file is the rule, this is the
# reminder that no package's own code runs while it is being installed.
npm ci --ignore-scripts

# The licence policy over everything installed, and the exact pins of
# package.json.
node scripts/check-licences.mjs

# The gate's refusals, over fixtures (node's own test runner: no dependency).
node --test tests/check-licences.test.mjs

# Advisories for everything installed; signatures and provenance for what
# ships. The registry does not serve attestations for every dev-only package,
# and a 404 there is not a reason to fail -- hence --omit=dev, as in Robinauts.
npm audit --audit-level=low

# npm refuses to verify an empty set ("found no installed dependencies to
# audit") and exits 1. Today the package has no dependency of any kind, so
# there is genuinely nothing to verify; the step runs the moment the lockfile
# pins a package that ships. The count is read from the lockfile npm ci has
# just installed from, the same file the licence gate reads.
shipped=$(node -e '
const lock = JSON.parse(require("node:fs").readFileSync("package-lock.json", "utf8"));
const entries = Object.entries(lock.packages ?? {});
console.log(entries.filter(([where, e]) => where !== "" && e.link !== true && e.dev !== true).length);
')
if [ "$shipped" -eq 0 ]; then
    printf 'npm audit signatures: the lockfile pins no package that ships, so there is no\n'
    printf 'signature to verify; it runs once one is added.\n'
else
    npm audit signatures --omit=dev
fi
