# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The launcher with real processes: an application's command calls ``launch``
on a real backend in the local mode, two small workers and a window.

The workers present their tokens on the worker listener. The window opens on
the ticket's address and reads a route with its session. The browser is a
stand-in in Chrome's place, or the real Chromium that
``ONEBERTH_TEST_CHROMIUM`` names. Each part reports to a probe the test
listens on. After each stop, no process of the data directory is left.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).parent
LAUNCHER = HERE / "launcher_process.py"
STAND_IN_BROWSER = HERE / "stand_in_browser.py"
CHROMIUM_ENV = "ONEBERTH_TEST_CHROMIUM"
TIMEOUT_SECONDS = 60


class Probe:
    """The lines the parts report, as they arrive."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.port = 0
        self._heard = asyncio.Event()

    async def accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        async for line in reader:
            self.lines.append(line.decode().strip())
            self._heard.set()
        writer.close()

    async def heard(self, prefix: str) -> str:
        """The first line that starts with ``prefix``, once it arrives."""
        async with asyncio.timeout(TIMEOUT_SECONDS):
            while True:
                for index, line in enumerate(self.lines):
                    if line.startswith(prefix):
                        return self.lines.pop(index)
                self._heard.clear()
                await self._heard.wait()


def left_behind(data: Path) -> list[int]:
    """The processes whose environment names ``data`` as their data directory."""
    marker = f"ONEBERTH_DATA_DIR={data}".encode()
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            environment = (entry / "environ").read_bytes()
        except OSError:
            continue
        if marker in environment.split(b"\0"):
            found.append(int(entry.name))
    return found


class Desktop:
    """Starts the test application's command on one data directory."""

    def __init__(self, tmp_path: Path, probe: Probe) -> None:
        self.data = tmp_path / "data"
        self.probe = probe
        self.started: list[asyncio.subprocess.Process] = []
        self.logs = tmp_path / "launcher.log"
        self.stand_in = tmp_path / "browser"
        self.stand_in.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{STAND_IN_BROWSER}" "$@"\n'
        )
        self.stand_in.chmod(0o755)

    async def launch(
        self,
        browser: str | None = None,
        arguments: Sequence[str] = (),
        environment: dict[str, str] | None = None,
    ) -> asyncio.subprocess.Process:
        with self.logs.open("ab") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                os.fspath(LAUNCHER),
                os.fspath(self.data),
                browser or os.fspath(self.stand_in),
                *arguments,
                env={
                    **os.environ,
                    "PROBE_PORT": str(self.probe.port),
                    **(environment or {}),
                },
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log,
                stderr=log,
            )
        self.started.append(process)
        return process

    async def ended(self, process: asyncio.subprocess.Process) -> int:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            return await process.wait()

    @property
    def front_port(self) -> int:
        port: int = json.loads((self.data / "launcher.json").read_text())["front_port"]
        return port


@pytest.fixture
async def desktop(tmp_path: Path) -> AsyncIterator[Desktop]:
    probe = Probe()
    server = await asyncio.start_server(probe.accept, "127.0.0.1", 0)
    probe.port = server.sockets[0].getsockname()[1]
    desktop = Desktop(tmp_path, probe)
    try:
        yield desktop
    finally:
        for process in desktop.started:
            if process.returncode is None:
                process.kill()
                await process.wait()
        for pid in left_behind(desktop.data):
            os.kill(pid, signal.SIGKILL)
        server.close()
        await server.wait_closed()


def fields(line: str) -> dict[str, str]:
    return dict(word.split("=", 1) for word in line.split(" ") if "=" in word)


async def test_the_desktop_starts_comes_forward_closes_and_starts_again(
    desktop: Desktop,
) -> None:
    probe = desktop.probe
    first = await desktop.launch()
    claims = sorted([await probe.heard("worker w1 "), await probe.heard("worker w2 ")])
    assert claims == [
        'worker w1 claimed 200 {"by": "w1", "queue": "gpu"}',
        'worker w2 claimed 200 {"by": "w2", "queue": "cpu"}',
    ]
    window = fields(await probe.heard("window opened"))
    assert window["origin"] == f"http://127.0.0.1:{desktop.front_port}"
    assert (window["at"], window["items"]) == ("/ui/", '{"for":"Ada"}')
    assert (desktop.data / "window").is_dir()

    second = await desktop.launch()
    assert await desktop.ended(second) == 0
    forwarded = (await probe.heard("window forwarded ")).split(" ")[-1]
    async with httpx.AsyncClient(trust_env=False) as browser:
        signed_in = await browser.get(forwarded)
        assert signed_in.headers["location"] == f"{window['origin']}/ui/"

    os.kill(int(window["pid"]), signal.SIGTERM)
    stops = sorted([await probe.heard("worker w1 "), await probe.heard("worker w2 ")])
    assert [stop.split(" ")[2:4] for stop in stops] == [["stops", "200"]] * 2
    assert await desktop.ended(first) == 0
    assert left_behind(desktop.data) == []

    third = await desktop.launch()
    reopened = fields(await probe.heard("window opened"))
    assert reopened["origin"] == window["origin"]
    third.send_signal(signal.SIGTERM)
    assert await desktop.ended(third) == 0
    assert left_behind(desktop.data) == []


async def test_a_worker_that_ends_stops_the_whole_desktop(desktop: Desktop) -> None:
    launched = await desktop.launch(environment={"ONEBERTH_TEST_FAILING_WORKER": "w2"})

    assert await desktop.ended(launched) == 1
    assert "notes stopped: the worker 'w2' ended with code 3" in (
        desktop.logs.read_text()
    )
    assert left_behind(desktop.data) == []


def chromium_window(data: Path) -> int:
    """The window's own process: the browser's, not one of its helpers."""
    for pid in left_behind(data):
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if any(a.startswith(b"--app=") for a in arguments) and not any(
            a.startswith(b"--type=") for a in arguments
        ):
            return pid
    raise AssertionError("no window runs")


async def test_the_window_is_chromium_signed_in_and_closing_it_stops_all(
    desktop: Desktop,
) -> None:
    chromium = os.environ.get(CHROMIUM_ENV)
    if not chromium:
        pytest.skip(f"no Chromium: set {CHROMIUM_ENV}")
    launched = await desktop.launch(chromium, ["--headless=new", "--no-sandbox"])

    assert await desktop.probe.heard("items for Ada")
    os.kill(chromium_window(desktop.data), signal.SIGTERM)

    assert await desktop.ended(launched) == 0
    assert left_behind(desktop.data) == []
