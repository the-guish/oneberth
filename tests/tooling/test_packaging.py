# SPDX-License-Identifier: Apache-2.0
# Copyright The Oneberth Authors

"""What every distribution under python/ carries with it.

Each package names `LICENSE`, `NOTICE` and `AUTHORS` as its licence files, and
PEP 639 globs cannot climb out of the package's directory, so each holds a
copy of the root's. A copy is a thing that drifts; this holds it to the root.
"""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = sorted(path.parent for path in (ROOT / "python").glob("*/pyproject.toml"))


def test_there_are_packages_to_check():
    assert [package.name for package in PACKAGES] == ["oneberth", "oneberth-core"]


@pytest.mark.io
@pytest.mark.parametrize("package", PACKAGES, ids=lambda path: path.name)
def test_each_package_carries_the_roots_licence_files(package):
    project = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE", "NOTICE", "AUTHORS"]
    for name in project["license-files"]:
        assert (package / name).read_bytes() == (ROOT / name).read_bytes(), (
            f"{package.name}/{name} differs from the root's; copy it again"
        )


@pytest.mark.io
@pytest.mark.parametrize("package", PACKAGES, ids=lambda path: path.name)
def test_each_package_takes_its_version_from_the_repository(package):
    pyproject = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"] == {
        "source": "vcs",
        "raw-options": {"root": "../.."},
    }
