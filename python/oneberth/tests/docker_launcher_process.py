# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""An application's desktop command in the Docker shape, for the tests of
the launcher with Docker.

    python docker_launcher_process.py DATA_DIR BROWSER IMAGE FRONT_PORT

``IMAGE`` holds Python, the oneberth checkout and the programs of these
tests under ``/opt/tests``. The backend runs in it, as do a trusted worker on
``app``, which prints more than a pipe holds once it is ready, and an
untrusted worker on ``sandbox``. A third worker runs as a
process of the host. The window is the stand-in browser.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from oneberth.launcher import (
    Application,
    Backend,
    Container,
    Mount,
    Process,
    Trust,
    Window,
    Worker,
    launch,
)

HERE = Path(__file__).parent
IN_IMAGE = "/opt/tests"


def main() -> None:
    data_dir, browser, image, front_port = sys.argv[1:]

    def in_image(
        queue: str, environment: dict[str, str], mounts: tuple[Mount, ...] = ()
    ) -> Container:
        command = ["python", f"{IN_IMAGE}/launched_worker_process.py", queue]
        return Container(image, command, environment, mounts)

    host_worker = [sys.executable, os.fspath(HERE / "launched_worker_process.py")]
    application = Application(
        name="notes",
        data_dir=data_dir,
        backend=Backend(
            Process([sys.executable, os.fspath(HERE / "launched_backend_process.py")]),
            container=Container(
                image, ["python", f"{IN_IMAGE}/launched_backend_process.py"]
            ),
        ),
        workers=[
            Worker(
                "t1",
                "notes/worker",
                in_image("gpu", {"NOTE": "trusted", "CHATTY": "1"}),
                resource="gpu",
            ),
            Worker(
                "u1",
                "notes/worker",
                in_image("cpu", {"ENGINE": "echo"}, (Mount("workers/u1", "/state"),)),
                resource="cpu",
                trust=Trust.UNTRUSTED,
            ),
            Worker("p1", "notes/worker", Process([*host_worker, "io"]), resource="io"),
        ],
        front_port=int(front_port),
        window=Window(browser),
    )
    raise SystemExit(launch(application))


if __name__ == "__main__":
    main()
