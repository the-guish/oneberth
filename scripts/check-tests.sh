#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright The Oneberth Authors
#
# pytest over tests/: today, the tests of the checks themselves. Further
# arguments are passed on to pytest.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

# The workspace's own packages are left out: the tests import nothing of
# theirs yet. Left in, they would have to be built, and --no-build -- no
# package's code runs while the environment is made -- refuses that.
uv sync --locked --no-build --no-install-workspace
uv run --no-sync pytest "$@"
