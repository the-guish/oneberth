# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""A worker as the launcher starts it, for the tests of the launcher.

    python launched_worker_process.py QUEUE [EXIT_CODE]

It reads its token from standard input and the worker listener's address from
its environment, claims on ``QUEUE`` there and reports the answer to the test's
probe, or prints it without one, then says ``ready``. On SIGTERM it claims
once more, which shows the backend still serves, reports it and ends. With
``EXIT_CODE``, it ends with that code right after ``ready``.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import urllib.error
import urllib.request

from oneberth.launcher import LaunchedWorker, read_token, say_ready

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def report(text: str) -> None:
    """Tell the test's probe, or print it for the launcher's log in a
    container, which gets no probe."""
    if "PROBE_PORT" not in os.environ:
        print(text, flush=True)
        return
    with socket.create_connection(("127.0.0.1", int(os.environ["PROBE_PORT"]))) as to:
        to.sendall(f"{text}\n".encode())


def claim(worker: LaunchedWorker, token: str, queue: str) -> str:
    request = urllib.request.Request(
        f"{worker.worker_url}/notes/queues/{queue}/claims",
        data=b"{}",
        method="POST",
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
        },
    )
    try:
        with _OPENER.open(request, timeout=10) as answer:
            return f"{answer.status} {json.dumps(json.load(answer), sort_keys=True)}"
    except urllib.error.HTTPError as error:
        return f"{error.code} {error.read().decode()}"
    except OSError as error:
        return f"unreachable {error}"


def main() -> None:
    worker = LaunchedWorker.from_environ()
    assert worker is not None, "started without a supervisor"
    queue = sys.argv[1]
    token = read_token()
    report(f"worker {worker.name} claimed {claim(worker, token, queue)}")
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    say_ready()
    if len(sys.argv) > 2:
        raise SystemExit(int(sys.argv[2]))
    signal.sigwait({signal.SIGTERM})
    report(f"worker {worker.name} stops {claim(worker, token, queue)}")


if __name__ == "__main__":
    main()
