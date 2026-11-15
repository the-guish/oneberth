# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""An application's desktop command, for the tests of the launcher.

    python launcher_process.py DATA_DIR BROWSER [BROWSER_ARGUMENT ...]

It describes the backend of ``launched_backend_process.py`` and two workers of
``launched_worker_process.py``, then calls ``launch``, as an application's
command does. ``w1`` prints more than a pipe holds once it is ready.
``ONEBERTH_TEST_FAILING_WORKER`` names a worker that ends with code 3 right
after it says ``ready``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from oneberth.launcher import Application, Backend, Process, Window, Worker, launch

HERE = Path(__file__).parent


def worker(name: str, queue: str) -> Worker:
    command = [sys.executable, os.fspath(HERE / "launched_worker_process.py"), queue]
    if os.environ.get("ONEBERTH_TEST_FAILING_WORKER") == name:
        command.append("3")
    environment = {"CHATTY": "1"} if name == "w1" else {}
    return Worker(name, "notes/worker", Process(command, environment), resource=queue)


def main() -> None:
    data_dir, browser, *arguments = sys.argv[1:]
    application = Application(
        name="notes",
        data_dir=data_dir,
        backend=Backend(
            Process([sys.executable, os.fspath(HERE / "launched_backend_process.py")])
        ),
        workers=[worker("w1", "gpu"), worker("w2", "cpu")],
        window=Window(browser, arguments),
    )
    raise SystemExit(launch(application))


if __name__ == "__main__":
    main()
