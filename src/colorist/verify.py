# SPDX-License-Identifier: MIT
"""Decoded-delivery QC for profile tags, native YUV range, and frozen ROIs.

Verification deliberately observes the encoded delivery, not the render graph
that produced it.  Native YUV is decoded straight to rawvideo without a pixel
format conversion, then inspected in code values.  ROI masks are supplied from
the source measurement pass and staged beside a temporary alias of the
delivery, which lets :func:`measure_shot` load them without ever creating a
new delivery-derived candidate mask.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

import numpy as np

from colorist.corrections import bt1886_encode
from colorist.cuts import Shot, frames_to_pts, read_cutlist
from colorist.gates import (
    GateOutcome,
    GateSet,
    RunResult,
    format_gate_outcome,
    gate_outcome_payload,
    evaluate,
)
from colorist.grade import DeliveryProfile, _load_delivery_profile
from colorist.idt import camera_to_working
from colorist.measure import (
    MaskStat,
    ShotMeasurement,
    _frozen_mask_path,
    _mask_cache_identity,
    _save_frozen_mask,
    measure_shot,
    sample_positions,
)
from colorist.render import ConvertParams, read_frame_rgb
from colorist.tools import resolve_tool


FFMPEG = resolve_tool("ffmpeg")
FFPROBE = resolve_tool("ffprobe")
CLIPPING_CODE_THRESHOLD = 1.0 / 255.0
INTRODUCED_CLIPPING_DOMAIN = (
    "full-range Rec.709 display-code RGB channel samples, every frame's full "
    "raster compared source to delivery; clipped at <= 1/255 or >= 254/255"
)
REFERENCE_AUTHENTICATION_WIDTH = 32
REFERENCE_AUTHENTICATION_HEIGHT = 18
REFERENCE_AUTHENTICATION_MIN_LEVELS = 8
REFERENCE_AUTHENTICATION_MIN_LUMA_STD = 1.0 / 255.0
# With ffmpeg 8.1.2, encoded 160x96 gradients, correlated noise, and synthetic
# edge scenes measured 0.791576 to 0.999984 for genuine identity through
# two-channel clipping grades. Unrelated pairs measured -0.259692 to 0.496651.
# A 0.60 threshold leaves 0.191576 below the worst genuine case while rejecting
# the strongest unrelated pair by 0.103349.
REFERENCE_AUTHENTICATION_THRESHOLD = 0.60
_REC709_LUMA = np.array((0.2126, 0.7152, 0.0722), dtype=np.float64)


@dataclass(frozen=True)
class _YUVLayout:
    """The planar rawvideo layout needed to inspect native code values."""

    pix_fmt: str
    bit_depth: int
    bytes_per_sample: int
    little_endian: bool
    chroma_width: int
    chroma_height: int

    @property
    def frame_bytes(self) -> int:
        return self.bytes_per_sample * (
            self.width * self.height + 2 * self.chroma_width * self.chroma_height
        )

    width: int
    height: int


class VerificationError(RuntimeError):
    """Raised internally for a delivery that cannot be verified honestly."""


def verify_delivery(
    path: Path | str,
    profile: DeliveryProfile | Path | Mapping[str, object],
    gates: GateSet,
    frozen_masks: object,
    cutlist: Path | str | Sequence[Shot] | None,
    *,
    source_reference: Path | str | None = None,
    source_params: ConvertParams | None = None,
    source_curve_gamut: str | None = None,
    report_dir: Path | str | None = None,
    workflow: str | None = None,
) -> RunResult:
    """Verify one delivered file and write ``report.json`` and ``report.md``.

    ``frozen_masks`` is normally a sequence of source ``ShotMeasurement``
    values, one for each cut-list shot.  For orchestration callers, a mapping
    keyed by shot index is also accepted; each value may be a
    ``ShotMeasurement``, ``MaskStat``, a mask path, or a mapping containing
    ``neutral`` and/or ``skin`` values of those types.  Missing supplied masks
    are represented as empty frozen masks, never recomputed on the delivery.

    The returned state includes hard metadata and native sample-range
    invariants even if a caller supplied a gate set without those two gates.
    Operational failures produce an ``ERROR`` result and a best-effort report.
    """
    delivery = Path(path)
    metadata_report: dict[str, Any] = {
        "valid": False,
        "expected": {},
        "observed": {},
        "mismatches": [],
    }
    range_report: dict[str, Any] = {
        "valid": False,
        "declared_range": None,
        "pix_fmt": None,
        "bit_depth": None,
        "bounds": {},
        "frames_scanned": 0,
        "coverage": "exhaustive",
        "extrema": {},
        "violations": [],
    }
    measurement_report: list[dict[str, Any]] = []
    clipping_report: dict[str, Any] = {
        "available": False,
        "domain": INTRODUCED_CLIPPING_DOMAIN,
        "low_threshold": CLIPPING_CODE_THRESHOLD,
        "high_threshold": 1.0 - CLIPPING_CODE_THRESHOLD,
        "coverage": "exhaustive",
        "sample_count": 0,
        "source_clipped_samples": 0,
        "delivery_clipped_samples": 0,
        "introduced_clipped_samples": 0,
        "introduced_clipping_percent": None,
        "authentication": _reference_authentication_base(),
        "reason": "source reference not supplied",
    }

    try:
        output_profile = _as_delivery_profile(profile)
        stream = _probe_video_stream(delivery)
        metadata_report = _verify_metadata(delivery, stream, output_profile)

        frame_count = len(frames_to_pts(delivery))
        shots = _as_shots(cutlist, frame_count)
        shot_frames = _sample_shot_frames(shots, cutlist is None)
        # Hard legality gates inspect every frame; sampling is only for the soft
        # creative ROI statistics below.
        range_report = _verify_native_range(
            delivery, stream, output_profile, frame_count
        )
        clipping_report = _verify_introduced_clipping(
            delivery,
            output_profile,
            frame_count,
            stream,
            None if source_reference is None else Path(source_reference),
            source_params,
            source_curve_gamut,
        )

        measurements = _remeasure_frozen_rois(
            delivery,
            output_profile,
            shots,
            shot_frames,
            frozen_masks,
            stream,
        )
        measurement_report = [
            _measurement_report(index, frames, measurement, output_profile)
            for index, (frames, measurement) in enumerate(zip(shot_frames, measurements))
        ]

        delivery_evidence = _delivery_evidence(
            metadata_report, range_report, clipping_report
        )
        if measurements:
            gate_runs = [
                evaluate(gates, {**delivery_evidence, "measurement": measurement})
                for measurement in measurements
            ]
        else:
            # With no source-frozen ROI artifacts there is no trustworthy
            # measurement evidence at all.  In particular, do not let
            # measure_shot derive fresh neutral candidates from the delivery.
            gate_runs = [evaluate(gates, delivery_evidence)]

        result = _aggregate_gate_runs(gate_runs)
        result = _apply_delivery_invariants(
            result,
            metadata_valid=metadata_report["valid"],
            range_valid=range_report["valid"],
            clipping_report=clipping_report,
        )
    except Exception as error:  # A broken decode must never be called a pass.
        result = RunResult(
            state="ERROR",
            gates=[],
            error=f"{type(error).__name__}: {error}",
        )

    _write_reports(
        delivery,
        result,
        metadata_report,
        range_report,
        clipping_report,
        measurement_report,
        report_dir=report_dir,
        workflow=workflow,
    )
    return result


def _delivery_evidence(
    metadata_report: Mapping[str, Any],
    range_report: Mapping[str, Any],
    clipping_report: Mapping[str, Any],
) -> dict[str, dict[str, float | bool]]:
    """Assemble every delivery gate key produced by decoded verification."""
    delivery: dict[str, float | bool] = {
        "range_extrema_valid": bool(range_report["valid"]),
        "tags_match": bool(metadata_report["valid"]),
    }
    clipping = clipping_report.get("introduced_clipping_percent")
    if clipping_report.get("available") and isinstance(clipping, (int, float)):
        delivery["introduced_clipping_percent"] = float(clipping)
    return {"delivery": delivery}


def _as_delivery_profile(
    profile: DeliveryProfile | Path | Mapping[str, object],
) -> DeliveryProfile:
    if isinstance(profile, DeliveryProfile):
        return profile
    return _load_delivery_profile(profile)


def _probe_video_stream(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,pix_fmt,bits_per_raw_sample,codec_name,color_range,"
            "color_space,color_transfer,color_primaries",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise VerificationError(f"ffprobe failed: {result.stderr[-1000:]}")
    try:
        streams = json.loads(result.stdout)["streams"]
        stream = streams[0]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise VerificationError("ffprobe found no video stream") from error
    if not isinstance(stream, dict):
        raise VerificationError("ffprobe video stream is not an object")
    return stream


#: Map an encoder name in a delivery profile to the codec ffprobe reports.
_ENCODER_TO_CODEC = {
    "libx264": "h264",
    "libx265": "hevc",
    "libx264rgb": "h264",
    "prores_ks": "prores",
    "prores_aw": "prores",
    "ffv1": "ffv1",
}


def _verify_metadata(
    path: Path, stream: Mapping[str, Any], profile: DeliveryProfile
) -> dict[str, Any]:
    expected = {
        "color_range": profile.ffmpeg_range,
        "color_space": profile.colorspace,
        "color_transfer": profile.color_trc,
        "color_primaries": profile.color_primaries,
        # A delivery must also be the codec, pixel format, and container the
        # profile names: a yuv444p file is not a yuv420p delivery, whatever its
        # colour tags say.
        "pix_fmt": profile.pix_fmt,
        "codec": _ENCODER_TO_CODEC.get(profile.vcodec, profile.vcodec),
    }
    observed = {field: stream.get(field) for field in expected if field != "codec"}
    observed["codec"] = stream.get("codec_name")
    container = _probe_container(path)
    expected["container"] = profile.container
    observed["container"] = container
    mismatches: list[dict[str, Any]] = []
    for field, expected_value in expected.items():
        if field == "container":
            # ffprobe reports a family such as "mov,mp4,m4a,3gp,3g2,mj2"; the
            # profile container must appear in it.
            names = (observed[field] or "").lower().split(",")
            matched = expected_value.lower() in names
        else:
            matched = _normalise_tag(field, observed[field]) == _normalise_tag(
                field, expected_value
            )
        if not matched:
            mismatches.append(
                {"field": field, "expected": expected_value, "observed": observed[field]}
            )
    return {
        "valid": not mismatches,
        "expected": expected,
        "observed": observed,
        "mismatches": mismatches,
    }


def _probe_container(path: Path) -> str | None:
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=format_name",
         "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _normalise_tag(field: str, value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    normalised = value.lower()
    if field == "color_range":
        return {
            "tv": "limited",
            "mpeg": "limited",
            "limited": "limited",
            "pc": "full",
            "jpeg": "full",
            "full": "full",
        }.get(normalised, normalised)
    return normalised


def _as_shots(
    cutlist: Path | str | Sequence[Shot] | None, frame_count: int
) -> list[Shot]:
    if cutlist is None:
        return [Shot(0, frame_count)]
    shots = read_cutlist(Path(cutlist)) if isinstance(cutlist, (str, Path)) else list(cutlist)
    if not shots:
        raise VerificationError("cut list has no shots")
    for index, shot in enumerate(shots):
        if not isinstance(shot, Shot):
            raise TypeError(f"cut list entry {index} is not a Shot")
        if shot.start_frame < 0 or shot.end_frame <= shot.start_frame:
            raise VerificationError(f"cut list shot {index} has an invalid frame interval")
        if shot.end_frame > frame_count:
            raise VerificationError(
                f"cut list shot {index} ends at frame {shot.end_frame}, delivery has {frame_count}"
            )
    return shots


def _sample_shot_frames(shots: Sequence[Shot], no_cutlist: bool) -> list[list[int]]:
    if no_cutlist:
        count = shots[0].end_frame
        if count <= 5:
            return [list(range(count))]
        return [[round(index * (count - 1) / 4) for index in range(5)]]
    return [
        [shot.start_frame + position for position in sample_positions(shot.end_frame - shot.start_frame)]
        for shot in shots
    ]


#: Cap on how many violating frames are recorded verbatim in a range report.
_MAX_RECORDED_VIOLATIONS = 32


def _verify_native_range(
    path: Path,
    stream: Mapping[str, Any],
    profile: DeliveryProfile,
    expected_frame_count: int,
) -> dict[str, Any]:
    """Check native YUV legality on EVERY delivery frame, not a sample.

    Sample-range legality is a hard gate, so a single illegal frame between
    sampled positions must not pass. The whole stream is decoded once to native
    planar YUV and each frame's plane extrema are checked as it streams by.
    """
    width, height = _stream_dimensions(stream)
    pix_fmt = stream.get("pix_fmt")
    if not isinstance(pix_fmt, str) or not pix_fmt:
        raise VerificationError("ffprobe did not report a native pixel format")
    layout = _yuv_layout(pix_fmt, width, height, stream.get("bits_per_raw_sample"))

    scale = 1 << max(0, layout.bit_depth - 8)
    maximum = (1 << layout.bit_depth) - 1
    if profile.range == "limited":
        bounds = {
            "Y": {"minimum": 16 * scale, "maximum": 235 * scale},
            "Cb": {"minimum": 16 * scale, "maximum": 240 * scale},
            "Cr": {"minimum": 16 * scale, "maximum": 240 * scale},
        }
    else:
        bounds = {
            plane: {"minimum": 0, "maximum": maximum}
            for plane in ("Y", "Cb", "Cr")
        }

    violations: list[dict[str, Any]] = []
    global_extrema = {
        plane: {"minimum": maximum + 1, "maximum": -1}
        for plane in ("Y", "Cb", "Cr")
    }
    frames_scanned = 0
    for frame_index, chunk in enumerate(_stream_native_frames(path, pix_fmt, layout)):
        frames_scanned += 1
        plane_extrema = _frame_plane_extrema(chunk, 0, layout)
        for plane, extrema in plane_extrema.items():
            global_extrema[plane]["minimum"] = min(
                global_extrema[plane]["minimum"], extrema["minimum"]
            )
            global_extrema[plane]["maximum"] = max(
                global_extrema[plane]["maximum"], extrema["maximum"]
            )
            allowed = bounds[plane]
            for extremum, value, breached in (
                ("minimum", extrema["minimum"], extrema["minimum"] < allowed["minimum"]),
                ("maximum", extrema["maximum"], extrema["maximum"] > allowed["maximum"]),
            ):
                if breached and len(violations) < _MAX_RECORDED_VIOLATIONS:
                    violations.append(
                        {
                            "plane": plane,
                            "frame": frame_index,
                            "extremum": extremum,
                            "value": value,
                            "allowed_minimum": allowed["minimum"],
                            "allowed_maximum": allowed["maximum"],
                        }
                    )
    if frames_scanned == 0:
        raise VerificationError("delivery decoded to zero frames for range verification")
    # "Exhaustive" has to mean the frames the container stores, not the frames a
    # re-timed decode happened to emit. If those disagree the coverage claim is
    # false, so refuse rather than report a fabricated denominator.
    if frames_scanned != expected_frame_count:
        raise VerificationError(
            f"delivery decoded to {frames_scanned} frames but the container stores "
            f"{expected_frame_count}; the decode re-timed the stream, so per-frame "
            "legality could not be established"
        )
    return {
        "valid": not violations,
        "declared_range": profile.range,
        "pix_fmt": pix_fmt,
        "bit_depth": layout.bit_depth,
        "bounds": bounds,
        "frames_scanned": frames_scanned,
        "coverage": "exhaustive",
        "extrema": global_extrema,
        "violations": violations,
    }


def _verify_introduced_clipping(
    delivery: Path,
    profile: DeliveryProfile,
    delivery_frame_count: int,
    delivery_stream: Mapping[str, Any],
    source_reference: Path | None,
    source_params: ConvertParams | None,
    source_curve_gamut: str | None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "available": False,
        "domain": INTRODUCED_CLIPPING_DOMAIN,
        "low_threshold": CLIPPING_CODE_THRESHOLD,
        "high_threshold": 1.0 - CLIPPING_CODE_THRESHOLD,
        "coverage": "exhaustive",
        "sample_count": 0,
        "source_clipped_samples": 0,
        "delivery_clipped_samples": 0,
        "introduced_clipped_samples": 0,
        "introduced_clipping_percent": None,
        "authentication": _reference_authentication_base(),
    }
    if source_reference is None:
        return {**base, "reason": "source reference not supplied"}
    if _same_file(delivery, source_reference):
        raise VerificationError(
            "source reference is the delivery itself; --source-reference must name "
            "the distinct pre-grade source"
        )
    if source_params is None:
        raise VerificationError(
            "source decode parameters are required for introduced clipping verification"
        )
    source_frame_count = len(frames_to_pts(source_reference))
    if source_frame_count != delivery_frame_count:
        raise VerificationError(
            "source and delivery frame counts differ for introduced clipping verification"
        )
    source_stream = _probe_video_stream(source_reference)
    if _stream_dimensions(source_stream) != _stream_dimensions(delivery_stream):
        raise VerificationError(
            "source and delivery dimensions differ for introduced clipping verification"
        )
    width, height = _stream_dimensions(delivery_stream)

    delivery_params = ConvertParams(
        range=profile.range,
        matrix=profile.colorspace,
        transfer=profile.color_trc,
        primaries=profile.color_primaries,
    )
    authentication = _authenticate_source_reference(
        source_reference,
        delivery,
        delivery_frame_count,
        source_params,
        source_curve_gamut,
        delivery_params,
    )
    if authentication["evidence_frames"] == 0:
        return {
            **base,
            "authentication": authentication,
            "reason": (
                "source reference authentication yielded no usable evidence: all "
                f"{authentication['degenerate_frames']} sampled frames had near-zero "
                "luma variance or fewer than "
                f"{REFERENCE_AUTHENTICATION_MIN_LEVELS} distinct luma levels"
            ),
        }
    if authentication["correlation"] < REFERENCE_AUTHENTICATION_THRESHOLD:
        return {
            **base,
            "authentication": authentication,
            "reason": (
                "source reference authentication failed: median Spearman rank "
                f"correlation {authentication['correlation']:.6f} is below "
                f"{REFERENCE_AUTHENTICATION_THRESHOLD:.6f}"
            ),
        }
    # Introduced clipping is a hard gate, so it compares EVERY frame, not a
    # sample. Both files stream one frame at a time and the counts accumulate,
    # so peak memory is two frames regardless of length.
    source_frames = _stream_display_rgb(
        source_reference, source_params, source_curve_gamut, width, height
    )
    delivery_frames = _stream_display_rgb(delivery, delivery_params, None, width, height)
    statistics = _introduced_clipping_statistics(source_frames, delivery_frames)
    # Both files are decoded with passthrough timing, so the pairs compared
    # must equal what the containers store. A mismatch means a re-timed
    # decode weighted some frames more than once.
    if statistics["frames_compared"] != delivery_frame_count:
        raise VerificationError(
            f"clipping compared {statistics['frames_compared']} frame pairs but the "
            f"delivery stores {delivery_frame_count}; the decode re-timed the stream"
        )
    return {
        **base,
        **statistics,
        "available": True,
        "authentication": authentication,
        "reason": None,
    }


def _reference_authentication_base() -> dict[str, Any]:
    return {
        "method": "median_spearman_rank_correlation",
        "correlation": None,
        "threshold": REFERENCE_AUTHENTICATION_THRESHOLD,
        "sampled_frames": [],
        "evidence_frames": 0,
        "degenerate_frames": 0,
        "frame_correlations": [],
    }


def _same_file(first: Path, second: Path) -> bool:
    """Recognize path aliases and hard links before accepting a reference."""
    if first.resolve() == second.resolve():
        return True
    try:
        first_stat = first.stat()
        second_stat = second.stat()
    except OSError:
        return False
    return (first_stat.st_dev, first_stat.st_ino) == (
        second_stat.st_dev,
        second_stat.st_ino,
    )


def _authenticate_source_reference(
    source: Path,
    delivery: Path,
    frame_count: int,
    source_params: ConvertParams,
    source_curve_gamut: str | None,
    delivery_params: ConvertParams,
) -> dict[str, Any]:
    """Compare spatial rank structure on a few small aligned frame rasters."""
    frames = sample_positions(frame_count)
    correlations: list[dict[str, float | int]] = []
    degenerate_frames = 0
    for frame in frames:
        source_luma = _read_authentication_luma(
            source, frame, source_params, source_curve_gamut
        )
        delivery_luma = _read_authentication_luma(
            delivery, frame, delivery_params, None
        )
        source_levels = _authentication_levels(source_luma)
        delivery_levels = _authentication_levels(delivery_luma)
        if _authentication_frame_is_degenerate(source_luma, source_levels) or (
            _authentication_frame_is_degenerate(delivery_luma, delivery_levels)
        ):
            degenerate_frames += 1
            continue
        correlation = _spearman_rank_correlation(source_levels, delivery_levels)
        correlations.append({"frame": frame, "correlation": correlation})

    result = _reference_authentication_base()
    result.update(
        {
            "sampled_frames": frames,
            "evidence_frames": len(correlations),
            "degenerate_frames": degenerate_frames,
            "frame_correlations": correlations,
        }
    )
    if correlations:
        result["correlation"] = float(
            np.median([item["correlation"] for item in correlations])
        )
    return result


def _read_authentication_luma(
    path: Path,
    frame_index: int,
    params: ConvertParams,
    curve_gamut: str | None,
) -> np.ndarray:
    """Decode one selected frame directly to the small authentication raster."""
    vf = (
        f"select=eq(n\\,{frame_index}),"
        f"scale={REFERENCE_AUTHENTICATION_WIDTH}:{REFERENCE_AUTHENTICATION_HEIGHT}:"
        f"flags=area:in_range={params.sws_range}:out_range=pc:"
        f"in_color_matrix={params.matrix}:out_color_matrix=bt709,format=gbrpf32le"
    )
    result = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            vf,
            "-map",
            "0:v:0",
            "-an",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gbrpf32le",
            "-",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        raise VerificationError(
            "reference authentication decode failed: "
            + result.stderr.decode(errors="replace")[-1000:]
        )
    expected_bytes = (
        3
        * REFERENCE_AUTHENTICATION_WIDTH
        * REFERENCE_AUTHENTICATION_HEIGHT
        * 4
    )
    if len(result.stdout) != expected_bytes:
        raise VerificationError(
            f"reference authentication frame {frame_index} decoded to "
            f"{len(result.stdout)} bytes, expected {expected_bytes}"
        )
    planes = np.frombuffer(result.stdout, dtype="<f4").reshape(
        3, REFERENCE_AUTHENTICATION_HEIGHT, REFERENCE_AUTHENTICATION_WIDTH
    )
    green, blue, red = planes
    code = np.stack([red, green, blue], axis=-1).astype(np.float64)
    if curve_gamut is None:
        display_rgb = np.clip(code, 0.0, 1.0)
    else:
        display_rgb = bt1886_encode(camera_to_working(curve_gamut, code))
    if not np.all(np.isfinite(display_rgb)):
        raise VerificationError("reference authentication produced non-finite RGB samples")
    return display_rgb @ _REC709_LUMA


def _authentication_levels(luma: np.ndarray) -> np.ndarray:
    """Quantize luma to stable display-code levels before ranking ties."""
    return np.rint(np.clip(luma, 0.0, 1.0) * 255.0).astype(np.uint8)


def _authentication_frame_is_degenerate(
    luma: np.ndarray, levels: np.ndarray
) -> bool:
    return (
        float(np.std(luma)) < REFERENCE_AUTHENTICATION_MIN_LUMA_STD
        or np.unique(levels).size < REFERENCE_AUTHENTICATION_MIN_LEVELS
    )


def _spearman_rank_correlation(first: np.ndarray, second: np.ndarray) -> float:
    from scipy.stats import rankdata

    first_ranks = rankdata(first.ravel(), method="average")
    second_ranks = rankdata(second.ravel(), method="average")
    correlation = float(np.corrcoef(first_ranks, second_ranks)[0, 1])
    if not np.isfinite(correlation):
        raise VerificationError("reference authentication correlation is non-finite")
    return correlation


def _stream_display_rgb(
    path: Path,
    params: ConvertParams,
    curve_gamut: str | None,
    width: int,
    height: int,
):
    """Yield each frame of ``path`` as full-range Rec.709 display-code RGB.

    The whole file is decoded once. Log source is decoded at data level and
    mapped to display code in Python; display-referred input is clipped to the
    unit range. Peak memory is one frame.
    """
    vf = (
        f"scale=in_range={params.sws_range}:out_range=pc:"
        f"in_color_matrix={params.matrix}:out_color_matrix=bt709,format=gbrpf32le"
    )
    frame_bytes = 3 * width * height * 4
    proc = subprocess.Popen(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            vf,
            "-map",
            "0:v:0",
            "-an",
            # VFR input must not be re-timed. Without passthrough, ffmpeg
            # duplicates frames to reach a constant output rate: measured
            # 2026-07-23 on a 5-frame VFR file (PTS 0, .04, .16, .36, .64),
            # this pipe emitted 22 frames. Duration-weighted samples give a
            # fabricated denominator and can flip the clipping gate.
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gbrpf32le",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None
    try:
        while True:
            chunk = _read_exact(proc.stdout, frame_bytes)
            if chunk is None:
                break
            planes = np.frombuffer(chunk, dtype="<f4").reshape(3, height, width)
            green, blue, red = planes
            code = np.stack([red, green, blue], axis=-1).astype(np.float64)
            if curve_gamut is None:
                yield np.clip(code, 0.0, 1.0)
            else:
                yield bt1886_encode(camera_to_working(curve_gamut, code))
    finally:
        remaining_stderr = proc.stderr.read() if proc.stderr else b""
        proc.stdout.close()
        code = proc.wait()
        if code != 0:
            raise VerificationError(
                f"display decode failed: {remaining_stderr.decode(errors='replace')[-1000:]}"
            )


def _introduced_clipping_statistics(
    source_frames, delivery_frames
) -> dict[str, int | float]:
    """Count delivered clipped RGB samples that were not clipped in source.

    Accepts sequences or generators; frames are consumed pairwise so memory
    stays bounded to two frames.
    """
    import itertools

    sentinel = object()
    frames_compared = 0
    sample_count = 0
    source_clipped_samples = 0
    delivery_clipped_samples = 0
    introduced_clipped_samples = 0
    high = 1.0 - CLIPPING_CODE_THRESHOLD
    for source, delivery in itertools.zip_longest(
        source_frames, delivery_frames, fillvalue=sentinel
    ):
        if source is sentinel or delivery is sentinel:
            raise VerificationError(
                "source and delivery clipping comparisons require aligned frames"
            )
        source_array = np.asarray(source, dtype=np.float64)
        delivery_array = np.asarray(delivery, dtype=np.float64)
        if source_array.shape != delivery_array.shape or source_array.ndim != 3:
            raise VerificationError(
                "source and delivery clipping frames must have matching RGB rasters"
            )
        if source_array.shape[-1] != 3:
            raise VerificationError("clipping comparison frames must contain RGB channels")
        if not np.all(np.isfinite(source_array)) or not np.all(np.isfinite(delivery_array)):
            raise VerificationError("clipping comparison produced non-finite RGB samples")
        source_low = source_array <= CLIPPING_CODE_THRESHOLD
        source_high = source_array >= high
        delivery_low = delivery_array <= CLIPPING_CODE_THRESHOLD
        delivery_high = delivery_array >= high
        source_clipped = source_low | source_high
        delivery_clipped = delivery_low | delivery_high
        # Endpoint-aware: a sample newly clipped at EITHER end is introduced
        # clipping. Collapsing low and high into one mask would treat a
        # source-black, delivery-white sample as pre-existing and miss it.
        introduced = (delivery_low & ~source_low) | (delivery_high & ~source_high)
        frames_compared += 1
        sample_count += int(source_array.size)
        source_clipped_samples += int(np.count_nonzero(source_clipped))
        delivery_clipped_samples += int(np.count_nonzero(delivery_clipped))
        introduced_clipped_samples += int(np.count_nonzero(introduced))
    if sample_count == 0:
        raise VerificationError("clipping comparison had no frames to compare")
    return {
        "frames_compared": frames_compared,
        "sample_count": sample_count,
        "source_clipped_samples": source_clipped_samples,
        "delivery_clipped_samples": delivery_clipped_samples,
        "introduced_clipped_samples": introduced_clipped_samples,
        "introduced_clipping_percent": (
            100.0 * introduced_clipped_samples / sample_count
        ),
    }


def _stream_dimensions(stream: Mapping[str, Any]) -> tuple[int, int]:
    try:
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, TypeError, ValueError) as error:
        raise VerificationError("ffprobe did not report valid video dimensions") from error
    if width <= 0 or height <= 0:
        raise VerificationError("video dimensions must be positive")
    return width, height


def _yuv_layout(
    pix_fmt: str, width: int, height: int, raw_depth: object
) -> _YUVLayout:
    normalised = pix_fmt.replace("yuvj", "yuv", 1)
    match = re.fullmatch(r"yuv(420|422|444)p(?:(8|9|10|12|14|16)(le|be)?)?", normalised)
    if match is None:
        raise VerificationError(
            f"native pixel format {pix_fmt!r} is unsupported for raw planar YUV range verification"
        )
    subsampling, suffix_depth, endian = match.groups()
    try:
        bit_depth = int(suffix_depth or raw_depth or 8)
    except (TypeError, ValueError) as error:
        raise VerificationError(f"cannot determine bit depth for {pix_fmt}") from error
    if bit_depth < 8:
        raise VerificationError(f"unsupported bit depth {bit_depth} for {pix_fmt}")
    h_subsample = 2 if subsampling in {"420", "422"} else 1
    v_subsample = 2 if subsampling == "420" else 1
    return _YUVLayout(
        pix_fmt=pix_fmt,
        bit_depth=bit_depth,
        bytes_per_sample=1 if bit_depth <= 8 else 2,
        little_endian=endian != "be",
        chroma_width=(width + h_subsample - 1) // h_subsample,
        chroma_height=(height + v_subsample - 1) // v_subsample,
        width=width,
        height=height,
    )




def _stream_native_frames(path: Path, pix_fmt: str, layout: _YUVLayout):
    """Yield one native planar-YUV frame at a time for the whole stream.

    The whole file is decoded in a single ffmpeg pass and read in exact
    per-frame chunks, so peak memory is one frame regardless of length.
    """
    frame_bytes = layout.frame_bytes
    proc = subprocess.Popen(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            # VFR input must not be re-timed. Without passthrough, ffmpeg
            # duplicates frames to reach a constant output rate: measured
            # 2026-07-23 on a 5-frame VFR file (PTS 0, .04, .16, .36, .64),
            # this pipe emitted 22 frames. Duration-weighted samples give a
            # fabricated denominator and can flip the clipping gate.
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-pix_fmt",
            pix_fmt,
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None
    try:
        while True:
            chunk = _read_exact(proc.stdout, frame_bytes)
            if chunk is None:
                break
            yield chunk
    finally:
        remaining_stderr = proc.stderr.read() if proc.stderr else b""
        proc.stdout.close()
        code = proc.wait()
        if code != 0:
            raise VerificationError(
                f"native raw decode failed: {remaining_stderr.decode(errors='replace')[-1000:]}"
            )


def _read_exact(stream, size: int) -> bytes | None:
    """Read exactly ``size`` bytes, or None at a clean end of stream."""
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        piece = stream.read(remaining)
        if not piece:
            break
        chunks.append(piece)
        remaining -= len(piece)
    if not chunks:
        return None
    data = b"".join(chunks)
    if len(data) != size:
        raise VerificationError(
            f"native decode ended mid-frame: got {len(data)} of {size} bytes"
        )
    return data


def _frame_plane_extrema(raw: bytes, frame: int, layout: _YUVLayout) -> dict[str, dict[str, int]]:
    offset = frame * layout.frame_bytes
    y_count = layout.width * layout.height
    chroma_count = layout.chroma_width * layout.chroma_height
    result: dict[str, dict[str, int]] = {}
    for plane, count in (("Y", y_count), ("Cb", chroma_count), ("Cr", chroma_count)):
        end = offset + count * layout.bytes_per_sample
        values = np.frombuffer(
            raw,
            dtype=_sample_dtype(layout),
            count=count,
            offset=offset,
        )
        if not len(values):
            raise VerificationError(f"raw decode has no {plane} samples at frame {frame}")
        result[plane] = {"minimum": int(values.min()), "maximum": int(values.max())}
        offset = end
    return result


def _sample_dtype(layout: _YUVLayout) -> np.dtype[Any]:
    if layout.bytes_per_sample == 1:
        return np.dtype(np.uint8)
    return np.dtype("<u2" if layout.little_endian else ">u2")


def _remeasure_frozen_rois(
    delivery: Path,
    profile: DeliveryProfile,
    shots: Sequence[Shot],
    shot_frames: Sequence[Sequence[int]],
    frozen_masks: object,
    stream: Mapping[str, Any],
) -> list[ShotMeasurement]:
    if _frozen_masks_absent(frozen_masks):
        return []
    width, height = _stream_dimensions(stream)
    params = ConvertParams(
        range=profile.range,
        matrix=profile.colorspace,
        transfer=profile.color_trc,
        primaries=profile.color_primaries,
    )
    with tempfile.TemporaryDirectory(prefix="colorist-verify-") as temporary:
        temp_dir = Path(temporary)
        alias = temp_dir / delivery.name
        alias.symlink_to(delivery.resolve())
        measurements: list[ShotMeasurement] = []
        for index, frames in enumerate(shot_frames):
            if not frames:
                raise VerificationError(f"shot {index} has no sample frames")
            supplied = _mask_paths_for_shot(frozen_masks, index)
            _stage_masks(
                alias,
                frames,
                supplied,
                width,
                height,
                params,
                temp_dir,
            )
            measurements.append(
                measure_shot(
                    alias,
                    list(frames),
                    params,
                    None,
                    artifact_dir=temp_dir,
                    shot_frame_count=shots[index].end_frame - shots[index].start_frame,
                )
            )
        return measurements


def _frozen_masks_absent(frozen_masks: object) -> bool:
    """Treat omitted and empty frozen-mask collections as absent evidence."""
    if frozen_masks is None:
        return True
    return isinstance(frozen_masks, (Mapping, Sequence)) and not frozen_masks


def _mask_paths_for_shot(frozen_masks: object, index: int) -> dict[str, Path]:
    if isinstance(frozen_masks, Mapping):
        if index in frozen_masks:
            selected = frozen_masks[index]
        elif str(index) in frozen_masks:
            selected = frozen_masks[str(index)]
        elif "shots" in frozen_masks and isinstance(frozen_masks["shots"], Sequence):
            shots = frozen_masks["shots"]
            selected = shots[index] if index < len(shots) else None
        else:
            selected = None
    elif isinstance(frozen_masks, Sequence) and not isinstance(frozen_masks, (str, bytes, Path)):
        selected = frozen_masks[index] if index < len(frozen_masks) else None
    else:
        selected = frozen_masks if index == 0 else None
    return _collect_mask_paths(selected)


def _collect_mask_paths(value: object) -> dict[str, Path]:
    if value is None:
        return {}
    if isinstance(value, ShotMeasurement):
        return _collect_mask_paths((value.neutral, value.skin))
    if isinstance(value, MaskStat):
        return _collect_mask_paths(value.frozen_mask_path)
    if isinstance(value, (str, Path)):
        path = Path(value)
        mask_type = _mask_type(path)
        return {} if mask_type is None else {mask_type: path}
    if isinstance(value, Mapping):
        masks: dict[str, Path] = {}
        for name in ("neutral", "skin"):
            if name in value:
                masks.update(_collect_mask_paths(value[name]))
        if "measurement" in value:
            masks.update(_collect_mask_paths(value["measurement"]))
        return masks
    if isinstance(value, Sequence):
        masks: dict[str, Path] = {}
        for item in value:
            masks.update(_collect_mask_paths(item))
        return masks
    raise TypeError("frozen_masks must contain source mask paths or ShotMeasurement values")


def _mask_type(path: Path) -> str | None:
    name = path.name
    if ".neutral.mask.npz" in name:
        return "neutral"
    if ".skin.mask.npz" in name:
        return "skin"
    raise ValueError(f"cannot infer frozen mask type from {path}")


def _stage_masks(
    alias: Path,
    frames: Sequence[int],
    supplied: Mapping[str, Path],
    width: int,
    height: int,
    params: ConvertParams,
    artifact_dir: Path,
) -> None:
    base_identity = _mask_cache_identity(
        alias, list(frames), params, None, (height, width)
    )
    for name in ("neutral", "skin"):
        destination = _frozen_mask_path(
            alias,
            list(frames),
            name,
            params,
            None,
            artifact_dir,
        )
        identity = {**base_identity, "mask_type": name}
        source = supplied.get(name)
        if source is None:
            # An explicit empty frozen ROI is the truthful representation of
            # absent source evidence.  It prevents measure_shot from deriving
            # a fresh candidate mask from the delivery.
            _save_frozen_mask(
                destination,
                np.zeros((height, width), dtype=bool),
                identity,
            )
        else:
            if not source.is_file():
                raise VerificationError(f"frozen {name} mask does not exist: {source}")
            with np.load(source, allow_pickle=False) as archive:
                if "mask" not in archive or "identity_json" not in archive:
                    raise VerificationError(
                        f"frozen {name} mask cache record is incomplete: {source}"
                    )
                mask = np.asarray(archive["mask"], dtype=bool)
            if mask.shape != (height, width):
                raise VerificationError(
                    f"frozen {name} mask has shape {mask.shape}, expected {(height, width)}"
                )
            _save_frozen_mask(destination, mask, identity)


def _measurement_report(
    shot: int,
    frames: Sequence[int],
    measurement: ShotMeasurement,
    profile: DeliveryProfile,
) -> dict[str, Any]:
    return {
        "shot": shot,
        "frames": list(frames),
        "temporal_coverage_sufficient": measurement.temporal_coverage_sufficient,
        "luma_percentiles": measurement.luma_percentiles,
        "neutral": _mask_report(measurement.neutral),
        "skin": _mask_report(measurement.skin),
        "colorimetry": _colorimetry(measurement.neutral, profile),
    }


def _mask_report(mask: MaskStat | None) -> dict[str, Any] | None:
    if mask is None:
        return None
    return {
        "median_rgb": list(mask.median_rgb) if mask.median_rgb is not None else None,
        "sample_px": mask.sample_px,
        "frames_used": mask.frames_used,
        "multimodal": mask.multimodal,
        "multimodal_axes": list(mask.multimodal_axes),
        "regions": [
            {"median_rgb": list(region.median_rgb), "px": region.px, "bbox": list(region.bbox)}
            for region in mask.regions
        ],
    }


def _colorimetry(mask: MaskStat | None, profile: DeliveryProfile) -> dict[str, Any]:
    """Return optional CCT, Duv, and DE2000 for valid neutral evidence."""
    if mask is None:
        return {"available": False, "reason": "neutral evidence absent"}
    if mask.multimodal or mask.median_rgb is None:
        return {"available": False, "reason": "neutral evidence is multimodal"}
    if profile.color_primaries != "bt709" or profile.color_trc != "bt709":
        return {
            "available": False,
            "reason": "no identified RGB-to-XYZ transform for this delivery profile",
        }
    try:
        import colour

        colourspace = colour.RGB_COLOURSPACES["ITU-R BT.709"]
        rgb = np.asarray(mask.median_rgb, dtype=np.float64)
        xyz = np.asarray(
            colour.RGB_to_XYZ(rgb, colourspace, apply_cctf_decoding=True), dtype=np.float64
        )
        uv = np.asarray(colour.xy_to_UCS_uv(colour.XYZ_to_xy(xyz)), dtype=np.float64)
        cct_duv = np.asarray(colour.uv_to_CCT(uv, method="Ohno 2013"), dtype=np.float64)
        reference_xyz = np.asarray(colour.xy_to_XYZ(colourspace.whitepoint), dtype=np.float64)
        reference_xyz *= xyz[1] / reference_xyz[1]
        lab = colour.XYZ_to_Lab(xyz, colourspace.whitepoint)
        reference_lab = colour.XYZ_to_Lab(reference_xyz, colourspace.whitepoint)
        delta_e = float(colour.delta_E(lab, reference_lab, method="CIE 2000"))
        return {
            "available": True,
            "reference_white": "D65",
            "cct_kelvin": float(cct_duv[0]),
            "duv": float(cct_duv[1]),
            "delta_e2000": delta_e,
        }
    except Exception as error:  # Optional scientist-grade metrics cannot hide QC.
        return {"available": False, "reason": f"colorimetry unavailable: {type(error).__name__}"}


def _aggregate_gate_runs(runs: Sequence[RunResult]) -> RunResult:
    if not runs:
        return RunResult(state="ERROR", gates=[], error="no gate evaluation was performed")
    if any(run.state == "ERROR" for run in runs):
        first_error = next(run.error for run in runs if run.state == "ERROR")
        return RunResult(state="ERROR", gates=[], error=first_error)
    lengths = {len(run.gates) for run in runs}
    if len(lengths) != 1:
        return RunResult(state="ERROR", gates=[], error="gate evaluation returned inconsistent outcomes")

    status_rank = {
        "FAIL": 5,
        "INDETERMINATE_ABSENT_EVIDENCE": 4,
        "SKIPPED_ABSENT_EVIDENCE": 3,
        "WAIVED": 2,
        "PASS": 1,
    }
    outcomes: list[GateOutcome] = []
    for grouped in zip(*(run.gates for run in runs)):
        worst = max(grouped, key=lambda outcome: status_rank[outcome.status])
        outcomes.append(
            GateOutcome(
                gate_id=worst.gate_id,
                status=worst.status,
                observed=worst.observed,
                threshold=worst.threshold,
                domain=worst.domain,
                operator=worst.operator,
                numbers=worst.numbers,
                waiver=worst.waiver,
                reason=worst.reason,
            )
        )
    if any(outcome.status == "FAIL" for outcome in outcomes):
        return RunResult(state="FAIL", gates=outcomes)
    if any(run.state == "INDETERMINATE" for run in runs):
        return RunResult(state="INDETERMINATE", gates=outcomes)
    return RunResult(state="PASS", gates=outcomes)


#: The grade-introduced clipping ceiling, in percent, enforced on every delivery
#: regardless of the preset. Matches the shipped interview preset.
MANDATORY_CLIPPING_THRESHOLD_PCT = 0.5

#: Delivery hard gates that MUST be evaluated for a PASS, whatever the preset says.
_MANDATORY_DELIVERY_GATES = (
    "delivery_tags_match",
    "delivery_range_extrema",
    "introduced_clipping",
)


def _apply_delivery_invariants(
    result: RunResult,
    *,
    metadata_valid: bool,
    range_valid: bool,
    clipping_report: Mapping[str, Any],
) -> RunResult:
    """Enforce the complete delivery hard-gate inventory outside the preset.

    Delivery tag legality, native sample range, and grade-introduced clipping
    are processing invariants, not tunable creative gates. A user preset may add
    soft gates but can neither omit nor weaken these three: their outcomes are
    always computed here from the measured evidence, replacing any preset copy,
    so a preset that lists no hard gate can never produce a vacuous PASS. Missing
    clipping evidence (no source reference) is INDETERMINATE, never PASS.
    """
    if result.state == "ERROR":
        return result

    tags = GateOutcome(
        gate_id="delivery_tags_match",
        status="PASS" if metadata_valid else "FAIL",
        observed=bool(metadata_valid),
        threshold=True,
        domain="decoded delivery color metadata tags against the declared output profile",
        operator="equals",
        numbers={"observed": 1.0 if metadata_valid else 0.0, "threshold": 1.0},
    )
    native_range = GateOutcome(
        gate_id="delivery_range_extrema",
        status="PASS" if range_valid else "FAIL",
        observed=bool(range_valid),
        threshold=True,
        domain="decoded delivery Y Cb Cr samples in the declared output range",
        operator="equals",
        numbers={"observed": 1.0 if range_valid else 0.0, "threshold": 1.0},
    )
    clipping = _clipping_invariant_outcome(clipping_report)

    invariant_ids = {gate.gate_id for gate in (tags, native_range, clipping)}
    preserved = [gate for gate in result.gates if gate.gate_id not in invariant_ids]
    outcomes = [*preserved, tags, native_range, clipping]

    if any(gate.status == "FAIL" for gate in outcomes):
        state = "FAIL"
    elif any(
        gate.status in {"INDETERMINATE_ABSENT_EVIDENCE"} for gate in (tags, native_range, clipping)
    ) or result.state == "INDETERMINATE":
        state = "INDETERMINATE"
    else:
        state = "PASS"
    return RunResult(state=state, gates=outcomes, error=result.error)


def _clipping_invariant_outcome(clipping_report: Mapping[str, Any]) -> GateOutcome:
    domain = str(clipping_report.get("domain", INTRODUCED_CLIPPING_DOMAIN))
    if not clipping_report.get("available"):
        return GateOutcome(
            gate_id="introduced_clipping",
            status="INDETERMINATE_ABSENT_EVIDENCE",
            observed=None,
            threshold=MANDATORY_CLIPPING_THRESHOLD_PCT,
            domain=domain,
            operator="less_than_or_equal",
            numbers={"threshold": MANDATORY_CLIPPING_THRESHOLD_PCT},
            reason=str(clipping_report.get("reason") or "introduced clipping evidence absent"),
        )
    percent = float(clipping_report["introduced_clipping_percent"])
    return GateOutcome(
        gate_id="introduced_clipping",
        status="PASS" if percent <= MANDATORY_CLIPPING_THRESHOLD_PCT else "FAIL",
        observed=percent,
        threshold=MANDATORY_CLIPPING_THRESHOLD_PCT,
        domain=domain,
        operator="less_than_or_equal",
        numbers={"observed": percent, "threshold": MANDATORY_CLIPPING_THRESHOLD_PCT},
    )


def _write_reports(
    delivery: Path,
    result: RunResult,
    metadata: Mapping[str, Any],
    range_report: Mapping[str, Any],
    clipping_report: Mapping[str, Any],
    measurements: Sequence[Mapping[str, Any]],
    *,
    report_dir: Path | str | None = None,
    workflow: str | None = None,
) -> None:
    run: dict[str, Any] = {"state": result.state, "error": result.error}
    if workflow is not None:
        run["workflow"] = workflow
    report = {
        "run": run,
        "gates": [gate_outcome_payload(outcome) for outcome in result.gates],
        "metadata": dict(metadata),
        "range": dict(range_report),
        "clipping": dict(clipping_report),
        "measurements": list(measurements),
    }
    destination = delivery.parent if report_dir is None else Path(report_dir)
    existing = [
        path
        for path in (destination / "report.json", destination / "report.md")
        if path.exists()
    ]
    if existing:
        raise FileExistsError(
            "report exists; refusing to overwrite: "
            + ", ".join(str(path) for path in existing)
        )
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "report.json").open("x") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    with (destination / "report.md").open("x") as handle:
        handle.write(_markdown_report(report, result.gates))


def _markdown_report(report: Mapping[str, Any], gates: Sequence[GateOutcome]) -> str:
    run = report["run"]
    metadata = report["metadata"]
    range_report = report["range"]
    clipping = report["clipping"]
    lines = [
        "# Delivery verification",
        "",
        f"Result: **{run['state']}**",
        "",
        "Engineer units: RGB and luma values use full-range 8-bit scale. Native YUV values use the delivered file's code-value bit depth.",
        "",
        "## Metadata",
        "",
        f"- Status: {'PASS' if metadata.get('valid') else 'FAIL'}",
    ]
    for field, expected in metadata.get("expected", {}).items():
        observed = metadata.get("observed", {}).get(field)
        lines.append(f"- {field}: observed `{observed}`, expected `{expected}`")

    lines.extend(["", "## Sample range", ""])
    lines.append(f"- Status: {'PASS' if range_report.get('valid') else 'FAIL'}")
    lines.append(
        f"- Declared range: {range_report.get('declared_range')}; "
        f"native format: {range_report.get('pix_fmt')}; bit depth: {range_report.get('bit_depth')}"
    )
    for violation in range_report.get("violations", []):
        lines.append(
            "- {plane} frame {frame} {extremum}: {value}; allowed "
            "{allowed_minimum} to {allowed_maximum}".format(**violation)
        )

    lines.extend(["", "## Introduced clipping", ""])
    authentication = clipping.get("authentication", {})
    correlation = authentication.get("correlation")
    if correlation is not None:
        lines.append(
            f"- Reference authentication: median Spearman rank correlation "
            f"{correlation:.6f}; threshold {authentication.get('threshold'):.6f}"
        )
    if authentication.get("sampled_frames"):
        lines.append(
            f"- Authentication frames: {authentication.get('evidence_frames')} usable; "
            f"{authentication.get('degenerate_frames')} degenerate; sampled "
            f"{authentication.get('sampled_frames')}"
        )
    if clipping.get("available"):
        lines.append(
            "- Measured: {introduced_clipping_percent:.6f}% "
            "({introduced_clipped_samples}/{sample_count} RGB samples)".format(
                **clipping
            )
        )
        lines.append(
            f"- Source clipped samples: {clipping.get('source_clipped_samples')}; "
            f"delivery clipped samples: {clipping.get('delivery_clipped_samples')}"
        )
    else:
        lines.append(f"- INDETERMINATE: {clipping.get('reason')}")
    lines.append(f"- Domain: {clipping.get('domain')}")

    lines.extend(["", "## Gates", ""])
    lines.extend(format_gate_outcome(gate) for gate in gates)

    lines.extend(["", "## Frozen ROI measurements", ""])
    if not report["measurements"]:
        lines.append("- Absent. Frozen source ROI masks were not supplied.")
    for measurement in report["measurements"]:
        lines.append(
            f"- Shot {measurement['shot']}, frames {measurement['frames']}: "
            f"luma p1={measurement['luma_percentiles']['p1']:.3f}, "
            f"p50={measurement['luma_percentiles']['p50']:.3f}, "
            f"p99={measurement['luma_percentiles']['p99']:.3f}"
        )
        colorimetry = measurement["colorimetry"]
        if colorimetry["available"]:
            lines.append(
                f"  CCT={colorimetry['cct_kelvin']:.1f} K, "
                f"Duv={colorimetry['duv']:.6f}, "
                f"delta E 2000={colorimetry['delta_e2000']:.4f}"
            )
        else:
            lines.append(f"  Colorimetry absent: {colorimetry['reason']}")
        for mask_name in ("neutral", "skin"):
            mask = measurement[mask_name]
            if mask is None:
                continue
            if mask["multimodal"]:
                lines.append(
                    f"  {mask_name} multimodal on: "
                    + ", ".join(mask["multimodal_axes"])
                )
            for region_index, region in enumerate(mask["regions"]):
                lines.append(
                    f"  {mask_name} region {region_index}: "
                    f"median_rgb={region['median_rgb']}, px={region['px']}, "
                    f"bbox={region['bbox']}"
                )
    if run["error"]:
        lines.extend(["", "## Error", "", str(run["error"])])
    return "\n".join(lines) + "\n"
