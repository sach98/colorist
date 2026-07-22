# SPDX-License-Identifier: MIT
"""End-to-end smoke test on the bundled self-authored CC0 clip.

The clip is a small multi-scene torture fixture (tools/make_test_clip.py): a
neutral grey scene, several coloured scenes, and an SMPTE bars scene whose
below-legal pluge (Y = 14) is a genuine delivery-range violation. The pipeline
must run end to end and reach the exact honest states asserted below, not just
any state; a mutation that made a workflow return an unconditional PASS would
fail these assertions.
"""
from pathlib import Path
import shutil

from colorist.cuts import propose_cuts
from colorist.workflow import run_consistency, run_qc

CLIP = Path(__file__).parent / "assets" / "smoke_scenes.mp4"
INTERVIEW = Path(__file__).parents[1] / "presets" / "gates" / "interview.yaml"
H264 = Path(__file__).parents[1] / "presets" / "delivery" / "h264-yt-sdr.yaml"


def _outcome(result, gate_id: str):
    return next(outcome for outcome in result.gates if outcome.gate_id == gate_id)


def test_clip_present_and_attributed_cc0():
    assert CLIP.exists()
    sidecar = CLIP.with_name(CLIP.name + ".license")
    assert "SPDX-License-Identifier: CC0-1.0" in sidecar.read_text()
    attribution = (CLIP.parent / "ATTRIBUTION.md").read_text()
    assert "Self-authored" in attribution
    assert "CC0" in attribution


def test_scene_detection_finds_the_six_scene_cuts():
    cuts = [cut.frame for cut in propose_cuts(CLIP)]
    # Six 15-frame scenes: cuts fall on the scene boundaries.
    assert cuts == [15, 30, 45, 60, 75]


def test_qc_fails_on_the_illegal_bars_scene(tmp_path: Path):
    result = run_qc(CLIP, INTERVIEW, H264, report_dir=tmp_path / "qc-run")
    # The bars scene's below-legal pluge trips the hard range gate; whole-clip
    # qc cannot vacuously pass.
    assert result.state == "FAIL"
    assert _outcome(result, "delivery_range_extrema").status == "FAIL"


def test_consistency_runs_end_to_end_and_writes_a_report(tmp_path: Path):
    source = tmp_path / CLIP.name
    shutil.copyfile(CLIP, source)
    csv = tmp_path / "cuts.csv"
    csv.write_text(
        "start_frame,end_frame\n0,15\n15,30\n30,45\n45,60\n60,75\n75,90\n"
    )

    result = run_consistency(
        source,
        csv,
        INTERVIEW,
        H264,
        tmp_path / "work",
        report_dir=tmp_path / "rep",
        max_iterations=1,
    )

    # A multi-scene torture clip with an illegal bars scene does not pass, but it
    # terminates honestly rather than crashing.
    assert result.state in {"FAIL", "INDETERMINATE"}
    assert (tmp_path / "rep" / "report.json").is_file()
