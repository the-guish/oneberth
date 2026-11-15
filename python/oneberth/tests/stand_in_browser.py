# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""A browser in Chrome's place, for the tests of the launcher.

    python stand_in_browser.py --user-data-dir=PROFILE --app=URL [...]

It opens ``URL`` with a jar of cookies, as the window does, then reads
``/notes/items`` with the session it got, and reports both to the test's probe.
It runs until SIGTERM, which closes the window. A second start on the same
profile hands its address to the first one and ends, as Chrome does: it
reports the address, and leaves it unopened for the test.
"""

from __future__ import annotations

import os
import signal
import socket
import sys
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlsplit


def report(text: str) -> None:
    with socket.create_connection(("127.0.0.1", int(os.environ["PROBE_PORT"]))) as to:
        to.sendall(f"{text}\n".encode())


def argument(name: str) -> str:
    return next(a for a in sys.argv[1:] if a.startswith(name)).removeprefix(name)


def running(pid_file: Path) -> bool:
    try:
        os.kill(int(pid_file.read_text()), 0)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return False
    return True


def main() -> None:
    profile, url = Path(argument("--user-data-dir=")), argument("--app=")
    pid_file = profile / "stand-in.pid"
    if running(pid_file):
        report(f"window forwarded {url}")
        return
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    pid_file.write_text(str(os.getpid()))
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar())
    )
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
    with opener.open(url, timeout=10) as page:
        landed = page.geturl().removeprefix(origin)
    with opener.open(f"{origin}/notes/items", timeout=10) as items:
        read = items.read().decode()
    report(f"window opened pid={os.getpid()} origin={origin} at={landed} items={read}")
    signal.sigwait({signal.SIGTERM})
    pid_file.unlink()


if __name__ == "__main__":
    main()
