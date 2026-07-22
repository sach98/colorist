# SPDX-License-Identifier: MIT
"""Shared lossless video fixtures for ffmpeg-backed tests."""

from __future__ import annotations

from pathlib import Path
import subprocess

import colour
import numpy as np

from colorist.tools import resolve_tool


FFMPEG = resolve_tool("ffmpeg")


def _run_ffmpeg(args: list[str]) -> None:
    """Run the project-pinned ffmpeg binary and retain failures in pytest output."""
    subprocess.run(
        [str(FFMPEG), "-hide_banner", "-y", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def build_three_shot_fixture(
    tmp_path: Path, *, frames_per_shot: int = 10, fps: int = 25
) -> Path:
    """Create three solid-color CFR shots joined through the concat demuxer."""
    duration = frames_per_shot / fps
    parts: list[Path] = []
    for index, color in enumerate(("black", "white", "blue")):
        part = tmp_path / f"shot-{index}.mkv"
        _run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:size=64x48:rate={fps}:duration={duration}",
                "-frames:v",
                str(frames_per_shot),
                "-c:v",
                "ffv1",
                str(part),
            ]
        )
        parts.append(part)

    concat_list = tmp_path / "shots.ffconcat"
    concat_list.write_text(
        "ffconcat version 1.0\n"
        + "".join(f"file '{part.as_posix()}'\n" for part in parts)
    )
    output = tmp_path / "three-shots.mkv"
    _run_ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(output),
        ]
    )
    return output


def build_vfr_fixture(tmp_path: Path) -> Path:
    """Create five frames with intentionally non-uniform PTS values in seconds."""
    output = tmp_path / "variable-pts.mkv"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x48:rate=25:duration=0.2",
            "-vf",
            "settb=expr=1/1000,setpts=N*N*40",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "ffv1",
            str(output),
        ]
    )
    return output


def build_casted_three_shot_fixture(
    tmp_path: Path,
    *,
    casts: tuple[tuple[float, float, float], ...],
    frames_per_shot: int = 10,
    fps: int = 25,
    working_grey: float = 0.18,
    structured: bool = False,
) -> Path:
    """Create RGB16 CFR shots whose known scene-linear greys have diagonal casts.

    The raw input is RGB48LE and the FFV1 output is gbrp16le, avoiding an
    incidental source YUV conversion.  The source code values use the project's
    BT.1886 encode so ``curve_gamut=None`` decodes back to these known values.
    """
    if len(casts) != 3:
        raise ValueError("fixture requires exactly three casts")

    width, height = 64, 48
    y, x = np.mgrid[0:height, 0:width]
    modulation = 0.75 + 0.50 * (
        0.60 * x / (width - 1) + 0.40 * y / (height - 1)
    )
    parts: list[Path] = []
    for index, cast in enumerate(casts):
        base = working_grey * modulation[..., None] if structured else working_grey
        working_rgb = base * np.asarray(cast, dtype=np.float64)
        if np.any(working_rgb <= 0.0) or np.any(working_rgb > 1.0):
            raise ValueError("fixture cast produces an invalid scene-linear RGB value")
        code_rgb = np.power(working_rgb, 1.0 / 2.4)
        pixels = np.rint(code_rgb * 65535.0).astype("<u2")
        frame = np.broadcast_to(pixels, (height, width, 3)).copy()
        raw_video = frame.tobytes() * frames_per_shot
        part = tmp_path / f"casted-shot-{index}.mkv"
        subprocess.run(
            [
                str(FFMPEG),
                "-hide_banner",
                "-y",
                "-f",
                "rawvideo",
                "-pixel_format",
                "rgb48le",
                "-video_size",
                f"{width}x{height}",
                "-framerate",
                str(fps),
                "-i",
                "-",
                "-frames:v",
                str(frames_per_shot),
                "-pix_fmt",
                "gbrp16le",
                "-color_range",
                "pc",
                "-colorspace",
                "bt709",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-c:v",
                "ffv1",
                str(part),
            ],
            input=raw_video,
            check=True,
            capture_output=True,
        )
        parts.append(part)

    concat_list = tmp_path / "casted-shots.ffconcat"
    concat_list.write_text(
        "ffconcat version 1.0\n"
        + "".join(f"file '{part.as_posix()}'\n" for part in parts)
    )
    output = tmp_path / "casted-three-shots.mkv"
    _run_ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(output),
        ]
    )
    return output


def build_slog3_casted_three_shot_fixture(
    tmp_path: Path,
    *,
    casts: tuple[tuple[float, float, float], ...],
    frames_per_shot: int = 10,
    fps: int = 25,
    working_grey: float = 0.18,
    structured: bool = False,
) -> Path:
    """Create three S-Log3/S-Gamut3.Cine encoded neutral-with-cast shots.

    The fixture starts in the project's scene-linear Rec.709 working space,
    transforms each coloured grey into S-Gamut3.Cine, then uses
    :func:`colour.models.log_encoding_SLog3` before lossless RGB16 encoding.
    This makes the end-to-end fixture exercise the same camera-code input
    transform used by the consistency workflow.
    """
    if len(casts) != 3:
        raise ValueError("fixture requires exactly three casts")

    width, height = 64, 48
    y, x = np.mgrid[0:height, 0:width]
    modulation = 0.75 + 0.50 * (
        0.60 * x / (width - 1) + 0.40 * y / (height - 1)
    )
    source_space = colour.RGB_COLOURSPACES["ITU-R BT.709"]
    camera_space = colour.RGB_COLOURSPACES["S-Gamut3.Cine"]
    parts: list[Path] = []
    for index, cast in enumerate(casts):
        base = working_grey * modulation[..., None] if structured else working_grey
        working_rgb = base * np.asarray(cast, dtype=np.float64)
        if np.any(working_rgb <= 0.0):
            raise ValueError("fixture cast produces non-positive scene-linear RGB")
        linear_camera = colour.RGB_to_RGB(
            working_rgb,
            source_space,
            camera_space,
            chromatic_adaptation_transform="CAT02",
            apply_cctf_decoding=False,
            apply_cctf_encoding=False,
        )
        code_rgb = np.asarray(colour.models.log_encoding_SLog3(linear_camera))
        if np.any(code_rgb < 0.0) or np.any(code_rgb > 1.0):
            raise ValueError("fixture S-Log3 code values must be in the LUT domain")
        pixels = np.rint(code_rgb * 65535.0).astype("<u2")
        frame = np.broadcast_to(pixels, (height, width, 3)).copy()
        part = tmp_path / f"slog3-casted-shot-{index}.mkv"
        subprocess.run(
            [
                str(FFMPEG),
                "-hide_banner",
                "-y",
                "-f",
                "rawvideo",
                "-pixel_format",
                "rgb48le",
                "-video_size",
                f"{width}x{height}",
                "-framerate",
                str(fps),
                "-i",
                "-",
                "-frames:v",
                str(frames_per_shot),
                "-pix_fmt",
                "gbrp16le",
                "-color_range",
                "pc",
                "-colorspace",
                "bt709",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-c:v",
                "ffv1",
                str(part),
            ],
            input=frame.tobytes() * frames_per_shot,
            check=True,
            capture_output=True,
        )
        parts.append(part)

    concat_list = tmp_path / "slog3-casted-shots.ffconcat"
    concat_list.write_text(
        "ffconcat version 1.0\n"
        + "".join(f"file '{part.as_posix()}'\n" for part in parts)
    )
    output = tmp_path / "slog3-casted-three-shots.mkv"
    _run_ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(output),
        ]
    )
    return output
