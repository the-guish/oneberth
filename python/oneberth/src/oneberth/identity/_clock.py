# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""Where the identity core reads the time. Tests inject a clock of their own."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]
"""Returns the time now, aware and in UTC."""


def system_clock() -> datetime:
    """The machine's time, in UTC."""
    return datetime.now(UTC)
