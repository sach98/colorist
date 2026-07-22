# SPDX-License-Identifier: MIT
"""Fresh-clone, interpreter-floor, and built-wheel packaging regressions."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from colorist.__main__ import _check_python_floor
from colorist.workflow import _resolve_preset, _resolve_profile


ROOT = Path(__file__).parents[1]

# The README promises SPDX or a sidecar on every tracked file except these.
_SPDX_EXEMPT = {"LICENSE", "LICENSE-references", ".gitignore"}


def test_every_tracked_file_carries_spdx_or_a_sidecar() -> None:
    """Enforce the README's load-bearing licensing claim so it cannot regress."""
    listing = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
    )
    if listing.returncode != 0:
        pytest.skip("not a git checkout (e.g. an extracted source archive)")
    tracked = listing.stdout.split()
    missing = []
    for name in tracked:
        if name in _SPDX_EXEMPT or name.endswith(".license"):
            continue
        if (ROOT / (name + ".license")).exists():
            continue
        head = "".join((ROOT / name).read_text(errors="ignore").splitlines(keepends=True)[:40])
        if "SPDX-License-Identifier" not in head:
            missing.append(name)
    assert missing == [], f"tracked files without SPDX or a sidecar: {missing}"


def _copy_build_source(destination: Path) -> Path:
    source = destination / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE", "LICENSE-references"):
        shutil.copy2(ROOT / name, source / name)
    shutil.copytree(
        ROOT / "src",
        source / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    shutil.copytree(ROOT / "presets", source / "presets")
    return source


def test_editable_clone_resolves_repository_presets(tmp_path: Path) -> None:
    assert _resolve_preset("interview", "gates").resolve() == (
        ROOT / "presets/gates/interview.yaml"
    ).resolve()
    assert _resolve_profile("h264-yt-sdr").resolve() == (
        ROOT / "presets/delivery/h264-yt-sdr.yaml"
    ).resolve()
    assert (ROOT / "src/colorist/presets/gates/interview.yaml").read_text() == (
        ROOT / "presets/gates/interview.yaml"
    ).read_text()
    installed = tmp_path / "editable"
    source = _copy_build_source(tmp_path)
    # pip must run under an interpreter that can reach the build backend. The base
    # executable is outside the venv that pip install -e '.[dev]' populated, and
    # GitHub runners ship no setuptools there, so the isolated build below is
    # what makes this portable rather than a property of one developer's machine.
    build_python = sys.executable
    subprocess.run(
        [
            build_python,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(installed),
            "--editable",
            str(source),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    probe = subprocess.run(
        [
            build_python,
            "-c",
            "import site; "
            f"site.addsitedir({str(installed)!r}); "
            "from importlib import resources; "
            "preset = resources.files('colorist').joinpath(" 
            "'presets', 'gates', 'interview.yaml'); "
            "print(preset.is_file())",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "True"


def test_python_floor_has_a_friendly_preimport_error() -> None:
    with pytest.raises(SystemExit) as error:
        _check_python_floor((3, 10, 14))

    assert str(error.value) == (
        "colorist requires Python 3.11 or newer; running Python 3.10.14"
    )
    _check_python_floor((3, 11, 0))


def test_built_wheel_installs_with_bundled_presets(tmp_path: Path) -> None:
    source = _copy_build_source(tmp_path)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    # pip must run under an interpreter that can reach the build backend. The base
    # executable is outside the venv that pip install -e '.[dev]' populated, and
    # GitHub runners ship no setuptools there, so the isolated build below is
    # what makes this portable rather than a property of one developer's machine.
    build_python = sys.executable
    built = subprocess.run(
        [
            build_python,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            str(source),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(wheelhouse.glob("colorist-*.whl"))
    assert len(wheels) == 1, built.stdout + built.stderr
    installed = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(installed),
            str(wheels[0]),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(installed)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; "
            "import colorist; "
            "from colorist.gates import load_gates; "
            "from colorist.grade import _load_delivery_profile; "
            "from colorist.workflow import _resolve_preset, _resolve_profile; "
            "gates = load_gates(_resolve_preset('interview', 'gates')); "
            "profile = _load_delivery_profile(_resolve_profile('h264-yt-sdr')); "
            "print(Path(colorist.__file__).resolve()); "
            "print(f'wheel preset gates={len(gates.gates)} profile={profile.container}')",
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    lines = probe.stdout.splitlines()
    assert Path(lines[0]).is_relative_to(installed)
    assert lines[1] == "wheel preset gates=8 profile=mp4"
