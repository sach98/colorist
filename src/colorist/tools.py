# SPDX-License-Identifier: MIT
"""Single resolution point for the external ffmpeg tools this project shells out to.

Resolution order is an explicit environment override first, then ``PATH``.  There
is deliberately no hardcoded install prefix: a Homebrew-only path made the Linux
CI job fail before it could test anything.
"""

from __future__ import annotations

import os
import shutil


#: Environment variable consulted for each tool, keyed by executable name.
OVERRIDE_VARIABLES = {"ffmpeg": "COLORIST_FFMPEG", "ffprobe": "COLORIST_FFPROBE"}


def resolve_tool(name: str) -> str:
    """Return the absolute path of ``name`` from its override variable or PATH."""
    variable = OVERRIDE_VARIABLES.get(name, f"COLORIST_{name.upper()}")
    override = os.environ.get(variable)
    if override:
        return override
    resolved = shutil.which(name)
    if resolved is None:
        raise FileNotFoundError(
            f"required executable not found on PATH: {name}. "
            f"Install it, or set {variable} to its absolute path."
        )
    return resolved


#: The project's empirical numbers were all measured on ffmpeg 8.x, and the
#: render graph depends on filters whose negotiation behaviour changed across
#: major versions. Older builds decode and encode without complaint, so nothing
#: except this check stands between a distro's ffmpeg 6 and silently wrong output.
REQUIRED_FFMPEG_MAJOR = 8

#: Capabilities the render, measurement, cut-detection, and mezzanine paths need.
REQUIRED_FILTERS = ("scale", "lut3d", "scdet")
REQUIRED_ENCODERS = ("ffv1",)

#: Opt out of the version gate to try an unsupported build. The capability
#: checks below still run. This exists because refusing every non-8.x build
#: outright also refused the project's own advisory CI lane, which tracks
#: ffmpeg master precisely to catch upstream changes early: a lane that can
#: never pass reports nothing. Users who want to run a newer release before
#: this project has been measured on it can make the same trade knowingly.
ALLOW_UNSUPPORTED_VARIABLE = "COLORIST_ALLOW_UNSUPPORTED_FFMPEG"


class PreflightError(RuntimeError):
    """A required external tool is missing, too old, or lacks a capability."""


def _tool_banner(path: str) -> str:
    import subprocess

    try:
        completed = subprocess.run(
            [path, "-hide_banner", "-version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise PreflightError(
            f"could not run {path} to determine its version: {error}"
        ) from error
    return completed.stdout


def _parse_major(banner: str, path: str) -> int:
    import re

    # ffmpeg prints "ffmpeg version 8.1.2", ffprobe prints "ffprobe version 8.1.2",
    # and static builds prefix the number with "n" ("ffmpeg version n8.1.2").
    match = re.search(r"^(?:ffmpeg|ffprobe) version n?(\d+)\.", banner, re.M)
    if match is not None:
        return int(match.group(1))
    first = banner.splitlines()[0] if banner else "(no output)"
    # Master and nightly builds carry a build number instead of a release
    # version ("ffmpeg version N-125716-g1b1f602699-20260722"), so say that
    # rather than claiming the output was unrecognizable.
    if re.search(r"^(?:ffmpeg|ffprobe) version N-", first):
        raise PreflightError(
            f"{path} is an unversioned development build ({first.split(' Copyright')[0]}). "
            f"This project is measured on ffmpeg {REQUIRED_FFMPEG_MAJOR}.x releases. "
            f"Install one, or set {ALLOW_UNSUPPORTED_VARIABLE}=1 to proceed anyway."
        )
    raise PreflightError(
        f"{path} did not report a recognizable ffmpeg version. First line: {first}"
    )


def preflight() -> dict[str, str]:
    """Fail closed unless the resolved tools can actually do this project's work.

    Returns the resolved paths on success. Every processing command calls this
    before touching a frame, because the alternative is a plausible-looking
    number produced by a build this project was never measured on.
    """
    import subprocess

    ffmpeg = resolve_tool("ffmpeg")
    ffprobe = resolve_tool("ffprobe")

    allow_unsupported = bool(os.environ.get(ALLOW_UNSUPPORTED_VARIABLE))
    if not allow_unsupported:
        for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
            major = _parse_major(_tool_banner(path), path)
            if major != REQUIRED_FFMPEG_MAJOR:
                raise PreflightError(
                    f"{name} at {path} reports major version {major}, but this project "
                    f"requires ffmpeg {REQUIRED_FFMPEG_MAJOR}.x. Distribution packages are "
                    "often older than that (Ubuntu 24.04 LTS ships 6.1.1). Install an "
                    f"ffmpeg {REQUIRED_FFMPEG_MAJOR} build, point "
                    f"{OVERRIDE_VARIABLES[name]} at one, or set "
                    f"{ALLOW_UNSUPPORTED_VARIABLE}=1 to proceed anyway."
                )

    listed = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"], check=True, capture_output=True, text=True
    ).stdout
    missing_filters = [f for f in REQUIRED_FILTERS if f" {f} " not in listed]
    if missing_filters:
        raise PreflightError(
            f"ffmpeg at {ffmpeg} lacks required filters: {', '.join(missing_filters)}"
        )

    encoders = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"], check=True, capture_output=True, text=True
    ).stdout
    missing_encoders = [e for e in REQUIRED_ENCODERS if e not in encoders]
    if missing_encoders:
        raise PreflightError(
            f"ffmpeg at {ffmpeg} lacks required encoders: {', '.join(missing_encoders)}"
        )
    return {"ffmpeg": ffmpeg, "ffprobe": ffprobe}
