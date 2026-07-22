# SPDX-License-Identifier: MIT
"""End-to-end coverage for the source-based consistency and QC workflows."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

import colorist.__main__ as cli
from colorist.__main__ import _parser
from colorist.corrections import Correction, bt1886_encode, solve_wb
from colorist.gates import GateOutcome, RunResult
from colorist.tools import resolve_tool
from colorist.workflow import _adjust_implicated_targets, run_consistency, run_qc
from tests.conftest import build_slog3_casted_three_shot_fixture


H264_PROFILE = Path("presets/delivery/h264-yt-sdr.yaml")
INTERVIEW = Path("presets/gates/interview.yaml")
FFMPEG = resolve_tool("ffmpeg")
CASTS = (
    (0.82, 0.94, 1.18),
    (0.88, 1.13, 1.06),
    (1.08, 0.84, 1.25),
)


def _write_cutlist(path: Path, *, frames_per_shot: int = 10) -> Path:
    path.write_text(
        "start_frame,end_frame\n"
        f"0,{frames_per_shot}\n"
        f"{frames_per_shot},{frames_per_shot * 2}\n"
        f"{frames_per_shot * 2},{frames_per_shot * 3}\n"
    )
    return path


def _slog3_fixture(tmp_path: Path) -> tuple[Path, Path]:
    source = build_slog3_casted_three_shot_fixture(
        tmp_path, casts=CASTS, structured=True
    )
    return source, _write_cutlist(tmp_path / "cuts.csv")


def _limited_delivery(tmp_path: Path) -> Path:
    delivery = tmp_path / "delivery.mp4"
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:size=64x48:rate=25:duration=0.2",
            "-vf",
            "scale=in_range=pc:out_range=tv:in_color_matrix=bt709:"
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
            str(delivery),
        ],
        check=True,
        capture_output=True,
    )
    return delivery


def _structured_qc_pair(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "pre-grade.mkv"
    delivery = tmp_path / "structured-delivery.mp4"
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
            "-frames:v",
            "5",
            "-vf",
            "eq=saturation=0.2:contrast=0.65:brightness=0.05,format=gbrp16le",
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
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(source),
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
            str(delivery),
        ],
        check=True,
        capture_output=True,
    )
    return source, delivery


def _outcome(result: RunResult, gate_id: str):
    return next(outcome for outcome in result.gates if outcome.gate_id == gate_id)


def test_consistency_cli_accepts_and_threads_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = [
        "consistency",
        "input.mp4",
        "--cuts",
        "cuts.csv",
        "--deliver",
        "h264-yt-sdr",
        "--encoding",
        "slog3_sgamut3cine",
        "--preset",
        "interview",
        "--out",
        "run",
        "--approve-short-shots",
    ]
    assert _parser().parse_args(argv).encoding == "slog3_sgamut3cine"

    invalid = list(argv)
    invalid[invalid.index("slog3_sgamut3cine")] = "not-an-encoding"
    with pytest.raises(SystemExit):
        _parser().parse_args(invalid)

    received: dict[str, object] = {}

    def fake_run_consistency(*args: object, **kwargs: object) -> RunResult:
        received.update(kwargs)
        return RunResult(state="PASS", gates=[])

    monkeypatch.setattr(cli, "run_consistency", fake_run_consistency)

    assert cli.main(argv) == 0
    assert received["curve_gamut"] == "slog3_sgamut3cine"
    assert received["approve_short_shots"] is True


def test_qc_cli_accepts_and_threads_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = [
        "qc",
        "input.mp4",
        "--deliver",
        "h264-yt-sdr",
        "--source-reference",
        "source.mkv",
        "--encoding",
        "logc4_awg4",
        "--input-range",
        "limited",
        "--input-matrix",
        "bt709",
        "--confirm-metadata-override",
        "--preset",
        "interview",
        "--out",
        "run",
    ]
    received: dict[str, object] = {}

    received_args: tuple[object, ...] = ()

    def fake_run_qc(*args: object, **kwargs: object) -> RunResult:
        nonlocal received_args
        received_args = args
        received.update(kwargs)
        return RunResult(state="PASS", gates=[])

    monkeypatch.setattr(cli, "run_qc", fake_run_qc)

    assert cli.main(argv) == 0
    assert received_args[2] == "h264-yt-sdr"
    assert received["source_reference"] == Path("source.mkv")
    assert received["curve_gamut"] == "logc4_awg4"
    assert received["input_params"] == cli.ConvertParams(
        range="limited", matrix="bt709", transfer="bt709", primaries="bt709"
    )
    assert received["confirm_metadata_override"] is True


def test_consistency_neutralizes_slog3_shots_in_one_iteration(tmp_path: Path) -> None:
    source, cuts = _slog3_fixture(tmp_path)
    workdir = tmp_path / "consistency"
    reports = tmp_path / "consistency-reports"

    result = run_consistency(
        source,
        cuts,
        INTERVIEW,
        H264_PROFILE,
        workdir,
        curve_gamut="slog3_sgamut3cine",
        report_dir=reports,
        mask_review=True,
    )

    assert isinstance(result, RunResult)
    assert result.state == "PASS"
    assert result.iteration_count == 1
    assert _outcome(result, "whites_rb_balance").status == "PASS"
    assert _outcome(result, "whites_green_balance").status == "PASS"
    report = json.loads((reports / "report.json").read_text())
    assert report["run"]["state"] == "PASS"
    assert report["run"]["iteration_count"] == 1
    assert (workdir / f"{source.stem}.graded.mp4").is_file()
    assert (reports / "report.md").is_file()
    assert list((reports / "mask-review").glob("*.png"))
    assert report["shots"][0]["neutral"]["regions"]
    assert {"median_rgb", "px", "bbox"} <= set(
        report["shots"][0]["neutral"]["regions"][0]
    )
    assert not (workdir / "report.json").exists()


def test_consistency_preserves_best_candidate_on_impossible_gate(tmp_path: Path) -> None:
    source, cuts = _slog3_fixture(tmp_path)
    impossible = tmp_path / "impossible.yaml"
    impossible.write_text(
        INTERVIEW.read_text().replace("threshold: 205.0", "threshold: 0.0", 1)
    )
    workdir = tmp_path / "failed-consistency"

    result = run_consistency(
        source,
        cuts,
        impossible,
        H264_PROFILE,
        workdir,
        curve_gamut="slog3_sgamut3cine",
        max_iterations=3,
    )

    assert result.state == "FAIL"
    assert result.iteration_count == 3
    report = json.loads((workdir / "report.json").read_text())
    gate = next(
        gate
        for gate in report["gates"]
        if gate["id"] == "highlight_ceiling" and gate["outcome"] == "FAIL"
    )
    assert isinstance(gate["measured"], (int, float))
    assert isinstance(gate["threshold"], (int, float))
    assert gate["domain"] == "full-range Rec.709 luma, 8-bit scale, sampled source frames"
    assert f"measured {float(gate['measured']):+}" in (workdir / "report.md").read_text()
    assert report["best_candidate"]["manifest"] == "best-candidate.json"
    assert (workdir / "best-candidate.json").is_file()
    assert not (workdir / f"{source.stem}.graded.mp4").exists()


def test_two_iteration_white_balance_retry_preserves_measured_neutral_luma(
    tmp_path: Path,
) -> None:
    neutral = np.array([0.3, 0.2, 0.1], dtype=np.float64)
    prior = Correction(wb_gains=solve_wb(neutral))
    first_iteration_neutral = neutral * np.asarray(prior.wb_gains)
    verification_report = tmp_path / "report.json"
    verification_report.write_text(
        json.dumps(
            {
                "measurements": [
                    {
                        "shot": 0,
                        "neutral": {
                            "median_rgb": bt1886_encode(
                                first_iteration_neutral
                            ).tolist()
                        },
                    }
                ]
            }
        )
    )
    failed = RunResult(
        state="FAIL",
        gates=[
            GateOutcome(
                gate_id="whites_rb_balance",
                status="FAIL",
                observed=5.0,
                threshold=4.0,
                domain="test",
                operator="less_than_or_equal",
                numbers={"observed": 5.0, "threshold": 4.0},
            )
        ],
    )

    updated, adjusted = _adjust_implicated_targets(
        {0: prior}, failed, verification_report
    )

    luma_weights = np.array([0.2126, 0.7152, 0.0722])
    assert adjusted == ["shot-0: white_balance"]
    assert float((neutral * np.asarray(updated[0].wb_gains)) @ luma_weights) == pytest.approx(
        float(neutral @ luma_weights), abs=1e-12
    )


def test_out_pointing_at_a_regular_file_is_a_clean_error(tmp_path: Path) -> None:
    """An --out that names an existing regular file must be a clean ERROR / exit

    4, not a raw traceback with exit 1, per the documented exit-code contract.
    """
    delivery = _limited_delivery(tmp_path)
    out_file = tmp_path / "not-a-directory"
    out_file.write_text("x")

    completed = subprocess.run(
        [
            sys.executable, "-m", "colorist", "qc", str(delivery),
            "--deliver", str(H264_PROFILE), "--preset", str(INTERVIEW),
            "--out", str(out_file),
        ],
        cwd=Path(__file__).parents[1], capture_output=True, text=True,
    )
    assert completed.returncode == 4, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "ERROR"


def test_qc_is_terminal_and_never_writes_a_video(tmp_path: Path) -> None:
    delivery = _limited_delivery(tmp_path)

    result = run_qc(
        delivery, INTERVIEW, H264_PROFILE, report_dir=tmp_path / "qc-run"
    )

    assert result.state == "INDETERMINATE"
    clipping = _outcome(result, "introduced_clipping")
    assert clipping.status == "INDETERMINATE_ABSENT_EVIDENCE"
    assert not list(tmp_path.glob("*.graded.*"))
    assert (tmp_path / "qc-run" / "report.json").is_file()


def test_hard_gates_cannot_be_omitted_by_a_custom_preset(tmp_path: Path) -> None:
    """A schema-valid preset with only a soft gate must not bypass the delivery

    hard gates. Without a source reference the mandatory introduced-clipping
    gate is INDETERMINATE, so a legal delivery cannot vacuously PASS.
    """
    delivery = _limited_delivery(tmp_path)
    shadow_only = _shadow_floor_preset(tmp_path / "shadow-only.yaml", 0.0)

    result = run_qc(
        delivery, shadow_only, H264_PROFILE, report_dir=tmp_path / "omit-run"
    )

    assert result.state == "INDETERMINATE"
    gate_ids = {gate.gate_id for gate in result.gates}
    assert {"delivery_tags_match", "delivery_range_extrema", "introduced_clipping"} <= gate_ids
    assert _outcome(result, "delivery_tags_match").status == "PASS"
    assert _outcome(result, "delivery_range_extrema").status == "PASS"
    assert _outcome(result, "introduced_clipping").status == "INDETERMINATE_ABSENT_EVIDENCE"


def test_short_shots_are_measured_indeterminate_and_not_auto_corrected(
    tmp_path: Path,
) -> None:
    source = build_slog3_casted_three_shot_fixture(
        tmp_path, casts=CASTS, frames_per_shot=2
    )
    cuts = _write_cutlist(tmp_path / "short-cuts.csv", frames_per_shot=2)
    reports = tmp_path / "short-run"

    result = run_consistency(
        source,
        cuts,
        INTERVIEW,
        H264_PROFILE,
        tmp_path / "short-work",
        curve_gamut="slog3_sgamut3cine",
        report_dir=reports,
    )

    report = json.loads((reports / "report.json").read_text())
    whites = _outcome(result, "whites_rb_balance")
    assert result.state == "INDETERMINATE"
    assert whites.status == "INDETERMINATE_ABSENT_EVIDENCE"
    assert "fewer than 3 frames" in (whites.reason or "")
    assert all(shot["automatic_correction"] is False for shot in report["shots"])
    assert all(shot["short_shot_approved"] is False for shot in report["shots"])
    assert all(shot["neutral"]["regions"] for shot in report["shots"])
    assert all(shot["working_luma_p50"] > 0 for shot in report["shots"])
    assert not list((tmp_path / "short-work").glob("*.graded.*"))


def test_report_reuse_is_refused_without_overwrite(tmp_path: Path) -> None:
    delivery = _limited_delivery(tmp_path)
    run_dir = tmp_path / "reports"
    first = run_qc(delivery, INTERVIEW, H264_PROFILE, report_dir=run_dir)
    original = (run_dir / "report.json").read_bytes()

    second = run_qc(delivery, INTERVIEW, H264_PROFILE, report_dir=run_dir)

    assert first.state == "INDETERMINATE"
    assert second.state == "ERROR"
    assert "refusing to overwrite" in (second.error or "")
    assert (run_dir / "report.json").read_bytes() == original


def test_provisional_preset_must_be_selected_explicitly() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            ["qc", "input.mp4", "--deliver", "h264-yt-sdr", "--out", "run"]
        )
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "consistency",
                "input.mp4",
                "--cuts",
                "cuts.csv",
                "--out",
                "run",
            ]
        )


def _shadow_floor_preset(path: Path, threshold: float) -> Path:
    path.write_text(
        "workflow: qc\n"
        "required_coverage: []\n"
        "gates:\n"
        "  - id: shadow_floor\n"
        "    class: soft\n"
        "    coverage: shadows\n"
        "    domain: full-range Rec.709 luma, 8-bit scale, sampled source frames\n"
        "    statistic: p1 luma\n"
        "    operator: greater_than_or_equal\n"
        f"    threshold: {threshold}\n"
        "    evidence_key: shadows.p1\n"
        "    rationale: Test only.\n"
        "    validation_status: test\n"
    )
    return path


def _missing_evidence_preset(path: Path) -> Path:
    path.write_text(
        "workflow: qc\n"
        "required_coverage:\n"
        "  - missing\n"
        "gates:\n"
        "  - id: missing_evidence\n"
        "    class: soft\n"
        "    coverage: missing\n"
        "    domain: test evidence\n"
        "    statistic: missing value\n"
        "    operator: less_than_or_equal\n"
        "    threshold: 1.0\n"
        "    evidence_key: absent.value\n"
        "    rationale: Test only.\n"
        "    validation_status: test\n"
    )
    return path


def _invalid_evidence_preset(path: Path) -> Path:
    path.write_text(
        "workflow: qc\n"
        "required_coverage: []\n"
        "gates:\n"
        "  - id: invalid_evidence\n"
        "    class: soft\n"
        "    coverage: shadows\n"
        "    domain: test evidence\n"
        "    statistic: p1 luma\n"
        "    operator: equals\n"
        "    threshold: true\n"
        "    evidence_key: shadows.p1\n"
        "    rationale: Test only.\n"
        "    validation_status: test\n"
    )
    return path


def test_qc_cli_returns_pass_and_fail_exit_codes_and_honors_out(tmp_path: Path) -> None:
    reference, source = _structured_qc_pair(tmp_path)
    local_tools = tmp_path / "local-tools"
    local_tools.mkdir()
    (local_tools / "ffmpeg").symlink_to(resolve_tool("ffmpeg"))
    (local_tools / "ffprobe").symlink_to(resolve_tool("ffprobe"))
    environment = dict(os.environ)
    environment["PATH"] = str(local_tools)

    pass_reports = tmp_path / "pass-reports"
    passed = subprocess.run(
        [
            sys.executable,
            "-m",
            "colorist",
            "qc",
            str(source),
            "--deliver",
            str(H264_PROFILE),
            "--preset",
            str(_shadow_floor_preset(tmp_path / "pass.yaml", 0.0)),
            "--source-reference",
            str(reference),
            "--out",
            str(pass_reports),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert passed.returncode == 0, passed.stderr
    assert (pass_reports / "report.json").is_file()
    assert (pass_reports / "report.md").is_file()
    assert not (tmp_path / "report.json").exists()

    failed = subprocess.run(
        [
            sys.executable,
            "-m",
            "colorist",
            "qc",
            str(source),
            "--deliver",
            str(H264_PROFILE),
            "--preset",
            str(_shadow_floor_preset(tmp_path / "fail.yaml", 256.0)),
            "--out",
            str(tmp_path / "fail-reports"),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert failed.returncode == 2

    indeterminate = subprocess.run(
        [
            sys.executable,
            "-m",
            "colorist",
            "qc",
            str(source),
            "--deliver",
            str(H264_PROFILE),
            "--preset",
            str(_missing_evidence_preset(tmp_path / "indeterminate.yaml")),
            "--out",
            str(tmp_path / "indeterminate-reports"),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert indeterminate.returncode == 3

    errored = subprocess.run(
        [
            sys.executable,
            "-m",
            "colorist",
            "qc",
            str(source),
            "--deliver",
            str(H264_PROFILE),
            "--preset",
            str(_invalid_evidence_preset(tmp_path / "error.yaml")),
            "--out",
            str(tmp_path / "error-reports"),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert errored.returncode == 4
    assert _parser().parse_args(
        [
            "consistency",
            "input.mp4",
            "--cuts",
            "cuts.csv",
            "--deliver",
            "h264-yt-sdr",
            "--preset",
            "interview",
            "--out",
            "reports",
        ]
    ).out == Path("reports")
