# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The launcher's small parts: the port of the front listener, the browser it
looks for, the window's command, what a backend and a worker read from their
environment, and the lock on the data directory."""

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


def test_a_backend_reads_where_to_listen() -> None:
    environ = {
        "ONEBERTH_DATA_DIR": "/data",
        "ONEBERTH_HOST": "127.0.0.1",
        "ONEBERTH_FRONT_PORT": "8420",
        "ONEBERTH_WORKER_PORT": "8421",
    }
    assert LaunchedBackend.from_environ(environ) == LaunchedBackend(
        Path("/data"), "127.0.0.1", 8420, 8421
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
