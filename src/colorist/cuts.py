# SPDX-License-Identifier: MIT
"""Authoritative frame cut lists and PTS-exact scene-cut proposals."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
import re
import subprocess

from colorist.tools import resolve_tool


FFMPEG = resolve_tool("ffmpeg")
FFPROBE = resolve_tool("ffprobe")


@dataclass(frozen=True)
class Shot:
    """One authoritative frame interval with an inclusive start and exclusive end."""

    start_frame: int
    end_frame: int


@dataclass(frozen=True)
class ProposedCut:
    """One unconfirmed scene-detection boundary in frame and PTS coordinates."""

    frame: int
    score: float
    pts_time: float


class CutListValidationError(ValueError):
    """Base error for an invalid authoritative cut list."""


class InvalidCutListHeaderError(CutListValidationError):
    """Raised when a cut-list CSV lacks the required columns."""


class InvalidShotRangeError(CutListValidationError):
    """Raised when a frame range is empty, negative, or non-numeric."""


class OverlappingCutListError(CutListValidationError):
    """Raised when one authoritative shot begins before the prior shot ends."""


class GappedCutListError(CutListValidationError):
    """Raised when authoritative frame ranges are not contiguous from frame zero."""


_PROPOSAL_FIELDS = (
    "start_frame",
    "end_frame",
    "boundary_score",
    "boundary_pts_time",
)


def read_cutlist(path: Path) -> list[Shot]:
    """Read a contiguous ``start_frame,end_frame`` CSV cut list.

    Intervals use an inclusive start and exclusive end.  The CSV is the
    authoritative stream partition, so it must begin at frame zero and every
    following interval must begin exactly where its predecessor ends.  The
    final exclusive end is the represented stream length.
    """
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or set(reader.fieldnames) != {
            "start_frame",
            "end_frame",
        }:
            raise InvalidCutListHeaderError(
                "cut list must have exactly start_frame,end_frame columns"
            )

        shots: list[Shot] = []
        for line_number, row in enumerate(reader, start=2):
            try:
                start = int(row["start_frame"] or "")
                end = int(row["end_frame"] or "")
            except ValueError as error:
                raise InvalidShotRangeError(
                    f"line {line_number} has non-integer frame bounds"
                ) from error
            if start < 0 or end <= start:
                raise InvalidShotRangeError(
                    f"line {line_number} has invalid range [{start}, {end})"
                )

            if not shots:
                if start != 0:
                    raise GappedCutListError(
                        f"gap before first range: expected start 0, found {start}"
                    )
            else:
                prior_end = shots[-1].end_frame
                if start < prior_end:
                    raise OverlappingCutListError(
                        f"overlap at line {line_number}: start {start} precedes {prior_end}"
                    )
                if start > prior_end:
                    raise GappedCutListError(
                        f"gap at line {line_number}: expected {prior_end}, found {start}"
                    )
            shots.append(Shot(start_frame=start, end_frame=end))

    if not shots:
        raise CutListValidationError("cut list has no shot ranges")
    return shots


def frames_to_pts(src: Path) -> list[float]:
    """Return decoded-frame PTS values from ffprobe, never a nominal FPS mapping."""
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time,pkt_pts_time",
            "-of",
            "json",
            str(Path(src)),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    pts: list[float] = []
    for frame_index, frame in enumerate(data.get("frames", [])):
        timestamp = frame.get("best_effort_timestamp_time", frame.get("pkt_pts_time"))
        if timestamp in (None, "N/A"):
            raise ValueError(f"frame {frame_index} has no usable PTS timestamp")
        pts.append(float(timestamp))
    if not pts:
        raise ValueError(f"video stream has no frames: {src}")
    return pts


_SCDET_EVENT = re.compile(
    r"lavfi\.scd\.score:\s*(?P<score>[0-9]+(?:\.[0-9]+)?),\s*"
    r"lavfi\.scd\.time:\s*(?P<time>-?[0-9]+(?:\.[0-9]+)?)"
)


def propose_cuts(
    src: Path, threshold: float = 10.0, min_shot: int = 12
) -> list[ProposedCut]:
    """Run ``scdet`` and map detected boundaries back to actual frame PTS values.

    Candidates closer than ``min_shot`` frames are merged by retaining the
    highest-scoring member.  The return values are proposals only: callers must
    still persist a reviewed ``read_cutlist`` CSV before rendering.
    """
    if threshold < 0:
        raise ValueError("threshold must be non-negative")
    if min_shot < 1:
        raise ValueError("min_shot must be at least one frame")

    src = Path(src)
    result = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(src),
            "-vf",
            f"scdet=threshold={threshold}",
            "-an",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    pts = frames_to_pts(src)
    candidates: list[ProposedCut] = []
    for match in _SCDET_EVENT.finditer(result.stderr):
        score = float(match.group("score"))
        reported_time = float(match.group("time"))
        frame = min(range(len(pts)), key=lambda index: abs(pts[index] - reported_time))
        candidates.append(ProposedCut(frame=frame, score=score, pts_time=pts[frame]))

    merged: list[ProposedCut] = []
    for candidate in sorted(candidates, key=lambda cut: cut.frame):
        if not merged or candidate.frame - merged[-1].frame >= min_shot:
            merged.append(candidate)
        elif candidate.score > merged[-1].score:
            merged[-1] = candidate
    return merged


def write_cut_proposal(
    src: Path,
    destination: Path,
    threshold: float = 10.0,
    min_shot: int = 12,
) -> Path:
    """Write a complete, non-authoritative shot partition with cut scores."""
    output = Path(destination)
    if output.exists():
        raise FileExistsError(f"cut proposal exists; refusing to overwrite: {output}")
    frame_count = len(frames_to_pts(Path(src)))
    cuts = [
        cut
        for cut in propose_cuts(Path(src), threshold=threshold, min_shot=min_shot)
        if 0 < cut.frame < frame_count
    ]
    cuts_by_frame = {cut.frame: cut for cut in cuts}
    bounds = [0, *sorted(cuts_by_frame), frame_count]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_PROPOSAL_FIELDS)
        writer.writeheader()
        for start, end in zip(bounds, bounds[1:]):
            boundary = cuts_by_frame.get(end)
            writer.writerow(
                {
                    "start_frame": start,
                    "end_frame": end,
                    "boundary_score": "" if boundary is None else boundary.score,
                    "boundary_pts_time": "" if boundary is None else boundary.pts_time,
                }
            )
    return output


def confirm_cut_proposal(proposal: Path, destination: Path) -> Path:
    """Confirm a reviewed proposal by writing the strict authoritative CSV."""
    output = Path(destination)
    if output.exists():
        raise FileExistsError(f"cut list exists; refusing to overwrite: {output}")
    with Path(proposal).open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(_PROPOSAL_FIELDS):
            raise InvalidCutListHeaderError(
                "cut proposal must have exactly " + ",".join(_PROPOSAL_FIELDS)
            )
        shots: list[Shot] = []
        for line_number, row in enumerate(reader, start=2):
            try:
                start = int(row["start_frame"] or "")
                end = int(row["end_frame"] or "")
            except ValueError as error:
                raise InvalidShotRangeError(
                    f"line {line_number} has non-integer frame bounds"
                ) from error
            if start < 0 or end <= start:
                raise InvalidShotRangeError(
                    f"line {line_number} has invalid range [{start}, {end})"
                )
            expected = 0 if not shots else shots[-1].end_frame
            if start < expected:
                raise OverlappingCutListError(
                    f"overlap at line {line_number}: start {start} precedes {expected}"
                )
            if start > expected:
                raise GappedCutListError(
                    f"gap at line {line_number}: expected {expected}, found {start}"
                )
            shots.append(Shot(start, end))
    if not shots:
        raise CutListValidationError("cut proposal has no shot ranges")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("start_frame", "end_frame"))
        writer.writerows((shot.start_frame, shot.end_frame) for shot in shots)
    return output
