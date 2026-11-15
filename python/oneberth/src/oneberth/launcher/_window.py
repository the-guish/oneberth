# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The window: Chrome or Chromium with ``--app``, on a profile of its own in
the data directory (shapes.md, "The window").

The launcher looks for Chrome, Chromium, Edge and Brave. Without one, the
default browser opens the address.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path

from oneberth.launcher._describe import Process, Window

LINUX_BROWSERS = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "microsoft-edge-stable",
    "brave-browser",
)
"""The executables the launcher looks for on the ``PATH`` of Linux, in order."""

MACOS_BROWSERS = (
    "Google Chrome.app/Contents/MacOS/Google Chrome",
    "Chromium.app/Contents/MacOS/Chromium",
    "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "Brave Browser.app/Contents/MacOS/Brave Browser",
)
"""The executables the launcher looks for under the applications of macOS, in order."""


def find_browser(
    platform: str,
    which: Callable[[str], str | None],
    is_file: Callable[[Path], bool],
    home: Path,
) -> str | None:
    """The first browser of the list that this machine has, or ``None``."""
    if platform == "darwin":
        for folder in (Path("/Applications"), home / "Applications"):
            for executable in MACOS_BROWSERS:
                if is_file(folder / executable):
                    return os.fspath(folder / executable)
        return None
    for name in LINUX_BROWSERS:
        found = which(name)
        if found:
            return found
    return None


def window_command(
    browser: str, profile: Path, url: str, arguments: Sequence[str]
) -> tuple[str, ...]:
    """What starts the window at ``url``."""
    return (
        browser,
        f"--user-data-dir={os.fspath(profile)}",
        f"--app={url}",
        "--no-first-run",
        "--no-default-browser-check",
        *arguments,
    )


class BrowserWindows:
    """Opens the window in Chrome or Chromium, or else in the default browser."""

    def __init__(self, window: Window, profile: Path) -> None:
        self._profile = profile
        self._arguments = window.arguments
        if window.browser is not None:
            self._browser: str | None = os.fspath(window.browser)
        else:
            self._browser = find_browser(
                sys.platform, shutil.which, Path.is_file, Path.home()
            )

    def window(self, url: str) -> Process | None:
        if self._browser is None:
            return None
        self._profile.mkdir(parents=True, exist_ok=True)
        return Process(
            window_command(self._browser, self._profile, url, self._arguments),
            quiet=True,
        )

    async def open_elsewhere(self, url: str) -> None:
        print(f"open {url}", flush=True)
        # Without a display, Python's choice is a browser of the terminal.
        display = os.environ.keys() & {"DISPLAY", "WAYLAND_DISPLAY"}
        if sys.platform == "darwin" or display:
            await asyncio.to_thread(webbrowser.open, url)
