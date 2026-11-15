# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The runtime of the processes shape: each component is a process of the host.

Each process starts in a session of its own. A Ctrl-C in the terminal then
reaches the launcher alone, which stops the parts in order. Once a process has
ended, whatever it left in its session is killed.

The launcher reads a part's standard output for as long as the part runs. A
part that writes to a full pipe stops, and an access log fills one fast.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import Mapping

from oneberth.launcher._describe import Application, LauncherError, Process, Run


async def next_line(output: asyncio.StreamReader | None) -> str | None:
    """The next line of a part's output, or ``None`` once it ends.

    A line longer than the reader's buffer comes in pieces, each as long as
    the buffer: reading goes on.
    """
    if output is None:
        return None
    try:
        line = await output.readuntil(b"\n")
    except asyncio.IncompleteReadError as ended:
        line = ended.partial
    except asyncio.LimitOverrunError as long:
        line = await output.read(max(long.consumed, 1))
    return line.decode(errors="replace") if line else None


class ProcessRunning:
    """A component's process."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process

    @property
    def pid(self) -> int | None:
        return self._process.pid

    async def line(self) -> str | None:
        return await next_line(self._process.stdout)

    async def wait(self) -> int:
        code = await self._process.wait()
        self._signal_session(signal.SIGKILL)
        return code

    def terminate(self) -> None:
        if self._process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._process.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        self._signal_session(signal.SIGKILL)

    def _signal_session(self, signum: signal.Signals) -> None:
        # The session's id is the process's own: it was started in a new one.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self._process.pid, signum)


class ProcessRuntime:
    """Starts each component as a process of the host."""

    async def prepare(self, application: Application) -> None:
        return None

    async def release(self) -> None:
        return None

    async def address(self, name: str, network: str) -> str:
        raise LauncherError(f"no network joins the processes: {network}")

    async def start(
        self,
        name: str,
        run: Run,
        environment: Mapping[str, str],
        stdin: str | None,
    ) -> ProcessRunning:
        if not isinstance(run, Process):
            raise LauncherError(f"{name} runs as no process this launcher starts")
        try:
            process = await asyncio.create_subprocess_exec(
                *run.command,
                env={**os.environ, **run.environment, **environment},
                cwd=run.directory,
                stdin=asyncio.subprocess.PIPE
                if stdin is not None
                else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL if run.quiet else None,
                start_new_session=True,
            )
        except OSError as error:
            raise LauncherError(
                f"{name} could not be started with {run.command[0]}: {error}"
            ) from error
        if process.stdin is not None and stdin is not None:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                process.stdin.write(stdin.encode())
                await process.stdin.drain()
            process.stdin.close()
        return ProcessRunning(process)
