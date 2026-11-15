# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The launcher with the real Docker daemon: a real backend in the local mode
runs in a container, beside a trusted worker's container on ``app``, an
untrusted worker's container on ``sandbox``, a worker as a process of the host
and the stand-in browser.

The image is built once per session from ``python:3.12-slim``, with the
oneberth checkout, its dependencies for the web part and the programs of these
tests inside. The tests are marked ``docker``, and skip without a daemon.
After each test, no container, network or process of its data directory is
left, pass or fail.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from oneberth.launcher import (
    APP,
    BACKEND,
    DATA_LABEL,
    SANDBOX,
    container_name,
    network_name,
)

pytestmark = pytest.mark.docker

HERE = Path(__file__).parent
SOURCE = HERE.parent / "src"
ROOT = HERE.parents[2]
LAUNCHER = HERE / "docker_launcher_process.py"
STAND_IN_BROWSER = HERE / "stand_in_browser.py"
BASE_IMAGE = "python:3.12-slim"
IMAGE_FILES = (
    "launched_backend_process.py",
    "launched_worker_process.py",
    "launcher_page",
)
TIMEOUT_SECONDS = 120
SECRET_PREFIXES = (b"ob_svc_", b"ob_lch_")
MARKER = "ONEBERTH_TEST_RUN"


def docker(*arguments: str, check: bool = True) -> str:
    done = subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=300
    )
    if check and done.returncode != 0:
        raise AssertionError(f"docker {' '.join(arguments)}: {done.stderr}")
    return done.stdout


def docker_running() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=20, check=True)
    except (subprocess.SubprocessError, OSError):
        return False
    return True


@pytest.fixture(scope="session")
def image(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """An image of Python 3.12 with oneberth[web] and the tests' programs."""
    if not docker_running():
        pytest.skip("no Docker daemon: these tests start containers")
    uv = os.environ.get("UV") or shutil.which("uv")
    if uv is None:
        pytest.skip("no uv: it gathers the image's dependencies")
    context = tmp_path_factory.mktemp("image")
    requirements = context / "requirements.txt"
    subprocess.run(
        [uv, "export", "--frozen", "--no-dev", "--extra", "web", "--package",
         "oneberth", "--no-emit-workspace", "--no-hashes", "--quiet",
         "-o", os.fspath(requirements)],
        cwd=ROOT, check=True, timeout=300,
    )  # fmt: skip
    machine = docker("info", "--format", "{{.Architecture}}").strip()
    machine = {"arm64": "aarch64", "amd64": "x86_64"}.get(machine, machine)
    subprocess.run(
        [uv, "pip", "install", "--quiet", "--target", os.fspath(context / "site"),
         "--python-version", "3.12", "--python-platform", f"{machine}-manylinux_2_28",
         "--only-binary", ":all:", "--no-deps", "-r", os.fspath(requirements)],
        cwd=ROOT, check=True, timeout=300,
    )  # fmt: skip
    shutil.copytree(SOURCE / "oneberth", context / "src" / "oneberth")
    for name in IMAGE_FILES:
        found = HERE / name
        if found.is_dir():
            shutil.copytree(found, context / "tests" / name)
        else:
            (context / "tests").mkdir(exist_ok=True)
            shutil.copy(found, context / "tests" / name)
    (context / "Dockerfile").write_text(
        f"FROM {BASE_IMAGE}\n"
        "COPY site /opt/site\n"
        "COPY src /opt/oneberth\n"
        "COPY tests /opt/tests\n"
        "ENV PYTHONPATH=/opt/site:/opt/oneberth PYTHONUNBUFFERED=1\n"
    )
    tag = f"oneberth-test:{uuid.uuid4().hex[:12]}"
    docker("build", "--quiet", "--tag", tag, os.fspath(context))
    try:
        yield tag
    finally:
        docker("image", "rm", "--force", tag, check=False)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


class Heard:
    """Lines that arrive, from the probe or from the launcher's log."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.everything: list[str] = []
        self._heard = asyncio.Event()

    def add(self, line: str) -> None:
        self.lines.append(line)
        self.everything.append(line)
        self._heard.set()

    async def heard(self, text: str) -> str:
        """The first line that holds ``text``, once it arrives."""
        async with asyncio.timeout(TIMEOUT_SECONDS):
            while True:
                for index, line in enumerate(self.lines):
                    if text in line:
                        return self.lines.pop(index)
                self._heard.clear()
                await self._heard.wait()


def marked_processes(run: str) -> list[int]:
    """The processes of the host whose environment holds the test's marker."""
    marker = f"{MARKER}={run}".encode()
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit() and entry.name != str(os.getpid()):
            try:
                if marker in (entry / "environ").read_bytes().split(b"\0"):
                    found.append(int(entry.name))
            except OSError:
                continue
    return found


def ours(data: Path) -> tuple[list[str], list[str]]:
    """The containers and the networks of a data directory."""
    label = f"label={DATA_LABEL}={data}"
    containers = docker("ps", "--all", "--format", "{{.Names}}", "--filter", label)
    networks = docker("network", "ls", "--format", "{{.Name}}", "--filter", label)
    return containers.split(), networks.split()


class Desktop:
    """Starts the test application's command on one data directory."""

    def __init__(self, tmp_path: Path, image: str) -> None:
        self.data = tmp_path / "data"
        self.image = image
        self.run = uuid.uuid4().hex
        self.probe = Heard()
        self.log = Heard()
        self.probe_port = 0
        self.front_port = free_port()
        self.started: list[asyncio.subprocess.Process] = []
        self._readers: list[asyncio.Task[None]] = []
        self.stand_in = tmp_path / "browser"
        self.stand_in.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{STAND_IN_BROWSER}" "$@"\n'
        )
        self.stand_in.chmod(0o755)

    async def accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        async for line in reader:
            self.probe.add(line.decode().strip())
        writer.close()

    async def launch(
        self, environment: dict[str, str] | None = None
    ) -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            os.fspath(LAUNCHER),
            os.fspath(self.data),
            os.fspath(self.stand_in),
            self.image,
            str(self.front_port),
            env={
                **os.environ,
                "PROBE_PORT": str(self.probe_port),
                MARKER: self.run,
                **(environment or {}),
            },
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self.started.append(process)
        self._readers.append(asyncio.create_task(self._read(process)))
        return process

    async def _read(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        async for line in process.stdout:
            self.log.add(line.decode(errors="replace").rstrip())

    async def ended(self, process: asyncio.subprocess.Process) -> int:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            return await process.wait()

    async def ready(self) -> dict[str, str]:
        """Wait until every part serves; the window's report."""
        for name in ("t1", "u1"):
            line = await self.log.heard(f"worker {name} claimed ")
            assert line.endswith(f'200 {{"by": "{name}", "queue": "{QUEUES[name]}"}}')
        line = await self.probe.heard("worker p1 claimed ")
        assert line == 'worker p1 claimed 200 {"by": "p1", "queue": "io"}'
        return fields(await self.probe.heard("window opened"))

    def container(self, name: str) -> str:
        return container_name(self.data, name)

    def network(self, name: str) -> str:
        return network_name(self.data, name)

    async def clean(self) -> None:
        # The launcher's parts share its output: they end first, or before
        # 3.12 the wait for the launcher lasts as long as they do.
        for pid in marked_processes(self.run):
            os.kill(pid, signal.SIGKILL)
        for process in self.started:
            with contextlib.suppress(TimeoutError):
                await self.ended(process)
        for task in self._readers:
            task.cancel()
        await asyncio.gather(*self._readers, return_exceptions=True)
        containers, networks = ours(self.data)
        if containers:
            docker("rm", "--force", *containers, check=False)
        if networks:
            docker("network", "rm", *networks, check=False)
        for pid in marked_processes(self.run):
            os.kill(pid, signal.SIGKILL)


QUEUES = {"t1": "gpu", "u1": "cpu", "p1": "io"}


def fields(line: str) -> dict[str, str]:
    return dict(word.split("=", 1) for word in line.split(" ") if "=" in word)


@pytest.fixture
async def desktop(tmp_path: Path, image: str) -> AsyncIterator[Desktop]:
    desktop = Desktop(tmp_path, image)
    server = await asyncio.start_server(desktop.accept, "127.0.0.1", 0)
    desktop.probe_port = server.sockets[0].getsockname()[1]
    try:
        yield desktop
    finally:
        try:
            await desktop.clean()
        finally:
            server.close()
            await server.wait_closed()
            print("\n".join(desktop.log.everything))
    assert ours(desktop.data) == ([], [])


def inspected(name: str) -> Any:
    return json.loads(docker("inspect", name))[0]


def networks_of(name: str) -> dict[str, dict[str, str]]:
    networks: dict[str, dict[str, str]] = inspected(name)["NetworkSettings"]["Networks"]
    return networks


def mounts_of(name: str) -> list[tuple[str, str]]:
    return [(m["Source"], m["Destination"]) for m in inspected(name)["Mounts"]]


def environment_of(name: str, image: str) -> set[str]:
    """The variables of a container that its image does not set."""
    config = inspected(name)["Config"]
    own = set(json.loads(docker("image", "inspect", "--format",
                                "{{json .Config.Env}}", image)))  # fmt: skip
    return set(config["Env"]) - own


CONNECT = """
import socket, sys
for target in sys.argv[1:]:
    host, port = target.rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), timeout=3).close()
        print(target, "open")
    except OSError as error:
        print(target, "closed", type(error).__name__)
"""


def reachable(container: str, *targets: str) -> dict[str, bool]:
    """Which ``host:port`` a container connects to."""
    out = docker("exec", container, "python", "-c", CONNECT, *targets)
    return {
        target: state == "open"
        for target, state, *_ in (line.split(" ") for line in out.splitlines())
    }


def host_addresses() -> set[str]:
    """The IPv4 addresses of this host: its name's and each bridge gateway's."""
    found = {"172.17.0.1"}
    with_name = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    found |= {str(entry[4][0]) for entry in with_name}
    for network in docker("network", "ls", "--format", "{{.Name}}").split():
        for config in (
            json.loads(
                docker(
                    "network", "inspect", "--format", "{{json .IPAM.Config}}", network
                )
            )
            or []
        ):
            if config.get("Gateway"):
                found.add(config["Gateway"])
            subnet = config.get("Subnet", "")
            if subnet.endswith(".0/16") or subnet.endswith(".0/24"):
                found.add(subnet.rsplit(".", 1)[0] + ".1")
    return {a for a in found if ":" not in a and not a.startswith("127.")}


def secrets_in(data: bytes) -> list[bytes]:
    return [prefix for prefix in SECRET_PREFIXES if prefix in data]


async def test_the_docker_shape_runs_isolates_the_untrusted_worker_and_stops_clean(
    desktop: Desktop,
) -> None:
    host_service = await asyncio.start_server(lambda _r, w: w.close(), "0.0.0.0", 0)
    service_port = host_service.sockets[0].getsockname()[1]
    try:
        launched = await desktop.launch()
        window = await desktop.ready()
        front = f"http://127.0.0.1:{desktop.front_port}"
        assert window["origin"] == front
        assert (window["at"], window["items"]) == ("/ui/", '{"for":"Ada"}')
        await desktop.log.heard("items for Ada")
        async with httpx.AsyncClient(trust_env=False) as client:
            assert (await client.get(f"{front}/health")).status_code == 200

        backend, t1, u1 = (desktop.container(n) for n in (BACKEND, "t1", "u1"))
        app, sandbox = desktop.network(APP), desktop.network(SANDBOX)
        on = networks_of(backend)
        assert set(on) == {app, sandbox}
        assert set(networks_of(t1)) == {app}
        assert set(networks_of(u1)) == {sandbox}
        bindings = inspected(backend)["HostConfig"]["PortBindings"].values()
        assert {b["HostIp"] for found in bindings for b in found} == {"127.0.0.1"}
        assert mounts_of(backend) == [(os.fspath(desktop.data), "/data")]
        assert (desktop.data / "oneberth.db").is_file()

        worker_port = int(
            next(
                v.split("=", 1)[1]
                for v in environment_of(backend, desktop.image)
                if v.startswith("ONEBERTH_WORKER_PORT=")
            )
        )
        app_ip, sandbox_ip = on[app]["IPAddress"], on[sandbox]["IPAddress"]
        assert environment_of(u1, desktop.image) == {
            "ENGINE=echo",
            "ONEBERTH_WORKER_NAME=u1",
            f"ONEBERTH_WORKER_URL=http://{sandbox_ip}:{worker_port}",
        }
        assert mounts_of(u1) == [(os.fspath(desktop.data / "workers/u1"), "/state")]
        assert environment_of(t1, desktop.image) == {
            "NOTE=trusted",
            "ONEBERTH_WORKER_NAME=t1",
            f"ONEBERTH_WORKER_URL=http://{app_ip}:{worker_port}",
            f"ONEBERTH_FRONT_URL=http://{app_ip}:{desktop.front_port}",
        }

        worker_listener = f"{sandbox_ip}:{worker_port}"
        fronts = [f"{ip}:{desktop.front_port}" for ip in (sandbox_ip, app_ip)]
        hosts = [f"{a}:{service_port}" for a in sorted(host_addresses())]
        outside = ["1.1.1.1:443", "8.8.8.8:53", f"host.docker.internal:{service_port}"]
        assert reachable(u1, worker_listener, *fronts, *hosts, *outside) == {
            worker_listener: True,
            **dict.fromkeys([*fronts, *hosts, *outside], False),
        }
        assert reachable(
            t1,
            f"{app_ip}:{desktop.front_port}",
            f"host.docker.internal:{service_port}",
        ) == {
            f"{app_ip}:{desktop.front_port}": True,
            f"host.docker.internal:{service_port}": True,
        }

        for name in (backend, t1, u1):
            assert secrets_in(docker("inspect", name).encode()) == []
        for pid in marked_processes(desktop.run):
            for part in ("cmdline", "environ"):
                with_secret = secrets_in(Path(f"/proc/{pid}/{part}").read_bytes())
                assert with_secret == [], (pid, part)

        launched.send_signal(signal.SIGTERM)
        for name, queue in QUEUES.items():
            if name != "p1":
                line = await desktop.log.heard(f"worker {name} stops ")
                assert line.endswith(f'200 {{"by": "{name}", "queue": "{queue}"}}')
        assert (await desktop.probe.heard("worker p1 stops ")).split(" ")[3] == "200"
        assert await desktop.ended(launched) == 0
        assert ours(desktop.data) == ([], [])
        assert marked_processes(desktop.run) == []
    finally:
        host_service.close()
        await host_service.wait_closed()


async def test_a_start_after_a_crash_removes_what_the_crash_left(
    desktop: Desktop,
) -> None:
    crashed = await desktop.launch()
    await desktop.ready()
    # The crash ends the host's processes of the start, the launcher among
    # them. Its containers stay.
    for pid in marked_processes(desktop.run):
        os.kill(pid, signal.SIGKILL)
    assert await desktop.ended(crashed) == -signal.SIGKILL
    left, networks = ours(desktop.data)
    assert set(left) == {desktop.container(n) for n in (BACKEND, "t1", "u1")}
    assert set(networks) == {desktop.network(APP), desktop.network(SANDBOX)}

    again = await desktop.launch()
    removed = await desktop.log.heard("removed what an earlier start left: ")
    assert set(removed.split(": ", 1)[1].split(", ")) == {*left, *networks}
    window = await desktop.ready()
    assert window["origin"] == f"http://127.0.0.1:{desktop.front_port}"
    again.send_signal(signal.SIGTERM)
    assert await desktop.ended(again) == 0
    assert ours(desktop.data) == ([], [])


async def test_the_launcher_refuses_while_docker_does_not_answer(
    desktop: Desktop,
) -> None:
    refused = await desktop.launch({"DOCKER_HOST": "unix:///nonexistent/docker.sock"})

    assert await desktop.ended(refused) == 1
    assert await desktop.log.heard(
        "Docker is not running; it runs the workers 't1', 'u1'."
    )
    assert marked_processes(desktop.run) == []
