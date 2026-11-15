# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The launcher: it starts the desktop's parts, opens the window and stops them
(shapes.md, "The launcher" and "The window"). It imports no third-party code.

An application describes its backend, its workers and its data directory with
an ``Application``, and its command calls ``launch``. A backend reads where to
listen with ``LaunchedBackend``. A worker reads its name and the worker
listener's address with ``LaunchedWorker``, its token with ``read_token``, and
says it serves with ``say_ready``.

The logic lives in ``Launcher``, against the ports of ``_ports``.
``oneberth.launcher.testing`` holds stand-ins of the ports for tests.
"""

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
    LauncherError,
    Process,
    Run,
    Trust,
    Window,
    Worker,
)
from oneberth.launcher._entry import AsyncioTimer, launch, process_launcher
from oneberth.launcher._environment import (
    DATA_DIR,
    FRONT_PORT,
    FRONT_URL,
    HOST,
    LAUNCHER_PID,
    LOOPBACK,
    READY,
    TOKEN_FILE,
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
    Running,
    Runtime,
    Timer,
    Windows,
)
from oneberth.launcher._processes import ProcessRuntime
from oneberth.launcher._window import BrowserWindows, find_browser, window_command

__all__ = [
    "AGAIN",
    "BACKEND",
    "BACKEND_START_SECONDS",
    "BACKEND_STOP_SECONDS",
    "DATA_DIR",
    "FRONT_PORT",
    "FRONT_URL",
    "HOST",
    "LAUNCHER_PID",
    "LOCK_FILE",
    "LOOPBACK",
    "PROFILE_DIRECTORY",
    "READY",
    "RESERVED",
    "STATE_FILE",
    "TOKEN_FILE",
    "WINDOW",
    "WINDOW_STOP_SECONDS",
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
    "DataLock",
    "Ending",
    "HttpBackendApi",
    "LaunchedBackend",
    "LaunchedWorker",
    "Launcher",
    "LauncherError",
    "Outcome",
    "Process",
    "ProcessRuntime",
    "Run",
    "Running",
    "Runtime",
    "Timer",
    "Trust",
    "Window",
    "Windows",
    "Worker",
    "choose_front_port",
    "find_browser",
    "launch",
    "process_launcher",
    "profile_path",
    "read_token",
    "say_ready",
    "window_command",
]
