# SPDX-License-Identifier: MIT
"""Tests for authoritative cut lists and PTS-exact cut proposals."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

import colorist.__main__ as cli
from colorist.cuts import (
    GappedCutListError,
    OverlappingCutListError,
    Shot,
    frames_to_pts,
    propose_cuts,
    read_cutlist,
)
from tests.conftest import build_three_shot_fixture, build_vfr_fixture


def test_propose_cuts_finds_each_synthetic_shot_boundary(tmp_path: Path) -> None:
    src = build_three_shot_fixture(tmp_path)

    cuts = propose_cuts(src, threshold=10.0, min_shot=5)

    assert [cut.frame for cut in cuts] == [10, 20]
    assert all(cut.score >= 10.0 for cut in cuts)
    assert [cut.pts_time for cut in cuts] == pytest.approx([0.4, 0.8], abs=1e-6)


def test_frames_to_pts_uses_actual_variable_timestamps(tmp_path: Path) -> None:
    src = build_vfr_fixture(tmp_path)

    pts = frames_to_pts(src)

    assert pts == pytest.approx([0.0, 0.04, 0.16, 0.36, 0.64], abs=1e-6)
    assert pts != pytest.approx([frame / 25 for frame in range(5)], abs=1e-6)


def test_cli_writes_scored_proposal_then_requires_explicit_confirmation(
    tmp_path: Path,
) -> None:
    src = build_three_shot_fixture(tmp_path)
    proposal = tmp_path / "proposal.csv"
    cutlist = tmp_path / "cuts.csv"

    assert cli.main(
        [
            "propose-cuts",
            str(src),
            "--out",
            str(proposal),
            "--threshold",
            "10",
            "--min-shot",
            "5",
        ]
    ) == 0
    with proposal.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(int(row["start_frame"]), int(row["end_frame"])) for row in rows] == [
        (0, 10),
        (10, 20),
        (20, 30),
    ]
    assert all(float(row["boundary_score"]) >= 10.0 for row in rows[:-1])
    with pytest.raises(Exception, match="exactly start_frame,end_frame"):
        read_cutlist(proposal)

    assert cli.main(
        ["confirm-cuts", str(proposal), "--out", str(cutlist)]
    ) == 0
    assert read_cutlist(cutlist) == [Shot(0, 10), Shot(10, 20), Shot(20, 30)]


def test_read_cutlist_rejects_overlapping_ranges(tmp_path: Path) -> None:
    cutlist = tmp_path / "overlap.csv"
    cutlist.write_text("start_frame,end_frame\n0,10\n9,20\n")

    with pytest.raises(OverlappingCutListError, match="overlap"):
        read_cutlist(cutlist)


def test_read_cutlist_rejects_gapped_ranges(tmp_path: Path) -> None:
    cutlist = tmp_path / "gap.csv"
    cutlist.write_text("start_frame,end_frame\n0,10\n11,20\n")

    with pytest.raises(GappedCutListError, match="gap"):
        read_cutlist(cutlist)
