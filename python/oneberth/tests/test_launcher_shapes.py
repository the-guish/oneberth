# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The Docker shape, in memory: the choice of shape, the networks each
component joins, what each component receives, the refusals, the cleaning
after a crash, and the order of a start and a stop with containers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from oneberth.launcher import (
    APP,
    BACKEND,
    SANDBOX,
    WINDOW,
    Application,
    Backend,
    Container,
    Ending,
    LauncherError,
    Mount,
    Outcome,
    Process,
    Shape,
    Trust,
    Worker,
    clean,
    container_name,
    network_name,
    networks_of,
    shape_of,
)
from oneberth.launcher._shape import (
    ContainerPlan,
    Joined,
    MountPlan,
    Published,
    labels_of,
)
from oneberth.launcher.testing import StandIns

ROLE = "notes/worker"
DATA = Path("/data")
IMAGE = "notes:1"
SERVE = Process(["serve"])
BACKEND_IMAGE = Container(IMAGE, ["serve"], {"LOG": "info"})
UNTRUSTED = Trust.UNTRUSTED


def worker(name: str, run: Process | Container, trust: Trust = Trust.TRUSTED) -> Worker:
    return Worker(name, ROLE, run, resource=name, trust=trust)


def desktop(*workers: Worker, backend: Backend | None = None) -> Application:
    return Application(
        "notes",
        DATA,
        backend or Backend(SERVE, container=BACKEND_IMAGE),
        workers=workers,
    )


TRUSTED_C = worker("t1", Container(IMAGE, ["work"], {"MODEL_URL": "http://m"}))
UNTRUSTED_C = worker(
    "u1",
    Container(IMAGE, ["work"], {"ENGINE": "echo"}, [Mount("workers/u1", "/state")]),
    UNTRUSTED,
)
PROCESS_W = worker("p1", Process(["work"]))


@pytest.mark.parametrize(
    ("application", "shape"),
    [
        (desktop(), Shape.PROCESSES),
        (desktop(PROCESS_W), Shape.PROCESSES),
        (desktop(PROCESS_W, TRUSTED_C), Shape.DOCKER),
        (desktop(UNTRUSTED_C), Shape.DOCKER),
        (desktop(backend=Backend(BACKEND_IMAGE)), Shape.DOCKER),
    ],
)
def test_one_worker_in_a_container_puts_the_whole_application_in_docker(
    application: Application, shape: Shape
) -> None:
    assert shape_of(application) is shape


@pytest.mark.parametrize(
    ("application", "name", "networks"),
    [
        (desktop(PROCESS_W), BACKEND, ()),
        (desktop(PROCESS_W), "p1", ()),
        (desktop(TRUSTED_C), BACKEND, (APP, SANDBOX)),
        (desktop(TRUSTED_C, PROCESS_W), "p1", ()),
        (desktop(TRUSTED_C), "t1", (APP,)),
        (desktop(UNTRUSTED_C), "u1", (SANDBOX,)),
    ],
)
def test_each_component_joins_its_networks(
    application: Application, name: str, networks: tuple[str, ...]
) -> None:
    assert networks_of(application, name) == networks


def described(*workers: Worker, backend: Backend | None = None) -> str:
    try:
        desktop(*workers, backend=backend)
    except LauncherError as error:
        return str(error)
    return "accepted"


@pytest.mark.parametrize(
    ("make", "problem"),
    [
        (
            lambda: described(worker("u", Process(["w"]), UNTRUSTED)),
            "the worker 'u' is untrusted: it runs in a container",
        ),
        (
            lambda: described(TRUSTED_C, backend=Backend(SERVE)),
            "a worker runs in a container: the backend needs a container too",
        ),
        (
            lambda: described(
                worker("u", Container(IMAGE, mounts=[Mount(".", "/d")]), UNTRUSTED)
            ),
            "the worker 'u' is untrusted: it may not mount the data directory, /data",
        ),
        (
            lambda: described(
                worker("u", Container(IMAGE, mounts=[Mount("/", "/d")]), UNTRUSTED)
            ),
            "it may not mount the data directory, /",
        ),
        (
            lambda: described(
                worker(
                    "u", Container(IMAGE, mounts=[Mount("a/../..", "/d")]), UNTRUSTED
                )
            ),
            "it may not mount the data directory, /",
        ),
        (
            lambda: described(
                worker("u", Container(IMAGE, mounts=[Mount("u", "/s")]), UNTRUSTED),
                worker("t", Container(IMAGE, mounts=[Mount(".", "/data")])),
            ),
            "accepted",
        ),
        (lambda: described(worker("t", Container(""))), "a container needs an image"),
        (
            lambda: described(worker("t", Container(IMAGE, environment={"A B": "1"}))),
            "no variable is named 'A B'",
        ),
        (
            lambda: described(worker("t", Container(IMAGE, environment={"A": "1\n2"}))),
            "the variable A holds a line break",
        ),
        (
            lambda: described(worker("t", Container(IMAGE, mounts=[Mount("a", "b")]))),
            "a mount's target is an absolute path: 'b'",
        ),
        (
            lambda: described(
                worker(
                    "t", Container(IMAGE, mounts=[Mount("a", "/b"), Mount("c", "/b")])
                )
            ),
            "two mounts have the target '/b'",
        ),
    ],
)
def test_a_description_of_containers_is_checked(
    make: Callable[[], str], problem: str
) -> None:
    try:
        found = make()
    except LauncherError as error:
        found = str(error)
    assert problem in found


async def test_the_docker_shape_starts_in_order_and_gives_each_part_its_share() -> None:
    stand_ins = StandIns()
    application = desktop(TRUSTED_C, UNTRUSTED_C, PROCESS_W)
    launcher = stand_ins.launcher(application)
    running = asyncio.create_task(launcher.run())
    await stand_ins.process(WINDOW)
    app, sandbox = network_name(DATA, APP), network_name(DATA, SANDBOX)
    started = [
        f"network {app}",
        f"network {sandbox}",
        "start backend",
        f"token t1 {ROLE} t1",
        f"token u1 {ROLE} u1",
        f"token p1 {ROLE} p1",
        "start t1",
        "start u1",
        "start p1",
        "ticket",
        "start window",
    ]
    assert stand_ins.journal == started

    plans = stand_ins.docker.plans
    labels = labels_of(DATA)
    assert plans[BACKEND] == ContainerPlan(
        name=container_name(DATA, BACKEND),
        image=IMAGE,
        command=("serve",),
        environment={
            "LOG": "info",
            "ONEBERTH_DATA_DIR": "/data",
            "ONEBERTH_HOST": "127.0.0.1",
            "ONEBERTH_FRONT_PORT": "8420",
            "ONEBERTH_WORKER_PORT": "8421",
            "ONEBERTH_FRONT_BIND": "front",
            "ONEBERTH_WORKER_BIND": "0.0.0.0",
        },
        mounts=(MountPlan(DATA, "/data", False),),
        networks=(Joined(app, ("front",)), Joined(sandbox)),
        published=(Published("127.0.0.1", 8420), Published("127.0.0.1", 8421)),
        gateway=True,
        user="1000:1000",
        labels={**labels, "oneberth.part": BACKEND},
    )
    trusted = plans["t1"]
    assert (trusted.networks, trusted.gateway, trusted.mounts) == (
        (Joined(app),),
        True,
        (),
    )
    assert trusted.environment == {
        "MODEL_URL": "http://m",
        "ONEBERTH_WORKER_NAME": "t1",
        "ONEBERTH_WORKER_URL": "http://10.0.1.2:8421",
        "ONEBERTH_FRONT_URL": "http://10.0.1.2:8420",
    }
    untrusted = plans["u1"]
    assert (untrusted.networks, untrusted.gateway, untrusted.published) == (
        (Joined(sandbox),),
        False,
        (),
    )
    assert untrusted.mounts == (MountPlan(DATA / "workers/u1", "/state", False),)
    assert untrusted.environment == {
        "ENGINE": "echo",
        "ONEBERTH_WORKER_NAME": "u1",
        "ONEBERTH_WORKER_URL": "http://10.0.2.2:8421",
    }
    processes = stand_ins.runtime.processes
    secret = stand_ins.api.secrets[0]
    assert processes[BACKEND].stdin == secret
    assert [processes[n].stdin for n in ("t1", "u1", "p1")] == [
        "token-t1",
        "token-u1",
        "token-p1",
    ]
    for plan in plans.values():
        values = " ".join(plan.environment.values())
        assert secret not in values
        assert "token-" not in values
    assert processes["p1"].environment == {
        "ONEBERTH_DATA_DIR": "/data",
        "ONEBERTH_LAUNCHER_PID": "1",
        "ONEBERTH_WORKER_NAME": "p1",
        "ONEBERTH_WORKER_URL": "http://127.0.0.1:8421",
        "ONEBERTH_FRONT_URL": "http://127.0.0.1:8420",
    }

    launcher.stop()
    assert (await running).ending is Ending.SIGNAL
    assert stand_ins.journal == [
        *started,
        "stop window",
        "stop t1",
        "stop u1",
        "stop p1",
        "stop backend",
        f"remove networks {app}, {sandbox}",
    ]
    assert stand_ins.docker.networks == {}
    assert stand_ins.docker.containers == {}


async def test_the_launcher_refuses_to_start_while_docker_is_not_running() -> None:
    stand_ins = StandIns()
    stand_ins.docker.up = False
    application = desktop(TRUSTED_C, UNTRUSTED_C, PROCESS_W)
    message = (
        "Docker is not running; it runs the workers 't1', 'u1'."
        " Start Docker, then start again"
    )
    with pytest.raises(LauncherError) as refused:
        await clean(stand_ins.docker, application)
    assert str(refused.value) == message

    outcome = await stand_ins.launcher(application).run()
    assert outcome == Outcome(Ending.START_FAILED, message)
    assert stand_ins.journal == []


async def test_a_start_removes_what_a_crashed_start_left_on_its_data_directory() -> (
    None
):
    stand_ins = StandIns()
    docker = stand_ins.docker
    app, sandbox = network_name(DATA, APP), network_name(DATA, SANDBOX)
    left = container_name(DATA, BACKEND)
    docker.leave(left, [app, sandbox], labels_of(DATA))
    other = Path("/other")
    docker.leave(
        container_name(other, BACKEND), [network_name(other, APP)], labels_of(other)
    )
    application = desktop(UNTRUSTED_C)

    assert await clean(docker, application) == [left, app, sandbox]
    assert stand_ins.journal == [
        f"remove containers {left}",
        f"remove networks {app}, {sandbox}",
    ]
    assert list(docker.containers) == [container_name(other, BACKEND)]
    assert list(docker.networks) == [network_name(other, APP)]

    docker.leave(left, [app], labels_of(DATA))
    stand_ins.journal.clear()
    launcher = stand_ins.launcher(application)
    running = asyncio.create_task(launcher.run())
    await stand_ins.process(WINDOW)
    assert stand_ins.journal[:4] == [
        f"remove containers {left}",
        f"remove networks {app}",
        f"network {app}",
        f"network {sandbox}",
    ]
    launcher.stop()
    await running
    assert list(docker.containers) == [container_name(other, BACKEND)]


async def test_a_failed_start_in_docker_removes_its_containers_and_networks() -> None:
    stand_ins = StandIns()
    stand_ins.runtime.refused.add("u1")
    stand_ins.runtime.stubborn.add("t1")
    app, sandbox = network_name(DATA, APP), network_name(DATA, SANDBOX)
    launcher = stand_ins.launcher(desktop(TRUSTED_C, UNTRUSTED_C))
    running = asyncio.create_task(launcher.run())
    await stand_ins.timer.sleeping(15)
    stand_ins.timer.advance(15)

    assert (await running).detail == "u1 could not be started"
    assert stand_ins.journal[-5:] == [
        "start t1",
        "stop t1",
        "kill t1",
        "stop backend",
        f"remove networks {app}, {sandbox}",
    ]
    assert stand_ins.docker.containers == {}


async def test_networks_a_start_could_not_finish_are_removed() -> None:
    stand_ins = StandIns()
    docker = stand_ins.docker
    sandbox = network_name(DATA, SANDBOX)
    docker.leave(None, [sandbox], {"made-by": "someone else"})

    outcome = await stand_ins.launcher(desktop(UNTRUSTED_C)).run()
    assert outcome.detail == f"the network {sandbox} exists already"
    app = network_name(DATA, APP)
    assert stand_ins.journal == [f"network {app}", f"remove networks {app}"]
    assert list(docker.networks) == [sandbox]
