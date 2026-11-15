# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The launcher: it starts the desktop's parts, opens the window and stops them
(shapes.md, "The launcher" and "The window"). It imports no third-party code.

An application describes its backend, its workers and its data directory with
an ``Application``, and its command calls ``launch``. A component runs as a
``Process`` of the host or in a Docker ``Container``. One worker in a
container puts the application in the Docker shape (``_shape``). A backend
reads where to listen with ``LaunchedBackend``. A worker reads its name and the
worker listener's address with ``LaunchedWorker``, its token with
``read_token``, and says it serves with ``say_ready``.

The logic lives in ``Launcher``, ``DockerRuntime`` and ``_shape``, against
the ports of ``_ports``.
``oneberth.launcher.testing`` holds stand-ins of the ports for tests.
"""

from oneberth.launcher._containers import DockerRuntime, clean, launcher_user
from oneberth.launcher._core import AGAIN, Ending, Launcher, Outcome
from oneberth.launcher._data import (
    LOCK_FILE,
    PROFILE_DIRECTORY,
    STATE_FILE,
    AlreadyRunning,
    DataLock,
    choose_front_port,
    profile_path,
)
from oneberth.launcher._describe import (
    BACKEND,
    BACKEND_START_SECONDS,
    BACKEND_STOP_SECONDS,
    RESERVED,
    WINDOW,
    WINDOW_STOP_SECONDS,
    WORKER_START_SECONDS,
    WORKER_STOP_SECONDS,
    Application,
    Backend,
    Container,
    LauncherError,
    Mount,
    Process,
    Run,
    Trust,
    Window,
    Worker,
)
from oneberth.launcher._docker import DockerCli
from oneberth.launcher._entry import AsyncioTimer, desktop_launcher, launch
from oneberth.launcher._environment import (
    DATA_DIR,
    FRONT_BIND,
    FRONT_PORT,
    FRONT_URL,
    HOST,
    LAUNCHER_PID,
    LOOPBACK,
    READY,
    TOKEN_FILE,
    WORKER_BIND,
    WORKER_NAME,
    WORKER_PORT,
    WORKER_URL,
    LaunchedBackend,
    LaunchedWorker,
    read_token,
    say_ready,
)
from oneberth.launcher._http import HttpBackendApi
from oneberth.launcher._ports import (
    ApiFactory,
    BackendApi,
    Docker,
    Running,
    Runtime,
    Timer,
    Windows,
)
from oneberth.launcher._processes import ProcessRuntime
from oneberth.launcher._shape import (
    APP,
    CONTAINER_DATA_DIR,
    DATA_LABEL,
    FRONT_ALIAS,
    GATEWAY_NAME,
    PART_LABEL,
    SANDBOX,
    ContainerPlan,
    NetworkPlan,
    Shape,
    container_name,
    network_name,
    networks_of,
    shape_of,
)
from oneberth.launcher._window import BrowserWindows, find_browser, window_command

__all__ = [
    "AGAIN",
    "APP",
    "BACKEND",
    "BACKEND_START_SECONDS",
    "BACKEND_STOP_SECONDS",
    "CONTAINER_DATA_DIR",
    "DATA_DIR",
    "DATA_LABEL",
    "FRONT_ALIAS",
    "FRONT_BIND",
    "FRONT_PORT",
    "FRONT_URL",
    "GATEWAY_NAME",
    "HOST",
    "LAUNCHER_PID",
    "LOCK_FILE",
    "LOOPBACK",
    "PART_LABEL",
    "PROFILE_DIRECTORY",
    "READY",
    "RESERVED",
    "SANDBOX",
    "STATE_FILE",
    "TOKEN_FILE",
    "WINDOW",
    "WINDOW_STOP_SECONDS",
    "WORKER_BIND",
    "WORKER_NAME",
    "WORKER_PORT",
    "WORKER_START_SECONDS",
    "WORKER_STOP_SECONDS",
    "WORKER_URL",
    "AlreadyRunning",
    "ApiFactory",
    "Application",
    "AsyncioTimer",
    "Backend",
    "BackendApi",
    "BrowserWindows",
    "Container",
    "ContainerPlan",
    "DataLock",
    "Docker",
    "DockerCli",
    "DockerRuntime",
    "Ending",
    "HttpBackendApi",
    "LaunchedBackend",
    "LaunchedWorker",
    "Launcher",
    "LauncherError",
    "Mount",
    "NetworkPlan",
    "Outcome",
    "Process",
    "ProcessRuntime",
    "Run",
    "Running",
    "Runtime",
    "Shape",
    "Timer",
    "Trust",
    "Window",
    "Windows",
    "Worker",
    "choose_front_port",
    "clean",
    "container_name",
    "desktop_launcher",
    "find_browser",
    "launch",
    "launcher_user",
    "network_name",
    "networks_of",
    "profile_path",
    "read_token",
    "say_ready",
    "shape_of",
    "window_command",
]
