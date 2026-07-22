# SPDX-License-Identifier: MIT
"""External tool resolution must be portable across Linux and macOS runners."""

from __future__ import annotations

from pathlib import Path

import pytest

import colorist.cuts
import colorist.ffgraph
import colorist.grade
import colorist.render
import colorist.verify
from colorist.tools import resolve_tool
from tests import conftest


def test_every_module_resolves_the_same_ffmpeg_as_the_test_fixtures() -> None:
    """The fixture binary must be the binary the package itself will execute."""
    expected = resolve_tool("ffmpeg")
    assert str(conftest.FFMPEG) == expected
    assert colorist.render.FFMPEG == expected
    assert colorist.ffgraph.FFMPEG == expected
    assert colorist.grade.FFMPEG == expected
    assert colorist.cuts.FFMPEG == expected
    assert colorist.verify.FFMPEG == expected


def test_every_module_resolves_the_same_ffprobe() -> None:
    expected = resolve_tool("ffprobe")
    assert colorist.render.FFPROBE == expected
    assert colorist.grade.FFPROBE == expected
    assert colorist.cuts.FFPROBE == expected


def test_resolved_tools_are_executable_files() -> None:
    for name in ("ffmpeg", "ffprobe"):
        resolved = Path(resolve_tool(name))
        assert resolved.exists(), f"{name} resolved to a path that does not exist"


def test_environment_override_wins_over_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLORIST_FFMPEG", "/custom/ffmpeg")
    assert resolve_tool("ffmpeg") == "/custom/ffmpeg"


def test_missing_tool_names_the_binary_and_the_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COLORIST_FFPROBE", raising=False)
    monkeypatch.setattr("colorist.tools.shutil.which", lambda name: None)
    with pytest.raises(FileNotFoundError) as excinfo:
        resolve_tool("ffprobe")
    message = str(excinfo.value)
    assert "ffprobe" in message
    assert "COLORIST_FFPROBE" in message


def test_no_hardcoded_install_prefix_remains() -> None:
    """A Homebrew-only path is what made the Linux CI job fail before testing."""
    root = Path(__file__).resolve().parents[1]
    needle = "/".join(("opt", "homebrew"))  # built at runtime so this file is clean
    offenders = []
    for path in list((root / "src").rglob("*.py")) + list((root / "tests").rglob("*.py")):
        if needle in path.read_text():
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_preflight_accepts_the_installed_tools() -> None:
    from colorist.tools import preflight

    resolved = preflight()
    assert Path(resolved["ffmpeg"]).name.startswith("ffmpeg")
    assert Path(resolved["ffprobe"]).name.startswith("ffprobe")


def test_preflight_rejects_a_tool_that_is_not_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    """Resolution alone proves nothing: an override may point anywhere.

    Before this check, COLORIST_FFMPEG=/bin/true satisfied the documented
    install verification, so a user could believe a working install while every
    subsequent measurement came from a build that was never run.
    """
    from colorist.tools import PreflightError, preflight

    impostor = tmp_path / "ffmpeg"
    impostor.write_text("#!/bin/sh\nexit 0\n")
    impostor.chmod(0o755)
    monkeypatch.setenv("COLORIST_FFMPEG", str(impostor))
    monkeypatch.setenv("COLORIST_FFPROBE", str(impostor))
    with pytest.raises(PreflightError, match="recognizable ffmpeg version"):
        preflight()


def test_preflight_rejects_an_unsupported_major_version(monkeypatch, tmp_path: Path) -> None:
    """Ubuntu 24.04 LTS ships ffmpeg 6.1.1, which decodes without complaint."""
    from colorist.tools import PreflightError, preflight

    old = tmp_path / "ffmpeg"
    old.write_text(
        "#!/bin/sh\n"
        "echo 'ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023 the FFmpeg developers'\n"
    )
    old.chmod(0o755)
    monkeypatch.setenv("COLORIST_FFMPEG", str(old))
    monkeypatch.setenv("COLORIST_FFPROBE", str(old))
    with pytest.raises(PreflightError, match="requires ffmpeg 8"):
        preflight()
