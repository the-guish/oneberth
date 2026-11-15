# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""Helpers for testing oneberth and its adapters.

``ManualClock`` is a clock a test moves by hand. ``contracts`` holds the suite
every identity store passes, and needs pytest and pytest-asyncio.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
"""Where a ``ManualClock`` starts unless told otherwise."""


class ManualClock:
    """A clock that stands still until a test moves it. Pass it as ``clock``."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> datetime:
        """Move the clock forward by ``by``; the new time."""
        self.now += by
        return self.now


__all__ = ["START", "ManualClock"]
