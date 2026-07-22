# SPDX-License-Identifier: MIT
"""CLI regressions for decoded-delivery hard gates and exit states."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from colorist.tools import resolve_tool


FFMPEG = resolve_tool("ffmpeg")
PROFILE = Path("presets/delivery/h264-yt-sdr.yaml")
PRESET = Path("presets/gates/interview.yaml")
WIDTH = 160
HEIGHT = 96


def _write_yuv_delivery(
    path: Path,
    *,
    y_value: int,
    full_range_tag: bool = False,
    frames: int = 5,
) -> Path:
    width, height = 64, 48
    luma_samples = width * height
    chroma_samples = (width // 2) * (height // 2)
    frame = (
        bytes([y_value]) * luma_samples
        + bytes([128]) * chroma_samples
        + bytes([128]) * chroma_samples
    )
    range_tag = "pc" if full_range_tag else "tv"
    fullrange = "on" if full_range_tag else "off"
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-s",
            f"{width}x{height}",
            "-r",
            "25",
            "-i",
            "-",
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-qp",
            "0",
            "-color_range",
            range_tag,
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-x264-params",
            f"fullrange={fullrange}:colormatrix=bt709:colorprim=bt709:transfer=bt709",
            str(path),
        ],
        input=frame * frames,
        check=True,
        capture_output=True,
    )
    return path


def _write_rgb_source(path: Path, value: float, frames: int = 5) -> Path:
    width, height = 64, 48
    rgb = np.full((height, width, 3), value, dtype=np.float64)
    frame = np.rint(rgb * 65535.0).astype("<u2").tobytes()
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb48le",
            "-s",
            f"{width}x{height}",
            "-r",
            "25",
            "-i",
            "-",
            "-frames:v",
            str(frames),
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
            str(path),
        ],
        input=frame * frames,
        check=True,
        capture_output=True,
    )
    return path


def _structured_frames(frames: int = 5) -> np.ndarray:
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH]
    xf = x / (WIDTH - 1)
    yf = y / (HEIGHT - 1)
    result = []
    for frame_index in range(frames):
        base = 0.08 + 0.72 * (0.58 * xf + 0.42 * yf)
        wave = 0.05 * np.sin(2 * np.pi * (2 * xf + frame_index / 7))
        rgb = np.stack(
            (
                base + wave,
                base * 0.95 + 0.03 * yf,
                base * 0.88 + 0.08 * xf,
            ),
            axis=-1,
        )
        rgb = rgb.copy()
        rgb[18:48, 18 + frame_index : 66 + frame_index] *= (0.55, 0.80, 1.10)
        circle = (x - (115 - frame_index)) ** 2 + (y - 62) ** 2 < 20**2
        rgb[circle] *= (1.10, 0.72, 0.52)
        result.append(np.clip(rgb, 0.04, 0.90))
    return np.stack(result)


def _write_structured_source(path: Path, frames: np.ndarray) -> Path:
    payload = np.rint(frames * 65535.0).astype("<u2").tobytes()
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb48le",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            "25",
            "-i",
            "-",
            "-frames:v",
            str(len(frames)),
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
            str(path),
        ],
        input=payload,
        check=True,
        capture_output=True,
    )
    return path


def _write_structured_delivery(path: Path, frames: np.ndarray) -> Path:
    payload = np.rint(frames * 65535.0).astype("<u2").tobytes()
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb48le",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            "25",
            "-i",
            "-",
            "-frames:v",
            str(len(frames)),
            "-vf",
            "scale=in_range=pc:out_range=tv:in_color_matrix=bt709:"
            "out_color_matrix=bt709,format=yuv420p",
            "-c:v",
            "libx264",
            "-qp",
            "0",
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-x264-params",
            "fullrange=off:colormatrix=bt709:colorprim=bt709:transfer=bt709",
            str(path),
        ],
        input=payload,
        check=True,
        capture_output=True,
    )
    return path


def _write_permissive_preset(path: Path) -> Path:
    path.write_text(
        "# SPDX-License-Identifier: MIT\n"
        "workflow: qc\n"
        "required_coverage: []\n"
        "gates:\n"
        "  - id: shadow_floor\n"
        "    class: soft\n"
        "    coverage: shadows\n"
        "    domain: test luma\n"
        "    statistic: p1 luma\n"
        "    operator: less_than_or_equal\n"
        "    threshold: 255.0\n"
        "    evidence_key: shadows.p1\n"
        "    rationale: Authentication test only.\n"
        "    validation_status: test\n"
    )
    return path


def _write_illegal_range_delivery(path: Path) -> Path:
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x48:rate=25:duration=0.2",
            "-vf",
            "scale=in_range=pc:out_range=pc:in_color_matrix=bt709:"
            "out_color_matrix=bt709,format=yuv420p",
            "-frames:v",
            "5",
            "-c:v",
            "libx264",
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-x264-params",
            "fullrange=off:colormatrix=bt709:colorprim=bt709:transfer=bt709",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _run_qc(
    delivery: Path,
    report_dir: Path,
    source: Path | None = None,
    preset: Path = PRESET,
):
    command = [
        sys.executable,
        "-m",
        "colorist",
        "qc",
        str(delivery),
        "--deliver",
        str(PROFILE),
        "--preset",
        str(preset),
        "--out",
        str(report_dir),
    ]
    if source is not None:
        command.extend(["--source-reference", str(source)])
    completed = subprocess.run(
        command,
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )
    return completed, json.loads((report_dir / "report.json").read_text())


def _gate(report: dict, gate_id: str) -> dict:
    return next(gate for gate in report["gates"] if gate["id"] == gate_id)


def test_qc_cli_illegal_sample_range_cannot_return_pass(tmp_path: Path) -> None:
    delivery = _write_illegal_range_delivery(tmp_path / "illegal-range.mp4")

    completed, report = _run_qc(delivery, tmp_path / "reports")

    assert completed.returncode == 2
    assert completed.stdout.strip() == "FAIL"
    assert report["run"]["state"] == "FAIL"
    assert report["range"]["valid"] is False
    assert report["range"]["violations"][0]["plane"] == "Y"
    assert _gate(report, "delivery_range_extrema")["outcome"] == "FAIL"


def test_qc_cli_wrong_color_tags_cannot_return_pass(tmp_path: Path) -> None:
    delivery = _write_yuv_delivery(
        tmp_path / "wrong-tags.mp4", y_value=100, full_range_tag=True
    )

    completed, report = _run_qc(delivery, tmp_path / "reports")

    assert completed.returncode == 2
    assert completed.stdout.strip() == "FAIL"
    assert report["run"]["state"] == "FAIL"
    assert report["metadata"]["valid"] is False
    assert report["metadata"]["mismatches"][0]["field"] == "color_range"
    assert _gate(report, "delivery_tags_match")["outcome"] == "FAIL"


def test_qc_cli_grade_introduced_clipping_cannot_return_pass(tmp_path: Path) -> None:
    frames = _structured_frames()
    source = _write_structured_source(tmp_path / "source.mkv", frames)
    clipped = frames.copy()
    clipped[..., 0] = 1.0
    clipped[..., 1] = 1.0
    delivery = _write_structured_delivery(tmp_path / "clipped.mp4", clipped)
    preset = _write_permissive_preset(tmp_path / "permissive.yaml")

    completed, report = _run_qc(
        delivery, tmp_path / "reports", source, preset
    )

    assert completed.returncode == 2
    assert completed.stdout.strip() == "FAIL"
    assert report["run"]["state"] == "FAIL"
    authentication = report["clipping"]["authentication"]
    assert authentication["correlation"] >= authentication["threshold"]
    assert authentication["evidence_frames"] == 3
    assert authentication["degenerate_frames"] == 0
    # Assert the BEHAVIOUR, not one build's pixel count. The exact number of
    # clipped samples depends on the encoder: this fixture measured 146800 on
    # homebrew ffmpeg 8.1.2 and 143015 on the pinned BtbN 8.1.2 Linux build, a
    # 2.6 percent spread that says nothing about whether the gate works.
    clipping = report["clipping"]
    assert clipping["available"] is True
    assert clipping["introduced_clipped_samples"] > 0
    assert clipping["introduced_clipping_percent"] > 10.0
    outcomes = {gate["id"]: gate["outcome"] for gate in report["gates"]}
    assert outcomes["introduced_clipping"] == "FAIL"
    assert report["clipping"]["sample_count"] == 230400
    assert report["clipping"]["introduced_clipping_percent"] == pytest.approx(
        63.71527777777778
    )
    assert _gate(report, "introduced_clipping")["outcome"] == "FAIL"


@pytest.mark.parametrize("reference_kind", ["path", "symlink", "hardlink"])
def test_qc_cli_rejects_delivery_as_its_source_reference(
    tmp_path: Path, reference_kind: str
) -> None:
    frames = _structured_frames()
    delivery = _write_structured_delivery(tmp_path / "delivery.mp4", frames)
    reference = delivery
    if reference_kind == "symlink":
        reference = tmp_path / "delivery-link.mp4"
        reference.symlink_to(delivery)
    elif reference_kind == "hardlink":
        reference = tmp_path / "delivery-hardlink.mp4"
        reference.hardlink_to(delivery)

    completed, report = _run_qc(
        delivery,
        tmp_path / f"reports-{reference_kind}",
        reference,
        _write_permissive_preset(tmp_path / f"{reference_kind}.yaml"),
    )

    assert completed.returncode == 4
    assert completed.stdout.strip() == "ERROR"
    assert report["run"]["state"] == "ERROR"
    assert "source reference is the delivery itself" in report["run"]["error"]
    assert "distinct pre-grade source" in completed.stderr


def test_qc_cli_unrelated_reference_is_indeterminate(tmp_path: Path) -> None:
    frames = _structured_frames()
    delivery = _write_structured_delivery(tmp_path / "delivery.mp4", frames)
    unrelated = _write_structured_source(
        tmp_path / "unrelated.mkv", np.flip(frames, axis=2)
    )

    completed, report = _run_qc(
        delivery,
        tmp_path / "reports",
        unrelated,
        _write_permissive_preset(tmp_path / "permissive.yaml"),
    )

    assert completed.returncode == 3
    assert completed.stdout.strip() == "INDETERMINATE"
    assert report["run"]["state"] == "INDETERMINATE"
    authentication = report["clipping"]["authentication"]
    assert authentication["evidence_frames"] == 3
    assert authentication["correlation"] < authentication["threshold"]
    assert report["clipping"]["available"] is False
    assert "authentication failed" in report["clipping"]["reason"]
    assert (
        _gate(report, "introduced_clipping")["outcome"]
        == "INDETERMINATE_ABSENT_EVIDENCE"
    )


def test_qc_cli_flat_reference_evidence_is_indeterminate(tmp_path: Path) -> None:
    source = _write_rgb_source(tmp_path / "flat-source.mkv", 0.5)
    delivery = _write_yuv_delivery(tmp_path / "flat-delivery.mp4", y_value=100)

    completed, report = _run_qc(
        delivery,
        tmp_path / "reports",
        source,
        _write_permissive_preset(tmp_path / "permissive.yaml"),
    )

    assert completed.returncode == 3
    assert report["run"]["state"] == "INDETERMINATE"
    authentication = report["clipping"]["authentication"]
    assert authentication["evidence_frames"] == 0
    assert authentication["degenerate_frames"] == 3
    assert "no usable evidence" in report["clipping"]["reason"]
    assert "near-zero luma variance" in report["clipping"]["reason"]


def test_qc_cli_mild_grade_authenticates_with_low_clipping(tmp_path: Path) -> None:
    frames = _structured_frames()
    source = _write_structured_source(tmp_path / "source.mkv", frames)
    mild = np.clip(np.power(frames, 0.96) * (1.02, 0.99, 1.01), 0.0, 1.0)
    delivery = _write_structured_delivery(tmp_path / "mild.mp4", mild)

    completed, report = _run_qc(
        delivery,
        tmp_path / "reports",
        source,
        _write_permissive_preset(tmp_path / "permissive.yaml"),
    )

    assert completed.returncode == 0
    assert report["run"]["state"] == "PASS"
    authentication = report["clipping"]["authentication"]
    assert authentication["correlation"] >= authentication["threshold"]
    assert authentication["evidence_frames"] == 3
    assert authentication["degenerate_frames"] == 0
    # "Low", not exactly zero. This delivery is a lossily encoded mild grade
    # whose red channel is lifted 2 percent, so whether any near-white sample
    # tips over the clip threshold is a property of the encoder's rounding, not
    # of the behaviour under test. The gate threshold is 0.5 percent; asserting
    # an order of magnitude under it still fails loudly on a real regression.
    assert report["clipping"]["introduced_clipping_percent"] < 0.05
    assert _gate(report, "introduced_clipping")["outcome"] == "PASS"


def test_qc_cli_missing_hard_gate_evidence_is_indeterminate(tmp_path: Path) -> None:
    delivery = _write_yuv_delivery(tmp_path / "clean.mp4", y_value=100)

    completed, report = _run_qc(delivery, tmp_path / "reports")

    assert completed.returncode == 3
    assert completed.stdout.strip() == "INDETERMINATE"
    assert report["run"]["state"] == "INDETERMINATE"
    assert report["clipping"]["available"] is False
    assert (
        _gate(report, "introduced_clipping")["outcome"]
        == "INDETERMINATE_ABSENT_EVIDENCE"
    )
