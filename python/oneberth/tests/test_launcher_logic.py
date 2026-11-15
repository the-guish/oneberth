# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The launcher's logic, on stand-ins and a manual timer.

The start follows the spec's order and the stop goes the other way. Each
failure stops what was started: a backend that never says ``ready`` or ends
first, a worker that ends, a refused token, a part that ignores SIGTERM. The
window's close and a signal stop the application.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from oneberth.identity import CredentialKind, kind_of
from oneberth.launcher import (
    AGAIN,
    BACKEND,
    WINDOW,
    Application,
    Backend,
    Ending,
    LauncherError,
    Outcome,
    Process,
    Trust,
    Window,
    Worker,
    testing,
)
from oneberth.launcher.testing import StandIns

ROLE = "notes/worker"
TICKET = "http://127.0.0.1:8420/auth/local?ticket=t1"
STARTED = [
    "prepare",
    "start backend",
    f"token w1 {ROLE} gpu",
    f"token w2 {ROLE} None",
    "start w1",
    "start w2",
    "ticket",
    "start window",
]
STOPPED = ["stop w1", "stop w2", "stop backend", "release"]


def application(
    data_dir: Path = Path("/data"), *, window: Window | None = None, **changes: object
) -> Application:
    return Application(
        name="notes",
        data_dir=data_dir,
        backend=Backend(Process(["serve"])),
        workers=[
            Worker("w1", ROLE, Process(["work"]), resource="gpu"),
            Worker("w2", ROLE, Process(["work"])),
        ],
        window=Window() if window is None else window,
        **changes,  # type: ignore[arg-type]
    )


async def started(
    stand_ins: StandIns, app: Application | None = None
) -> tuple[asyncio.Task[Outcome], Callable[[], None]]:
    launcher = stand_ins.launcher(app or application())
    return asyncio.create_task(launcher.run()), launcher.stop


async def test_the_launcher_starts_in_the_specs_order_and_stops_the_other_way() -> None:
    stand_ins = StandIns()
    launcher = stand_ins.launcher(application())
    running = asyncio.create_task(launcher.run())
    window = await stand_ins.process(WINDOW)
    assert stand_ins.journal == STARTED
    assert launcher.pids == {BACKEND: 1000, "w1": 1001, "w2": 1002, WINDOW: 1003}

    backend = stand_ins.runtime.processes[BACKEND]
    secret = stand_ins.api.secrets[0]
    assert kind_of(secret) is CredentialKind.LAUNCH
    assert backend.stdin == secret
    assert backend.environment == {
        "ONEBERTH_DATA_DIR": os.fspath(Path("/data").absolute()),
        "ONEBERTH_LAUNCHER_PID": "1",
        "ONEBERTH_HOST": "127.0.0.1",
        "ONEBERTH_FRONT_PORT": "8420",
        "ONEBERTH_WORKER_PORT": "8421",
        "ONEBERTH_FRONT_BIND": "127.0.0.1",
        "ONEBERTH_WORKER_BIND": "127.0.0.1",
    }
    assert stand_ins.api.front_url == "http://127.0.0.1:8420"
    w1 = stand_ins.runtime.processes["w1"]
    assert w1.stdin == "token-w1"
    assert w1.environment == {
        "ONEBERTH_DATA_DIR": os.fspath(Path("/data").absolute()),
        "ONEBERTH_LAUNCHER_PID": "1",
        "ONEBERTH_WORKER_NAME": "w1",
        "ONEBERTH_WORKER_URL": "http://127.0.0.1:8421",
        "ONEBERTH_FRONT_URL": "http://127.0.0.1:8420",
    }
    assert window.run == Process(("browser", f"--app={TICKET}"))
    assert window.stdin is None

    launcher.stop()
    outcome = await running
    assert outcome == Outcome(Ending.SIGNAL, "a signal asked the application to stop")
    assert outcome.code == 0
    assert stand_ins.journal == [*STARTED, "stop window", *STOPPED]
    assert launcher.pids == {}


async def test_closing_the_window_stops_the_application() -> None:
    stand_ins = StandIns()
    running, _ = await started(stand_ins)
    (await stand_ins.process(WINDOW)).exit(0)

    outcome = await running
    assert (outcome.ending, outcome.code) == (Ending.WINDOW_CLOSED, 0)
    assert stand_ins.journal == [*STARTED, *STOPPED]


async def test_without_a_browser_the_default_browser_opens_and_a_signal_stops() -> None:
    stand_ins = StandIns()
    stand_ins.windows.browser = False
    launcher = stand_ins.launcher(application())
    running = asyncio.create_task(launcher.run())
    while "ticket" not in stand_ins.journal:
        await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert stand_ins.journal[-1] == f"default browser {TICKET}"

    launcher.show()
    while stand_ins.journal[-1] == f"default browser {TICKET}":
        await asyncio.sleep(0)
    await asyncio.sleep(0)
    launcher.stop()
    assert (await running).ending is Ending.SIGNAL
    assert stand_ins.journal == [
        *STARTED[:-1],
        f"default browser {TICKET}",
        "ticket",
        f"default browser {TICKET[:-1]}2",
        *STOPPED,
    ]


async def test_a_second_start_brings_the_window_forward_with_a_new_ticket() -> None:
    stand_ins = StandIns()
    launcher = stand_ins.launcher(application())
    running = asyncio.create_task(launcher.run())
    await stand_ins.process(WINDOW)

    launcher.show()
    again = await stand_ins.process(AGAIN)
    assert again.run == Process(("browser", f"--app={TICKET[:-1]}2"))
    launcher.stop()
    await running
    assert stand_ins.journal == [
        *STARTED,
        "ticket",
        f"start {AGAIN}",
        "stop window",
        *STOPPED,
    ]


async def test_an_application_without_a_window_asks_for_no_ticket() -> None:
    stand_ins = StandIns()
    app = Application("notes", "/data", Backend(Process(["serve"])), window=None)
    launcher = stand_ins.launcher(app)
    running = asyncio.create_task(launcher.run())
    while launcher.pids != {BACKEND: 1000}:
        await asyncio.sleep(0)
    await asyncio.sleep(0)
    launcher.stop()
    assert (await running).ending is Ending.SIGNAL
    assert stand_ins.journal == ["prepare", "start backend", "stop backend", "release"]


async def test_a_backend_that_never_says_ready_is_stopped() -> None:
    stand_ins = StandIns()
    stand_ins.runtime.silent.add(BACKEND)
    running, _ = await started(stand_ins)
    await stand_ins.timer.sleeping(60)
    stand_ins.timer.advance(59)
    await asyncio.sleep(0)
    assert not running.done()
    stand_ins.timer.advance(1)

    outcome = await running
    assert outcome == Outcome(
        Ending.START_FAILED, "the backend did not say ready within 60 s"
    )
    assert outcome.code == 1
    assert stand_ins.journal == ["prepare", "start backend", "stop backend", "release"]


async def test_a_backend_that_ends_before_ready_fails_the_start() -> None:
    stand_ins = StandIns()
    stand_ins.runtime.silent.add(BACKEND)
    running, _ = await started(stand_ins)
    (await stand_ins.process(BACKEND)).exit(1)

    assert await running == Outcome(
        Ending.START_FAILED, "the backend ended with code 1 before it said ready"
    )
    assert stand_ins.journal == ["prepare", "start backend", "release"]


async def test_a_worker_that_never_says_ready_stops_the_others_and_the_backend() -> (
    None
):
    stand_ins = StandIns()
    stand_ins.runtime.silent.add("w2")
    running, _ = await started(stand_ins)
    await stand_ins.timer.sleeping(60)
    stand_ins.timer.advance(60)

    outcome = await running
    assert outcome.detail == "the worker 'w2' did not say ready within 60 s"
    assert stand_ins.journal == [*STARTED[:-2], *STOPPED]


async def test_a_worker_that_ends_stops_the_application() -> None:
    stand_ins = StandIns()
    running, _ = await started(stand_ins)
    await stand_ins.process(WINDOW)
    stand_ins.runtime.processes["w1"].exit(3)

    outcome = await running
    assert outcome == Outcome(Ending.PART_ENDED, "the worker 'w1' ended with code 3")
    assert outcome.code == 1
    assert stand_ins.journal == [
        *STARTED,
        "stop window",
        "stop w2",
        "stop backend",
        "release",
    ]


async def test_the_backend_that_ends_stops_the_workers() -> None:
    stand_ins = StandIns()
    running, _ = await started(stand_ins)
    await stand_ins.process(WINDOW)
    stand_ins.runtime.processes[BACKEND].exit(-11)

    assert (await running).detail == "the backend ended with code -11"
    assert stand_ins.journal == [*STARTED, "stop window", *STOPPED[:2], "release"]


async def test_a_part_that_ignores_sigterm_is_killed_after_its_patience() -> None:
    stand_ins = StandIns()
    stand_ins.runtime.stubborn.update({"w1", BACKEND})
    running, stop = await started(stand_ins)
    await stand_ins.process(WINDOW)
    stop()
    await stand_ins.timer.sleeping(15)
    assert stand_ins.journal[-2:] == ["stop w1", "stop w2"]
    stand_ins.timer.advance(15)
    await stand_ins.timer.sleeping(30)
    stand_ins.timer.advance(29)
    await asyncio.sleep(0)
    assert stand_ins.journal[-1] == "stop backend"
    stand_ins.timer.advance(1)

    await running
    assert stand_ins.journal == [
        *STARTED,
        "stop window",
        "stop w1",
        "stop w2",
        "kill w1",
        "stop backend",
        "kill backend",
        "release",
    ]


async def test_a_signal_during_the_start_stops_what_was_started() -> None:
    stand_ins = StandIns()
    stand_ins.runtime.silent.add(BACKEND)
    running, stop = await started(stand_ins)
    await stand_ins.process(BACKEND)
    stop()

    assert (await running).ending is Ending.SIGNAL
    assert stand_ins.journal == ["prepare", "start backend", "stop backend", "release"]


async def test_a_refused_token_fails_the_start() -> None:
    stand_ins = StandIns()
    stand_ins.api.refused = True
    running, _ = await started(stand_ins)

    outcome = await running
    assert outcome.detail == "the backend answered 403 to /auth/services"
    assert stand_ins.journal == ["prepare", "start backend", "stop backend", "release"]


async def test_a_worker_that_cannot_be_started_fails_the_start() -> None:
    stand_ins = StandIns()
    stand_ins.runtime.refused.add("w2")
    running, _ = await started(stand_ins)

    assert (await running).detail == "w2 could not be started"
    assert stand_ins.journal == [*STARTED[:5], "stop w1", "stop backend", "release"]


async def test_a_wait_for_a_part_fails_at_once_when_the_run_has_ended() -> None:
    stand_ins = StandIns()
    stand_ins.runtime.refused.add("w2")
    running, _ = await started(stand_ins)

    with pytest.raises(AssertionError) as failed:
        await stand_ins.process(WINDOW)
    assert str(failed.value) == (
        "waited for the window to start, but the launcher's run has ended:"
        " it returned start failed: w2 could not be started."
        f" The journal: {stand_ins.journal}"
    )
    assert running.done()


async def test_a_wait_for_a_part_fails_with_what_the_run_raised() -> None:
    stand_ins = StandIns()
    stand_ins.runtime.silent.add(BACKEND)
    running, _ = await started(stand_ins)
    await stand_ins.process(BACKEND)
    running.cancel()

    with pytest.raises(AssertionError, match="it raised CancelledError") as failed:
        await stand_ins.process(WINDOW)
    assert isinstance(failed.value.__cause__, asyncio.CancelledError)
    with pytest.raises(AssertionError, match="it raised CancelledError"):
        await stand_ins.timer.sleeping(60)


async def test_a_wait_on_the_stand_ins_fails_after_its_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(testing, "WAIT_SECONDS", 0.05)
    stand_ins = StandIns()
    running, stop = await started(stand_ins)
    await stand_ins.process(WINDOW)

    with pytest.raises(AssertionError) as failed:
        await stand_ins.process("w3")
    assert str(failed.value) == (
        f"waited 0.05 s for the w3 to start, in vain. The journal: {STARTED}"
    )
    with pytest.raises(AssertionError, match="for something to sleep 15 s, in vain"):
        await stand_ins.timer.sleeping(15)
    stop()
    await running


def test_an_untrusted_worker_runs_in_a_container() -> None:
    untrusted = Worker("u", ROLE, Process(["work"]), trust=Trust.UNTRUSTED)
    with pytest.raises(LauncherError, match="untrusted: it runs in a container"):
        Application("notes", "/data", Backend(Process(["serve"])), workers=[untrusted])


@pytest.mark.parametrize(
    ("workers", "front_port", "problem"),
    [
        ([("w 1", None)], None, "a worker's name has letters, digits and _ . - alone"),
        ([("backend", None)], None, "a worker may not be named 'backend'"),
        ([("window", None)], None, "a worker may not be named 'window'"),
        ([("w1", None), ("w1", None)], None, "two workers are named 'w1'"),
        ([], 0, "no port is numbered 0"),
        ([], 65536, "no port is numbered 65536"),
    ],
)
def test_a_description_is_refused_with_its_problem(
    workers: list[tuple[str, str | None]], front_port: int | None, problem: str
) -> None:
    with pytest.raises(LauncherError, match=problem):
        Application(
            "notes",
            "/data",
            Backend(Process(["serve"])),
            workers=[
                Worker(name, ROLE, Process(["w"]), resource=r) for name, r in workers
            ],
            front_port=front_port,
        )


def test_a_process_needs_a_command() -> None:
    with pytest.raises(LauncherError, match="a process needs a command"):
        Process([])
