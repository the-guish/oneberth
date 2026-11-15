# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""Fixtures shared by every package's tests.

They live at the root because pytest and mypy see the whole repository as one
run, and two directories cannot both hold a module called ``conftest``.

The PostgreSQL tests run against a real server, named by
``ONEBERTH_TEST_DATABASE_URL``. They are marked ``postgres``, and skip when the
variable is not set.
"""

from __future__ import annotations

import os

import pytest

# Before the suites are imported, for pytest's detailed assertion messages.
pytest.register_assert_rewrite("oneberth.identity.testing")

DATABASE_URL_ENV = "ONEBERTH_TEST_DATABASE_URL"


@pytest.fixture(scope="session")
def database_url() -> str:
    """The PostgreSQL database the tests may use as they like."""
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        pytest.skip(f"no PostgreSQL: set {DATABASE_URL_ENV}")
    return url
