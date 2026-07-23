# SPDX-License-Identifier: MIT
"""End-to-end tests for per-shot FFV1 grading and single delivery encoding."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

from colorist.corrections import Correction, compile_shot_lut, solve_wb
from colorist.cuts import read_cutlist
from colorist.grade import RefuseOverwriteError, VariableFrameRateError, grade_file
from colorist.lut import write_cube
from colorist.render import ConvertParams, read_frame_rgb, render_segment
from colorist.tools import resolve_tool
from tests.conftest import build_casted_three_shot_fixture, build_vfr_fixture


FFMPEG = resolve_tool("ffmpeg")
FFPROBE = resolve_tool("ffprobe")
H264_PROFILE = Path("presets/delivery/h264-yt-sdr.yaml")
CASTS = (
    (1.24, 0.91, 0.77),
    (0.82, 1.16, 1.05),
    (1.08, 0.78, 1.31),
)
WORKING_GREY = 0.18
P709_FULL = ConvertParams(
    range="full", matrix="bt709", transfer="bt709", primaries="bt709"
)
P709_LIMITED = ConvertParams(
    range="limited", matrix="bt709", transfer="bt709", primaries="bt709"
)


def _write_cutlist(path: Path, *, frames_per_shot: int = 10) -> Path:
    path.write_text(
        "start_frame,end_frame\n"
        f"0,{frames_per_shot}\n"
        f"{frames_per_shot},{frames_per_shot * 2}\n"
        f"{frames_per_shot * 2},{frames_per_shot * 3}\n"
    )
    return path


def _read_limited_frame_rgb(path: Path, frame_index: int) -> np.ndarray:
    """Decode a profile-limited frame to full-range RGB for comparison."""
    # read_frame_rgb's fixed full-range decode is appropriate for mezzanines;
    # delivery comparisons need FFmpeg to expand the profile's limited YUV.
    out = subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"select=eq(n\\,{frame_index}),"
            "scale=in_range=tv:out_range=pc:in_color_matrix=bt709:out_color_matrix=bt709,"
            "format=gbrpf32le",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gbrpf32le",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    probe = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height = (int(value) for value in probe.stdout.strip().split(","))
    planes = np.frombuffer(out.stdout, dtype=np.float32).reshape(3, height, width)
    green, blue, red = planes
    decoded = np.stack([red, green, blue], axis=-1).astype(np.float64)
    return decoded


def _profile_tags(path: Path) -> dict[str, str]:
    probe = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=pix_fmt,color_range,color_space,color_transfer,color_primaries",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(probe.stdout)["streams"][0]


def test_grade_file_neutralizes_each_shot_and_keeps_cut_boundaries_exact(
    tmp_path: Path,
) -> None:
    src = build_casted_three_shot_fixture(tmp_path, casts=CASTS)
    cutlist_path = _write_cutlist(tmp_path / "cuts.csv")
    shots = read_cutlist(cutlist_path)
    corrections = {
        index: Correction(
            wb_gains=solve_wb(WORKING_GREY * np.asarray(cast, dtype=np.float64))
        )
        for index, cast in enumerate(CASTS)
    }

    delivered = grade_file(
        src,
        cutlist_path,
        corrections,
        look=None,
        curve_gamut=None,
        delivery_profile=H264_PROFILE,
        workdir=tmp_path / "delivery",
    )

    assert delivered.name == "casted-three-shots.graded.mp4"
    for shot in shots:
        midpoint = (shot.start_frame + shot.end_frame) // 2
        median = np.median(
            read_frame_rgb(delivered, midpoint, P709_LIMITED), axis=(0, 1)
        )
        assert np.max(np.abs(median - median[0])) <= 2 / 255

    # Re-rendering each isolated shot gives the expected first and last frame at
    # every cut.  The separate luma levels make a one-frame LUT leak visible.
    for shot_index, shot in enumerate(shots):
        table_path = tmp_path / f"reference-{shot_index}.cube"
        write_cube(
            table_path,
            # grade_file must compile the same per-shot LUT used here.
            compile_shot_lut(corrections[shot_index], look=None, curve_gamut=None),
            title=f"reference shot {shot_index}",
        )
        reference = tmp_path / f"reference-{shot_index}.mkv"
        render_segment(
            src,
            reference,
            trim=(shot.start_frame, shot.end_frame),
            idt_cube=None,
            corr_cube=table_path,
            in_params=P709_FULL,
            out_params=P709_FULL,
        )
        for source_frame, segment_frame in (
            (shot.start_frame, 0),
            (shot.end_frame - 1, shot.end_frame - shot.start_frame - 1),
        ):
            actual = _read_limited_frame_rgb(delivered, source_frame)
            expected = read_frame_rgb(reference, segment_frame, P709_FULL)
            assert float(np.max(np.abs(actual - expected))) <= 1 / 255

    assert _profile_tags(delivered) == {
        "pix_fmt": "yuv420p",
        "color_range": "tv",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }


def test_grade_file_refuses_existing_delivery_output(tmp_path: Path) -> None:
    src = build_casted_three_shot_fixture(tmp_path, casts=CASTS)
    cutlist_path = _write_cutlist(tmp_path / "cuts.csv")
    corrections = {index: Correction() for index in range(3)}
    workdir = tmp_path / "delivery"

    grade_file(
        src,
        cutlist_path,
        corrections,
        look=None,
        curve_gamut=None,
        delivery_profile=H264_PROFILE,
        workdir=workdir,
    )

    with pytest.raises(RefuseOverwriteError, match="exists"):
        grade_file(
            src,
            cutlist_path,
            corrections,
            look=None,
            curve_gamut=None,
            delivery_profile=H264_PROFILE,
            workdir=workdir,
        )


def test_grade_file_refuses_variable_frame_rate_input(tmp_path: Path) -> None:
    src = build_vfr_fixture(tmp_path)
    cutlist_path = tmp_path / "cuts.csv"
    cutlist_path.write_text("start_frame,end_frame\n0,5\n")

    with pytest.raises(VariableFrameRateError, match="CFR"):
        grade_file(
            src,
            cutlist_path,
            {0: Correction()},
            look=None,
            curve_gamut=None,
            delivery_profile=H264_PROFILE,
            workdir=tmp_path / "delivery",
        )


def test_cfr_guard_tolerates_timebase_quantization(tmp_path: Path) -> None:
    """Ordinary 24fps footage must not be mistaken for variable frame rate.

    Presentation stamps are integer ticks and 24 is not exactly representable,
    so a genuinely constant 24fps stream reports intervals that alternate
    between 0.041666 and 0.041667. That 1 microsecond step is 2.4e-5 relative,
    and the original rel_tol of 1e-6 was 24 times tighter, so it refused a real
    121 frame 24fps H.264 file outright (observed 2026-07-23).
    """
    from colorist.grade import _require_cfr

    pts = [0.0]
    for index in range(120):
        pts.append(round(pts[-1] + (0.041666 if index % 3 else 0.041667), 6))
    _require_cfr(pts)


def test_cfr_guard_still_refuses_genuine_variable_rate() -> None:
    """The loosened tolerance must not let real VFR through.

    The project's own VFR fixture spans a 7x range between its shortest and
    longest interval, which is nowhere near timebase noise.
    """
    from colorist.grade import VariableFrameRateError, _require_cfr

    with pytest.raises(VariableFrameRateError):
        _require_cfr([0.0, 0.04, 0.16, 0.36, 0.64])
