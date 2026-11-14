#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright The Oneberth Authors
#
# The Python dependency licence gate: the policy of DEPENDENCIES.md over the
# whole locked set of uv.lock, read against the synced environment. The npm
# gate is part of scripts/check-npm.sh.
# Further arguments are passed on to the gate; see scripts/licence_gate.py --help.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

# Run under the synced environment: the gate reads the licence metadata of
# what is installed, and asks PyPI only about what this platform leaves out.
# The workspace's own packages are left out: they are ours, the gate stamps
# them Apache-2.0 without reading their metadata, and the tests import nothing
# of theirs. Left in, they would have to be built, and --no-build -- no
# package's code runs while the environment is made -- refuses that.
uv sync --locked --no-build --no-install-workspace
uv run --no-sync python "$root/scripts/licence_gate.py" "$@"
