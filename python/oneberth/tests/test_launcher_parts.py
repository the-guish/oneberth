# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The launcher's small parts: the port of the front listener, the browser it
looks for, the window's command, what a backend and a worker read from their
environment, the lock on the data directory, and the links the Docker adapter
follows before it mounts a directory of an untrusted worker."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from oneberth.launcher import (
    AlreadyRunning,
    DataLock,
    LaunchedBackend,
    LaunchedWorker,
    LauncherError,
    choose_front_port,
    find_browser,
    read_token,
    window_command,
)
from oneberth.launcher._data import keep_front_port, kept_front_port
from oneberth.launcher._docker import DockerCli, mount_problem
from oneberth.launcher._shape import ContainerPlan, MountPlan


@pytest.mark.parametrize(
    ("kept", "preferred", "taken", "expected"),
    [
        (None, None, set(), 50000),
        (None, 8420, set(), 8420),
        (None, 8420, {8420}, 50000),
        (8421, 8420, set(), 8421),
        (8421, 8420, {8420}, 8421),
        (8421, None, {8421}, LauncherError),
    ],
)
def test_the_front_port_is_kept_across_starts(
    kept: int | None,
    preferred: int | None,
    taken: set[int],
    expected: int | type[Exception],
) -> None:
    def choose() -> int:
        return choose_front_port(
            kept, preferred, lambda p: p not in taken, lambda: 50000
        )

    if isinstance(expected, int):
        assert choose() == expected
    else:
        with pytest.raises(expected, match=f"port {kept}, where"):
            choose()


def test_the_front_port_is_kept_in_the_data_directory(tmp_path: Path) -> None:
    assert kept_front_port(tmp_path) is None
    keep_front_port(tmp_path, 8420)
    assert kept_front_port(tmp_path) == 8420
    (tmp_path / "launcher.json").write_text("{not json")
    assert kept_front_port(tmp_path) is None


MACOS_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MACOS_BRAVE = "Applications/Brave Browser.app/Contents/MacOS/Brave Browser"


@pytest.mark.parametrize(
    ("platform", "present", "expected"),
    [
        ("linux", {"chromium", "brave-browser"}, "/usr/bin/chromium"),
        ("linux", {"google-chrome", "chromium"}, "/usr/bin/google-chrome"),
        ("linux", {"microsoft-edge"}, "/usr/bin/microsoft-edge"),
        ("linux", {"brave-browser"}, "/usr/bin/brave-browser"),
        ("linux", set(), None),
        ("darwin", {MACOS_CHROME}, MACOS_CHROME),
        ("darwin", {f"/Users/ada/{MACOS_BRAVE}"}, f"/Users/ada/{MACOS_BRAVE}"),
        ("darwin", {"chromium"}, None),
    ],
)
def test_the_launcher_looks_for_chrome_chromium_edge_and_brave(
    platform: str, present: set[str], expected: str | None
) -> None:
    found = find_browser(
        platform,
        lambda name: f"/usr/bin/{name}" if name in present else None,
        lambda path: os.fspath(path) in present,
        Path("/Users/ada"),
    )
    assert found == expected


def test_the_window_has_a_profile_of_its_own_and_no_address_bar() -> None:
    assert window_command(
        "/usr/bin/chromium", Path("/data/window"), "http://x/a", ["--headless=new"]
    ) == (
        "/usr/bin/chromium",
        "--user-data-dir=/data/window",
        "--app=http://x/a",
        "--no-first-run",
        "--no-default-browser-check",
        "--headless=new",
    )


LAUNCHED = {
    "ONEBERTH_DATA_DIR": "/data",
    "ONEBERTH_HOST": "127.0.0.1",
    "ONEBERTH_FRONT_PORT": "8420",
    "ONEBERTH_WORKER_PORT": "8421",
}


@pytest.mark.parametrize(
    ("binds", "front_bind", "worker_bind"),
    [
        ({}, "127.0.0.1", "127.0.0.1"),
        (
            {"ONEBERTH_FRONT_BIND": "front", "ONEBERTH_WORKER_BIND": "0.0.0.0"},
            "front",
            "0.0.0.0",
        ),
    ],
)
def test_a_backend_reads_where_to_listen(
    binds: dict[str, str], front_bind: str, worker_bind: str
) -> None:
    assert LaunchedBackend.from_environ({**LAUNCHED, **binds}) == LaunchedBackend(
        Path("/data"), "127.0.0.1", 8420, 8421, front_bind, worker_bind
    )
    assert LaunchedBackend.from_environ({}) is None


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        (
            {
                "ONEBERTH_WORKER_NAME": "w1",
                "ONEBERTH_WORKER_URL": "http://127.0.0.1:8421",
                "ONEBERTH_FRONT_URL": "http://127.0.0.1:8420",
                "ONEBERTH_DATA_DIR": "/data",
            },
            LaunchedWorker(
                "w1", "http://127.0.0.1:8421", "http://127.0.0.1:8420", Path("/data")
            ),
        ),
        (
            {"ONEBERTH_WORKER_NAME": "u", "ONEBERTH_WORKER_URL": "http://backend:8421"},
            LaunchedWorker("u", "http://backend:8421", None, None),
        ),
        ({}, None),
    ],
)
def test_a_worker_reads_its_name_and_the_worker_listener(
    environ: dict[str, str], expected: LaunchedWorker | None
) -> None:
    assert LaunchedWorker.from_environ(environ) == expected


def test_a_worker_reads_its_token_from_standard_input_or_a_file(
    tmp_path: Path,
) -> None:
    assert read_token(io.StringIO("ob_svc_abc"), {}) == "ob_svc_abc"
    assert read_token(io.StringIO("ob_svc_abc\n"), {}) == "ob_svc_abc"
    (tmp_path / "token").write_text("ob_svc_file\n")
    named = {"ONEBERTH_TOKEN_FILE": os.fspath(tmp_path / "token")}
    assert read_token(io.StringIO("ignored"), named) == "ob_svc_file"


def test_one_launcher_holds_a_data_directory(tmp_path: Path) -> None:
    data = tmp_path / "data"
    with DataLock.claim(data):
        assert (data / "launcher.lock").read_text() == f"{os.getpid()}\n"
        with pytest.raises(AlreadyRunning) as second:
            DataLock.claim(data)
        assert second.value.pid == os.getpid()
    with DataLock.claim(data):
        pass
    assert (data / "launcher.lock").read_text() == ""


# The mounts of an untrusted worker, on the real file system.


@pytest.fixture
def own(tmp_path: Path) -> Path:
    """An untrusted worker's own directory, with what an earlier run of the
    worker left in it: a link that stays inside, and a link to the person's
    keys."""
    own = tmp_path / "data" / "workers" / "u1"
    (own / "state").mkdir(parents=True)
    (tmp_path / "home" / ".ssh").mkdir(parents=True)
    (own / "inside").symlink_to(own / "state")
    (own / "keys").symlink_to(tmp_path / "home" / ".ssh")
    return own


def test_a_mount_of_an_untrusted_worker_is_followed_through_its_links(
    own: Path, tmp_path: Path
) -> None:
    keys = tmp_path / "home" / ".ssh"

    def problem(source: Path, within: Path | None = own) -> str | None:
        return mount_problem(MountPlan(source, "/x", False, True, within))

    for inside in (own, own / "state", own / "inside", own / "not" / "there" / "yet"):
        assert problem(inside) is None, inside
    assert problem(own / "keys") == (
        f"its mount {own / 'keys'} leads to {keys}, outside {own}"
    )
    assert f"leads to {keys / 'id'}, outside" in (problem(own / "keys" / "id") or "")
    # A trusted component's mount is kept inside nothing.
    assert problem(keys, within=None) is None
    # A loop of links leads nowhere: it is no way out, and no crash.
    (own / "loop").symlink_to(own / "loop")
    assert problem(own / "loop") is None or "cannot be followed" in (
        problem(own / "loop") or ""
    )


def test_a_data_directory_behind_a_link_keeps_its_workers_inside(
    own: Path, tmp_path: Path
) -> None:
    # The person keeps the data directory on another disk, behind a link.
    (tmp_path / "shortcut").symlink_to(tmp_path / "data")
    linked = tmp_path / "shortcut" / "workers" / "u1"

    def problem(source: Path) -> str | None:
        return mount_problem(MountPlan(source, "/x", False, True, linked))

    assert problem(linked / "state") is None
    assert f"leads to {tmp_path / 'home' / '.ssh'}, outside" in (
        problem(linked / "keys") or ""
    )


async def test_no_container_starts_with_a_mount_that_leads_out(
    own: Path, tmp_path: Path
) -> None:
    mount = MountPlan(own / "keys" / "new", "/x", False, create=True, within=own)
    plan = ContainerPlan(
        name="oneberth-test-u1",
        image="notes:1",
        command=(),
        environment={},
        mounts=(mount,),
        networks=(),
        published=(),
        gateway=False,
        user=None,
        labels={},
    )

    with pytest.raises(LauncherError, match=r"leads to .*\.ssh/new, outside .*u1"):
        await DockerCli().start(plan, None)
    # Nothing was created on the way out, and Docker was never asked.
    assert not (tmp_path / "home" / ".ssh" / "new").exists()
