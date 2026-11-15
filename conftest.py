# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""Fixtures shared by every package's tests.

They live at the root because pytest and mypy see the whole repository as one
run, and two directories cannot both hold a module called ``conftest``.
"""

from __future__ import annotations

import pytest

# Before the suites are imported, for pytest's detailed assertion messages.
pytest.register_assert_rewrite("oneberth.identity.testing")
