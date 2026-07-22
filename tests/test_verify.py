# SPDX-License-Identifier: MIT
"""Decoded-delivery verification fixtures and report-contract tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

from colorist.corrections import Correction, solve_wb
from colorist.cuts import Shot, read_cutlist
from colorist.gates import load_gates
from colorist.grade import grade_file
from colorist.measure import ShotMeasurement, measure_shot, sample_positions
from colorist.render import ConvertParams
from colorist.tools import resolve_tool
from colorist.verify import _introduced_clipping_statistics, verify_delivery
from tests.conftest import build_casted_three_shot_fixture


FFMPEG = resolve_tool("ffmpeg")
H264_PROFILE = Path("presets/delivery/h264-yt-sdr.yaml")
GATES = Path("presets/gates/interview.yaml")
P709_FULL = ConvertParams(
    range="full", matrix="bt709", transfer="bt709", primaries="bt709"
)
CASTS = (
    (1.12, 1.00, 0.92),
    (0.95, 1.10, 1.05),
    (1.04, 0.93, 1.10),
)


def test_wrong_pixel_format_fails_the_delivery_profile(tmp_path: Path):
    # An H.264 file in yuv444p is not an h264-yt-sdr delivery, which requires
    # yuv420p, even with correct colour tags.
    delivery = tmp_path / "yuv444.mp4"
    _run_ffmpeg([
        "-f", "lavfi", "-i", "color=c=gray:size=64x48:rate=25:duration=0.2",
        "-frames:v", "5", "-c:v", "libx264", "-pix_fmt", "yuv444p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        str(delivery),
    ])
    result = verify_delivery(delivery, H264_PROFILE, load_gates(GATES), None, None)
    report = json.loads((tmp_path / "report.json").read_text())
    assert result.state == "FAIL"
    assert report["metadata"]["valid"] is False
    fields = {m["field"] for m in report["metadata"]["mismatches"]}
    assert "pix_fmt" in fields


def test_introduced_clipping_is_endpoint_aware():
    from colorist.verify import _introduced_clipping_statistics

    black = np.zeros((4, 4, 3), dtype=np.float64)
    white = np.ones((4, 4, 3), dtype=np.float64)
    # Source clipped low, delivery clipped high: every sample is newly clipped
    # at the high end, so 100 percent is introduced, not zero.
    stats = _introduced_clipping_statistics([black], [white])
    assert stats["introduced_clipping_percent"] == 100.0
    # The reverse direction is equally introduced.
    reverse = _introduced_clipping_statistics([white], [black])
    assert reverse["introduced_clipping_percent"] == 100.0
    # A sample already clipped at the same end is not newly introduced.
    same = _introduced_clipping_statistics([white], [white])
    assert same["introduced_clipping_percent"] == 0.0


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _write_cutlist(path: Path, *, frames_per_shot: int = 10) -> Path:
    path.write_text(
        "start_frame,end_frame\n"
        f"0,{frames_per_shot}\n"
        f"{frames_per_shot},{frames_per_shot * 2}\n"
        f"{frames_per_shot * 2},{frames_per_shot * 3}\n"
    )
    return path


def _frozen_measurements(src: Path, shots: list[Shot]) -> list[ShotMeasurement]:
    return [
        measure_shot(
            src,
            [shot.start_frame + position for position in sample_positions(shot.end_frame - shot.start_frame)],
            P709_FULL,
            None,
            artifact_dir=src.parent / "masks",
            shot_frame_count=shot.end_frame - shot.start_frame,
        )
        for shot in shots
    ]


def _clean_delivery(
    tmp_path: Path,
) -> tuple[Path, Path, list[Shot], list[ShotMeasurement]]:
    src = build_casted_three_shot_fixture(tmp_path, casts=CASTS, structured=True)
    cuts = read_cutlist(_write_cutlist(tmp_path / "cuts.csv"))
    frozen = _frozen_measurements(src, cuts)
    delivery = grade_file(
        src,
        cuts,
        {
            index: Correction(wb_gains=solve_wb(0.18 * np.asarray(cast)))
            for index, cast in enumerate(CASTS)
        },
        look=None,
        curve_gamut=None,
        delivery_profile=H264_PROFILE,
        workdir=tmp_path / "delivery",
    )
    return src, delivery, cuts, frozen


def _delivery_with_one_illegal_frame(
    tmp_path: Path, illegal_frame: int, frames: int = 9
) -> Path:
    """Build a limited-range delivery whose only illegal frame is ``illegal_frame``.

    The illegal frame carries Y=8 (below the legal 16); every other frame is a
    legal mid grey. Frame indices [0, 2, 4, 6, 8] are the sampling grid, so an
    odd illegal frame is missed by sampling and only an exhaustive scan catches
    it. Stored losslessly as data-level yuv420p tagged limited so the encoder
    does not clamp the illegal sample.
    """
    width, height = 32, 32
    full_range = tmp_path / f"illegal-{illegal_frame}-pc.mkv"
    destination = tmp_path / f"illegal-{illegal_frame}.mkv"
    payload = bytearray()
    for index in range(frames):
        y_value = 8 if index == illegal_frame else 110
        payload += bytes([y_value]) * (width * height)
        payload += bytes([128]) * (width // 2 * (height // 2))
        payload += bytes([128]) * (width // 2 * (height // 2))
    # Store full-range so the below-legal Y=8 survives (a tv-tagged encode would
    # clamp it to 16), then retag as limited via stream copy without rescaling.
    _run_ffmpeg_input(
        [
            "-color_range",
            "pc",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-s",
            f"{width}x{height}",
            "-r",
            "5",
            "-i",
            "-",
            "-frames:v",
            str(frames),
            "-c:v",
            "ffv1",
            "-color_range",
            "pc",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            str(full_range),
        ],
        bytes(payload),
    )
    _run_ffmpeg(
        [
            "-i",
            str(full_range),
            "-c",
            "copy",
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            str(destination),
        ]
    )
    return destination


def _legal_tv_delivery(
    tmp_path: Path, name: str, luma_by_frame: list[int], frames: int = 9
) -> Path:
    """Build a legal limited-range yuv420p delivery with a per-frame neutral Y."""
    width, height = 32, 32
    destination = tmp_path / f"{name}.mkv"
    payload = bytearray()
    for index in range(frames):
        value = luma_by_frame[index]
        if value == 235:
            luma = np.full((height, width), value, dtype=np.uint8)
        else:
            gradient = np.linspace(-24, 24, width, dtype=np.int16)
            luma = np.clip(value + gradient[None, :], 16, 235).astype(np.uint8)
            luma = np.broadcast_to(luma, (height, width))
        payload += luma.tobytes()
        payload += bytes([128]) * (width // 2 * (height // 2))
        payload += bytes([128]) * (width // 2 * (height // 2))
    _run_ffmpeg_input(
        [
            "-color_range",
            "tv",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-s",
            f"{width}x{height}",
            "-r",
            "5",
            "-i",
            "-",
            "-frames:v",
            str(frames),
            "-c:v",
            "ffv1",
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            str(destination),
        ],
        bytes(payload),
    )
    return destination


def test_clipping_gate_catches_a_clipped_frame_between_samples(tmp_path: Path) -> None:
    from colorist.verify import _verify_introduced_clipping, _probe_video_stream
    from colorist.grade import _load_delivery_profile

    frames = 9
    grey = [110] * frames
    # Delivery frame 3 is clipped white (Y=235 -> display code ~1.0); source is
    # grey there. Frame 3 is off the [0, 2, 4, 6, 8] sampling grid.
    clipped = list(grey)
    clipped[3] = 235
    source = _legal_tv_delivery(tmp_path, "clip-source", grey)
    delivery = _legal_tv_delivery(tmp_path, "clip-delivery", clipped)

    profile = _load_delivery_profile(H264_PROFILE)
    report = _verify_introduced_clipping(
        delivery,
        profile,
        frames,
        _probe_video_stream(delivery),
        source,
        ConvertParams(range="limited", matrix="bt709", transfer="bt709", primaries="bt709"),
        None,
    )

    assert report["available"] is True
    assert report["coverage"] == "exhaustive"
    # Frame 3's clipped white clips two of three channels: about 7.4 percent,
    # far over the 0.5 percent gate. Sampling [0, 2, 4, 6, 8] would have found
    # exactly zero, so any nonzero result proves the middle frame was scanned.
    assert report["introduced_clipping_percent"] > 1.0
    assert report["sample_count"] == frames * 32 * 32 * 3


def test_range_gate_catches_an_illegal_frame_between_samples(tmp_path: Path) -> None:
    # Frame 3 is illegal and is not on the [0, 2, 4, 6, 8] sampling grid.
    delivery = _delivery_with_one_illegal_frame(tmp_path, illegal_frame=3)

    result = verify_delivery(delivery, H264_PROFILE, load_gates(GATES), None, None)

    report = json.loads((tmp_path / "report.json").read_text())
    assert report["range"]["coverage"] == "exhaustive"
    assert report["range"]["frames_scanned"] == 9
    assert report["range"]["valid"] is False
    assert result.state == "FAIL"
    offending = [v["frame"] for v in report["range"]["violations"]]
    assert 3 in offending


def _run_ffmpeg_input(args: list[str], data: bytes) -> None:
    subprocess.run(
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", *args],
        check=True,
        capture_output=True,
        input=data,
    )


def _abused_delivery(tmp_path: Path, name: str, vf: str, *, output_range: str = "tv") -> Path:
    """Build deliberately wrong YUV samples through explicit swscale abuse."""
    destination = tmp_path / f"{name}.mp4"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x48:rate=25:duration=0.2",
            "-vf",
            vf,
            "-frames:v",
            "5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            output_range,
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            str(destination),
        ]
    )
    return destination


@pytest.mark.parametrize(
    ("name", "vf"),
    [
        (
            "full-as-limited",
            "scale=in_range=pc:out_range=pc:in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p",
        ),
        (
            "limited-as-full",
            "scale=in_range=pc:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,"
            "scale=in_range=tv:out_range=pc:in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p",
        ),
        (
            "double-squeeze",
            "scale=in_range=pc:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,"
            "scale=in_range=pc:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,"
            "lut=y='if(lt(val,128),0,255)':u=128:v=128,format=yuv420p",
        ),
        (
            "double-expand",
            "scale=in_range=pc:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,"
            "scale=in_range=tv:out_range=pc:in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p",
        ),
        (
            "legal-overshoot",
            "scale=in_range=pc:out_range=pc:in_color_matrix=bt709:out_color_matrix=bt709,"
            "lut=y='min(255,val+32)':u=128:v=128,format=yuv420p",
        ),
    ],
)
def test_range_abuse_fixtures_fail_with_a_named_plane(
    tmp_path: Path, name: str, vf: str
) -> None:
    delivery = _abused_delivery(tmp_path, name, vf)

    result = verify_delivery(delivery, H264_PROFILE, load_gates(GATES), None, None)

    report = json.loads((tmp_path / "report.json").read_text())
    assert result.state == "FAIL"
    assert report["range"]["valid"] is False
    assert report["range"]["violations"]
    assert report["range"]["violations"][0]["plane"] in {"Y", "Cb", "Cr"}
    assert name in delivery.name


def test_correct_pixels_wrong_tags_fails_metadata(tmp_path: Path) -> None:
    _, delivery, _, _ = _clean_delivery(tmp_path)
    wrongly_tagged = tmp_path / "wrong-tags.mp4"
    _run_ffmpeg(
        [
            "-i",
            str(delivery),
            "-map",
            "0",
            "-c",
            "copy",
            "-bsf:v",
            "h264_metadata=video_full_range_flag=1",
            "-color_range",
            "pc",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            str(wrongly_tagged),
        ]
    )

    result = verify_delivery(wrongly_tagged, H264_PROFILE, load_gates(GATES), None, None)

    report = json.loads((tmp_path / "report.json").read_text())
    assert result.state == "FAIL"
    assert report["metadata"]["valid"] is False
    assert report["metadata"]["mismatches"][0]["field"] == "color_range"


def test_clean_grade_passes_with_frozen_masks_and_writes_schema(tmp_path: Path) -> None:
    source, delivery, cuts, frozen = _clean_delivery(tmp_path)

    result = verify_delivery(
        delivery,
        H264_PROFILE,
        load_gates(GATES),
        frozen,
        cuts,
        source_reference=source,
        source_params=P709_FULL,
    )

    report = json.loads((delivery.parent / "report.json").read_text())
    assert result.state == "PASS"
    assert {"run", "gates", "metadata", "range", "clipping", "measurements"} <= set(report)
    assert report["run"]["state"] == "PASS"
    assert all({"id", "status", "numbers"} <= set(gate) for gate in report["gates"])
    assert report["metadata"]["valid"] is True
    assert report["range"]["valid"] is True
    assert (delivery.parent / "report.md").is_file()


def test_required_whites_are_indeterminate_without_frozen_masks(tmp_path: Path) -> None:
    _, delivery, cuts, _ = _clean_delivery(tmp_path)

    result = verify_delivery(delivery, H264_PROFILE, load_gates(GATES), None, cuts)

    assert result.state == "INDETERMINATE"
    skipped = next(
        outcome
        for outcome in result.gates
        if outcome.gate_id == "whites_rb_balance"
        and outcome.status == "SKIPPED_ABSENT_EVIDENCE"
    )
    assert skipped.reason == "absent evidence: whites.r_minus_b"
    report = json.loads((delivery.parent / "report.json").read_text())
    gate = next(gate for gate in report["gates"] if gate["id"] == skipped.gate_id)
    assert gate["reason"] == skipped.reason


@pytest.mark.parametrize(
    ("name", "source", "delivery", "expected_percent", "source_clipped"),
    [
        (
            "introduced",
            np.array([[[0.50, 0.50, 0.50]]]),
            np.array([[[0.00, 0.50, 1.00]]]),
            200.0 / 3.0,
            0,
        ),
        (
            "baked-in",
            np.array([[[0.00, 0.50, 1.00]]]),
            np.array([[[0.00, 0.50, 1.00]]]),
            0.0,
            2,
        ),
        (
            "clean",
            np.array([[[0.25, 0.50, 0.75]]]),
            np.array([[[0.25, 0.50, 0.75]]]),
            0.0,
            0,
        ),
    ],
)
def test_introduced_clipping_is_source_relative_at_both_ends(
    name: str,
    source: np.ndarray,
    delivery: np.ndarray,
    expected_percent: float,
    source_clipped: int,
) -> None:
    statistics = _introduced_clipping_statistics([source], [delivery])

    assert statistics["introduced_clipping_percent"] == pytest.approx(
        expected_percent
    ), name
    assert statistics["source_clipped_samples"] == source_clipped


def test_wrong_codec_fails_the_delivery_profile(tmp_path: Path):
    # The profile names libx264, so an FFV1 stream is not that delivery even
    # inside an accepted container with correct tags. pix_fmt coverage does not
    # imply codec coverage: disabling codec enforcement leaves the rest of the
    # suite green, so this case needs its own test.
    delivery = tmp_path / "ffv1.mkv"
    _run_ffmpeg([
        "-f", "lavfi", "-i", "color=c=gray:size=64x48:rate=25:duration=0.2",
        "-frames:v", "5", "-c:v", "ffv1", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        str(delivery),
    ])
    result = verify_delivery(delivery, H264_PROFILE, load_gates(GATES), None, None)
    report = json.loads((tmp_path / "report.json").read_text())
    assert result.state == "FAIL"
    assert report["metadata"]["valid"] is False
    fields = {m["field"] for m in report["metadata"]["mismatches"]}
    assert "codec" in fields


def test_wrong_container_fails_the_delivery_profile(tmp_path: Path):
    # Same reasoning for the container family: an H.264 stream with correct
    # pixel format and tags, muxed into Matroska, is not an mp4 delivery.
    delivery = tmp_path / "h264.mkv"
    _run_ffmpeg([
        "-f", "lavfi", "-i", "color=c=gray:size=64x48:rate=25:duration=0.2",
        "-frames:v", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        str(delivery),
    ])
    result = verify_delivery(delivery, H264_PROFILE, load_gates(GATES), None, None)
    report = json.loads((tmp_path / "report.json").read_text())
    assert result.state == "FAIL"
    assert report["metadata"]["valid"] is False
    fields = {m["field"] for m in report["metadata"]["mismatches"]}
    assert "container" in fields


def _vfr_clip(tmp_path: Path, name: str, vf_extra: str = "") -> Path:
    """Five stored frames at irregular PTS (0, .04, .16, .36, .64 seconds)."""
    path = tmp_path / name
    select = "select='eq(n,0)+eq(n,1)+eq(n,4)+eq(n,9)+eq(n,16)'"
    vf = select + (("," + vf_extra) if vf_extra else "")
    # Structured, not a flat field: the clipping path authenticates its source
    # reference by spatial rank correspondence, and a flat raster carries none.
    _run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=25:duration=1",
        "-vf", vf, "-fps_mode", "passthrough",
        "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        str(path),
    ])
    return path


def test_vfr_delivery_is_measured_once_per_stored_frame(tmp_path: Path):
    """A variable-rate delivery must not be re-timed into duplicated frames.

    LIMITS.md states that qc runs on VFR input. Without passthrough timing the
    decode pipe pads a 5-frame file to a constant rate: measured 22 emitted
    frames on ffmpeg 8.1.2. That inflates frames_scanned and weights long
    frames repeatedly in the clipping percentage, which can move the result
    across the 0.5 percent gate in either direction.
    """
    delivery = _vfr_clip(tmp_path, "vfr.mp4")
    stored = int(subprocess.run(
        [str(resolve_tool("ffprobe")), "-v", "error", "-select_streams", "v:0",
         "-count_frames", "-show_entries", "stream=nb_read_frames",
         "-of", "csv=p=0", str(delivery)],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    assert stored == 5

    verify_delivery(delivery, H264_PROFILE, load_gates(GATES), None, None)
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["range"]["coverage"] == "exhaustive"
    assert report["range"]["frames_scanned"] == stored


def test_vfr_clipping_counts_each_stored_frame_once(tmp_path: Path):
    """The clipping denominator must be stored frames, not re-timed frames."""
    source = _vfr_clip(tmp_path, "vfr-source.mp4")
    delivery = _vfr_clip(tmp_path, "vfr-delivery.mp4", vf_extra="eq=brightness=0.2")
    verify_delivery(
        delivery,
        H264_PROFILE,
        load_gates(GATES),
        None,
        None,
        source_reference=source,
        source_params=ConvertParams(
            range="limited", matrix="bt709", transfer="bt709", primaries="bt709"
        ),
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["clipping"]["available"] is True
    assert report["clipping"]["frames_compared"] == 5
    assert report["clipping"]["sample_count"] == 5 * 64 * 48 * 3


def test_severe_but_recoverable_grades_still_authenticate(tmp_path: Path):
    """The authentication must not blind the tool to the defect it measures.

    Measured 2026-07-23 on encoded 160x96 testsrc2 through eq brightness lifts:
    +0.10 correlates 0.9966, +0.25 correlates 0.9800, +0.40 correlates 0.9210,
    +0.55 correlates 0.7953. All four authenticate above the 0.60 threshold and
    report real introduced clipping of 24.0 to 33.4 percent. Beyond that the
    raster is clipped past the point of carrying rank structure (+0.70
    correlates 0.3214), and the honest answer becomes INDETERMINATE rather than
    a number derived from an unverifiable reference.
    """
    source = tmp_path / "src.mp4"
    _run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=160x96:rate=25:duration=0.4",
        "-frames:v", "10", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709", str(source),
    ])
    delivery = tmp_path / "graded.mp4"
    _run_ffmpeg([
        "-i", str(source), "-vf", "eq=brightness=0.55", "-frames:v", "10",
        "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709", str(delivery),
    ])
    verify_delivery(
        delivery,
        H264_PROFILE,
        load_gates(GATES),
        None,
        None,
        source_reference=source,
        source_params=ConvertParams(
            range="limited", matrix="bt709", transfer="bt709", primaries="bt709"
        ),
    )
    report = json.loads((tmp_path / "report.json").read_text())
    clipping = report["clipping"]
    assert clipping["authentication"]["correlation"] > 0.60
    assert clipping["available"] is True
    assert clipping["introduced_clipping_percent"] > 20.0
    outcomes = {g["id"]: g["outcome"] for g in report["gates"]}
    assert outcomes["introduced_clipping"] == "FAIL"


def _structured_pair(tmp_path: Path) -> tuple[Path, Path]:
    """A structured source and a genuinely clipping grade of it."""
    source = tmp_path / "ident-src.mp4"
    _run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=25:duration=0.32",
        "-frames:v", "8", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709", str(source),
    ])
    delivery = tmp_path / "ident-delivery.mp4"
    _run_ffmpeg([
        "-i", str(source), "-vf", "eq=contrast=3.2:brightness=0.42", "-frames:v", "8",
        "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709", str(delivery),
    ])
    return source, delivery


def _clipping_error(delivery: Path, reference: Path) -> str:
    """Run the clipping path and return the terminal error text."""
    result = verify_delivery(
        delivery,
        H264_PROFILE,
        load_gates(GATES),
        None,
        None,
        source_reference=reference,
        source_params=ConvertParams(
            range="limited", matrix="bt709", transfer="bt709", primaries="bt709"
        ),
    )
    assert result.state == "ERROR"
    return result.error or ""


def test_a_copy_of_the_delivery_is_refused_as_its_own_source(tmp_path: Path):
    """Path and inode checks cannot see a copy, and rank structure cannot either.

    A byte-for-byte copy has a different path and a different inode, and it
    correlates with the delivery at exactly 1.0, so it passed authentication.
    Measured 2026-07-23 before this check: a delivery carrying 26.146 percent
    introduced clipping against its real source reported 0.0 percent and a
    PASSING hard gate against a copy of itself. Only the sample values separate
    the two, and only across every frame, since a grade may touch only frames
    the authentication sampler skips.
    """
    _, delivery = _structured_pair(tmp_path)
    copy = tmp_path / "copy-of-delivery.mp4"
    copy.write_bytes(delivery.read_bytes())
    assert copy.stat().st_ino != delivery.stat().st_ino
    assert "same pixels as the delivery" in _clipping_error(delivery, copy)


def test_a_remux_of_the_delivery_is_refused_as_its_own_source(tmp_path: Path):
    """A stream copy into another container is still not a pre-grade source."""
    _, delivery = _structured_pair(tmp_path)
    remux = tmp_path / "remux-of-delivery.mkv"
    _run_ffmpeg(["-i", str(delivery), "-c", "copy", str(remux)])
    assert remux.read_bytes() != delivery.read_bytes()
    assert "same pixels as the delivery" in _clipping_error(delivery, remux)


def test_a_genuine_grade_is_not_mistaken_for_an_identical_file(tmp_path: Path):
    """The identity bound must not swallow a real, subtle grade.

    Measured 2026-07-23 on encoded 160x96 testsrc2: the mildest grades tried
    (eq brightness 0.002, contrast 1.01, saturation 1.05) moved sampled luma by
    0.008984, 0.012437, and 0.012899, all above the 1/255 = 0.003922 bound,
    while an identical file measures exactly 0.
    """
    source = tmp_path / "subtle-src.mp4"
    _run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=25:duration=0.32",
        "-frames:v", "8", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709", str(source),
    ])
    delivery = tmp_path / "subtle-delivery.mp4"
    _run_ffmpeg([
        "-i", str(source), "-vf", "eq=brightness=0.002", "-frames:v", "8",
        "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709", str(delivery),
    ])
    verify_delivery(
        delivery,
        H264_PROFILE,
        load_gates(GATES),
        None,
        None,
        source_reference=source,
        source_params=ConvertParams(
            range="limited", matrix="bt709", transfer="bt709", primaries="bt709"
        ),
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["clipping"]["available"] is True
    assert report["clipping"]["max_frame_delta"] > 1.0 / 255.0
