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

    # The advisory CI lane sets the waiver for the whole run, and this test
    # exists to prove the gate fires, so it must not inherit that.
    monkeypatch.delenv("COLORIST_ALLOW_UNSUPPORTED_FFMPEG", raising=False)

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

    # The advisory CI lane sets the waiver for the whole run, and this test
    # exists to prove the gate fires, so it must not inherit that.
    monkeypatch.delenv("COLORIST_ALLOW_UNSUPPORTED_FFMPEG", raising=False)

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


def _fake_ffmpeg(tmp_path: Path, banner: str) -> Path:
    tool = tmp_path / "ffmpeg"
    tool.write_text(f"#!/bin/sh\necho '{banner}'\n")
    tool.chmod(0o755)
    return tool


def test_preflight_names_a_development_build_accurately(monkeypatch, tmp_path: Path) -> None:
    """A master build has a build number, not a version, and should be told so.

    Observed on the advisory CI lane: `ffmpeg version
    N-125716-g1b1f602699-20260722`. Reporting that as "unrecognizable" sent 19
    tests into confusing failures; the accurate message names the situation and
    the opt-out.
    """
    from colorist.tools import PreflightError, preflight

    # The advisory CI lane sets the waiver for the whole run, and this test
    # exists to prove the gate fires, so it must not inherit that.
    monkeypatch.delenv("COLORIST_ALLOW_UNSUPPORTED_FFMPEG", raising=False)

    tool = _fake_ffmpeg(tmp_path, "ffmpeg version N-125716-g1b1f602699-20260722 Copyright (c) 2000-2026")
    monkeypatch.setenv("COLORIST_FFMPEG", str(tool))
    monkeypatch.setenv("COLORIST_FFPROBE", str(tool))
    with pytest.raises(PreflightError, match="unversioned development build"):
        preflight()


def test_the_version_gate_can_be_waived_but_capabilities_cannot(monkeypatch, tmp_path: Path) -> None:
    """The opt-out exists so the advisory lane can actually run.

    A lane that can never pass reports nothing, so it must be able to exercise
    the code against a newer build. What it must NOT do is waive the capability
    checks, because those are what make the render graph work at all.
    """
    from colorist.tools import ALLOW_UNSUPPORTED_VARIABLE, PreflightError, preflight

    tool = _fake_ffmpeg(tmp_path, "ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023")
    monkeypatch.setenv("COLORIST_FFMPEG", str(tool))
    monkeypatch.setenv("COLORIST_FFPROBE", str(tool))
    monkeypatch.setenv(ALLOW_UNSUPPORTED_VARIABLE, "1")
    # Version is waived, so it gets as far as the capability check and fails there.
    with pytest.raises(PreflightError, match="lacks required filters"):
        preflight()


def test_waiving_the_version_gate_accepts_the_real_installed_tools(monkeypatch) -> None:
    from colorist.tools import ALLOW_UNSUPPORTED_VARIABLE, preflight

    monkeypatch.setenv(ALLOW_UNSUPPORTED_VARIABLE, "1")
    resolved = preflight()
    assert Path(resolved["ffmpeg"]).name.startswith("ffmpeg")
