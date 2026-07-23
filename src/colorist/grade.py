# SPDX-License-Identifier: MIT
"""Per-shot grading, FFV1 concatenation, and one explicit delivery encode.

Each authoritative frame interval is rendered independently to a gbrp16le
FFV1 mezzanine.  The concat demuxer joins those RGB mezzanines without another
pixel conversion, then the sole RGB-to-delivery conversion happens in one
profile-driven encode.  This deliberately has no sendcmd path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
import statistics
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from colorist.corrections import Correction, compile_shot_lut
from colorist.cuts import Shot, frames_to_pts, read_cutlist
from colorist.lut import write_cube
from colorist.render import ConvertParams, render_segment
from colorist.tools import resolve_tool

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - normal dependency is installed
    yaml = None  # type: ignore[assignment]


FFMPEG = resolve_tool("ffmpeg")
FFPROBE = resolve_tool("ffprobe")


class GradeError(RuntimeError):
    """Base class for an unrecoverable grade operation error."""


class RefuseOverwriteError(GradeError):
    """Raised before an input or an existing delivery output could be replaced."""


class VariableFrameRateError(GradeError):
    """Raised because v1 segment concatenation deliberately accepts CFR only."""


class CutListSourceMismatchError(GradeError):
    """Raised when the cut list does not partition every source frame exactly once."""


class MissingCorrectionError(GradeError):
    """Raised when no correction is supplied for an authoritative shot."""


class DeliveryProfileError(GradeError):
    """Raised when a delivery profile cannot be parsed or is unsupported."""


class ConcatError(GradeError):
    """Raised when FFmpeg cannot losslessly concatenate the shot mezzanines."""


class DeliveryEncodeError(GradeError):
    """Raised when the single profile-driven delivery encode fails."""


class SourceEncodingError(GradeError):
    """Raised when range or matrix evidence is insufficient for decoding."""


class SourceEncodingConflictError(SourceEncodingError):
    """Raised when a user declaration conflicts with source metadata."""


@dataclass(frozen=True)
class DeliveryProfile:
    """The validated delivery settings that become explicit FFmpeg arguments."""

    container: str
    vcodec: str
    pix_fmt: str
    range: str
    color_primaries: str
    color_trc: str
    colorspace: str
    acodec: str
    naming_template: str
    crf: int | float | None = None
    maxrate: str | None = None
    bitrate: str | None = None
    profile: int | str | None = None
    movflags: str | None = None

    @property
    def ffmpeg_range(self) -> str:
        return {"full": "pc", "limited": "tv"}[self.range]


def grade_file(
    src: Path,
    cutlist: str | Path | list[Shot],
    corrections: dict[int, Correction],
    look: Any,
    curve_gamut: str | None,
    delivery_profile: Any,
    workdir: Path,
    input_params: ConvertParams | None = None,
    confirm_metadata_override: bool = False,
) -> Path:
    """Grade every authoritative shot and write one named delivery file.

    ``cutlist`` may be a validated CSV path or pre-read ``Shot`` values.  A
    v1 delivery refuses variable-frame-rate source media, mismatched frame
    partitioning, an absent per-shot correction, the source as destination, or
    an already-existing destination.  A failed run intentionally leaves its
    uniquely named workspace in place with every mezzanine for diagnosis.
    """
    source = Path(src)
    profile = _load_delivery_profile(delivery_profile)
    shots = (
        read_cutlist(Path(cutlist))
        if isinstance(cutlist, (str, Path))
        else list(cutlist)
    )
    frame_pts = frames_to_pts(source)
    _require_cfr(frame_pts)
    _validate_shot_partition(shots, len(frame_pts))

    destination_root = Path(workdir)
    destination = destination_root / _output_name(source, profile)
    _refuse_overwrite(source, destination)
    destination_root.mkdir(parents=True, exist_ok=True)

    # A unique workspace prevents render_segment's required -y flag from ever
    # replacing a diagnostic artifact left by a previous failed run.
    run_dir = Path(
        tempfile.mkdtemp(prefix=f".{source.stem}.grade-", dir=destination_root)
    )
    mezzanines: list[Path] = []
    try:
        in_params = _source_convert_params(
            source,
            input_params,
            confirm_metadata_override=confirm_metadata_override,
            curve_gamut=curve_gamut,
        )
        out_params = ConvertParams(
            range=profile.range,
            matrix=profile.colorspace,
            transfer=profile.color_trc,
            primaries=profile.color_primaries,
        )
        for shot_index, shot in enumerate(shots):
            try:
                correction = corrections[shot_index]
            except KeyError as error:
                raise MissingCorrectionError(
                    f"no correction supplied for shot {shot_index} "
                    f"[{shot.start_frame}, {shot.end_frame})"
                ) from error
            cube = run_dir / f"shot-{shot_index:04d}.cube"
            write_cube(
                cube,
                compile_shot_lut(correction, look=look, curve_gamut=curve_gamut),
                title=f"colorist shot {shot_index}",
            )
            mezzanine = run_dir / f"shot-{shot_index:04d}.mkv"
            render_segment(
                source,
                mezzanine,
                trim=(shot.start_frame, shot.end_frame),
                idt_cube=None,
                corr_cube=cube,
                in_params=in_params,
                out_params=out_params,
            )
            mezzanines.append(mezzanine)

        concat_list = run_dir / "segments.ffconcat"
        _write_concat_list(concat_list, mezzanines)
        concatenated = run_dir / "concatenated-mezzanine.mkv"
        _concat_mezzanines(concat_list, concatenated)

        encoded = run_dir / _output_name(source, profile)
        _encode_delivery(concatenated, source, encoded, profile)
        finalized = _finalize_delivery_tags(encoded, profile)
        os.replace(finalized, destination)
    except Exception:
        # This is deliberately broad: FFmpeg, LUT rendering, and filesystem
        # exceptions all preserve the run directory and FFV1 diagnostics.
        raise
    else:
        _cleanup_success(run_dir)
    return destination


def _load_delivery_profile(
    profile_source: Any,
) -> DeliveryProfile:
    if isinstance(profile_source, Mapping):
        raw: object = dict(profile_source)
    else:
        path = (
            Path(profile_source)
            if isinstance(profile_source, (str, Path))
            else profile_source
        )
        try:
            text = path.read_text()
        except OSError as error:
            raise DeliveryProfileError(f"cannot read delivery profile: {path}") from error
        raw = yaml.safe_load(text) if yaml is not None else _load_flat_yaml(text)
    if not isinstance(raw, Mapping):
        raise DeliveryProfileError("delivery profile root must be a mapping")

    required_text = (
        "container",
        "vcodec",
        "pix_fmt",
        "range",
        "color_primaries",
        "color_trc",
        "colorspace",
        "acodec",
        "naming_template",
    )
    missing = [field for field in required_text if field not in raw]
    if missing:
        raise DeliveryProfileError(f"delivery profile missing fields: {missing}")
    if any(not isinstance(raw[field], str) or not raw[field] for field in required_text):
        raise DeliveryProfileError("delivery profile has an empty or non-string text field")
    if raw["range"] not in {"full", "limited"}:
        raise DeliveryProfileError("delivery profile range must be full or limited")
    if raw["acodec"] != "copy":
        raise DeliveryProfileError("v1 delivery profiles require acodec: copy")
    if raw["naming_template"] != "<stem>.graded.<ext>":
        raise DeliveryProfileError(
            "v1 delivery naming_template must be <stem>.graded.<ext>"
        )
    if raw["container"] == "mp4" and not isinstance(raw.get("movflags"), str):
        raise DeliveryProfileError("mp4 delivery profile requires movflags")
    if "crf" in raw and not isinstance(raw["crf"], (int, float)):
        raise DeliveryProfileError("crf must be numeric")
    for field in ("maxrate", "bitrate"):
        if field in raw and not isinstance(raw[field], (str, int, float)):
            raise DeliveryProfileError(f"{field} must be a string or number")
    if "profile" in raw and not isinstance(raw["profile"], (str, int)):
        raise DeliveryProfileError("profile must be a string or integer")
    if raw["vcodec"] == "libx264" and not (
        "crf" in raw or "bitrate" in raw
    ):
        raise DeliveryProfileError("libx264 delivery profile requires crf or bitrate")
    supported_pairs = {("mp4", "libx264"), ("mov", "prores_ks")}
    if (raw["container"], raw["vcodec"]) not in supported_pairs:
        raise DeliveryProfileError(
            "unsupported v1 delivery container/codec combination: "
            f"{raw['container']}/{raw['vcodec']}"
        )

    return DeliveryProfile(
        container=raw["container"],
        vcodec=raw["vcodec"],
        pix_fmt=raw["pix_fmt"],
        range=raw["range"],
        color_primaries=raw["color_primaries"],
        color_trc=raw["color_trc"],
        colorspace=raw["colorspace"],
        acodec=raw["acodec"],
        naming_template=raw["naming_template"],
        crf=raw.get("crf"),
        maxrate=None if raw.get("maxrate") is None else str(raw["maxrate"]),
        bitrate=None if raw.get("bitrate") is None else str(raw["bitrate"]),
        profile=raw.get("profile"),
        movflags=raw.get("movflags"),
    )


def _load_flat_yaml(text: str) -> dict[str, object]:
    """Read the tiny flat YAML subset used by delivery profiles offline."""
    values: dict[str, object] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise DeliveryProfileError(f"invalid YAML at line {line_number}")
        key, value = (item.strip() for item in line.split(":", maxsplit=1))
        if not key or not value:
            raise DeliveryProfileError(f"invalid YAML at line {line_number}")
        unquoted = value.strip("\"'")
        try:
            values[key] = float(unquoted) if "." in unquoted else int(unquoted)
        except ValueError:
            values[key] = unquoted
    return values


def _require_cfr(pts: list[float]) -> None:
    if len(pts) < 2:
        return
    intervals = [right - left for left, right in zip(pts, pts[1:])]
    if any(interval <= 0.0 for interval in intervals):
        raise VariableFrameRateError("v1 grade requires monotonically increasing CFR PTS")
    # Compare against the MEDIAN, not intervals[0]: one odd first interval
    # should not condemn the whole stream.
    #
    # The tolerance has to survive timebase quantization. Presentation stamps are
    # integer ticks, and a rate like 24 is not exactly representable, so a
    # genuinely constant 24fps stream reports intervals that alternate between
    # 0.041666 and 0.041667: a 1 microsecond step, 2.4e-5 relative. The former
    # rel_tol of 1e-6 was 24 times tighter than that and refused ordinary CFR
    # footage (observed 2026-07-23 on a 121 frame 24fps H.264 file). Genuine VFR
    # is not a near miss: the project's own VFR fixture spans a 7x range between
    # its shortest and longest interval, so 1e-3 separates the two cleanly while
    # sitting 40 times above the quantization noise.
    reference = statistics.median(intervals)
    if not all(
        math.isclose(interval, reference, rel_tol=1e-3, abs_tol=1e-9)
        for interval in intervals
    ):
        raise VariableFrameRateError("v1 grade requires CFR input; variable frame PTS refused")


def _validate_shot_partition(shots: list[Shot], frame_count: int) -> None:
    if not shots:
        raise CutListSourceMismatchError("cut list has no shots")
    if shots[0].start_frame != 0:
        raise CutListSourceMismatchError("cut list must start at source frame zero")
    prior_end = 0
    for index, shot in enumerate(shots):
        if shot.start_frame != prior_end or shot.end_frame <= shot.start_frame:
            raise CutListSourceMismatchError(f"cut list shot {index} is not contiguous")
        prior_end = shot.end_frame
    if prior_end != frame_count:
        raise CutListSourceMismatchError(
            f"cut list ends at frame {prior_end}, source has {frame_count} frames"
        )


def _output_name(source: Path, profile: DeliveryProfile) -> str:
    return profile.naming_template.replace("<stem>", source.stem).replace(
        "<ext>", profile.container
    )


def _refuse_overwrite(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise RefuseOverwriteError(f"refusing to overwrite input: {source}")
    if destination.exists():
        raise RefuseOverwriteError(f"output exists; refusing to overwrite: {destination}")


#: Concrete display transfer/primaries tags that contradict a camera-log
#: declaration. Genuine log carries an unspecified transfer, so any of these
#: alongside an --encoding is a conflict the user must confirm.
_DISPLAY_TRANSFER_TAGS = frozenset(
    {"bt709", "smpte170m", "bt470bg", "gamma22", "gamma28",
     "iec61966-2-1", "srgb", "smpte2084", "arib-std-b67"}
)
_DISPLAY_PRIMARY_TAGS = frozenset({"bt709", "smpte170m", "bt470bg", "smpte432", "bt2020"})


def _source_convert_params(
    source: Path,
    declared: ConvertParams | None = None,
    *,
    confirm_metadata_override: bool = False,
    curve_gamut: str | None = None,
) -> ConvertParams:
    """Resolve input conversion without silently choosing range or matrix.

    Known metadata is used when no declaration is supplied. A declaration
    fills absent range or matrix evidence. Any conflict is raised unless the
    caller explicitly confirms the override, in which case the declaration
    wins and becomes the conversion used by decoding and rendering. A camera-log
    ``curve_gamut`` declared against a concrete display transfer or primaries tag
    is itself a conflict, since genuine log is not tagged with a display curve.
    """
    if declared is not None and not isinstance(declared, ConvertParams):
        raise TypeError("declared must be a ConvertParams instance or None")
    probe = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=pix_fmt,color_range,color_space,color_transfer,color_primaries",
            "-of",
            "default=noprint_wrappers=1:nokey=0",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = dict(
        line.split("=", maxsplit=1)
        for line in probe.stdout.splitlines()
        if "=" in line
    )
    pix_fmt = evidence.get("pix_fmt", "").lower()
    range_tag = evidence.get("color_range", "").lower()
    if range_tag in {"pc", "jpeg", "full"}:
        probed_range: str | None = "full"
    elif range_tag in {"tv", "mpeg", "limited"}:
        probed_range = "limited"
    elif pix_fmt.startswith(("gbr", "rgb", "bgr", "rgba", "bgra", "yuvj")):
        probed_range = "full"
    else:
        probed_range = None

    matrix_tag = evidence.get("color_space", "").lower()
    if matrix_tag not in {"", "unknown", "unspecified", "gbr", "rgb"}:
        probed_matrix: str | None = matrix_tag
    elif pix_fmt.startswith(("gbr", "rgb", "bgr", "rgba", "bgra")):
        # RGB inputs have no YUV decode matrix. BT.709 names the canonical RGB
        # output expected by this SDR pipeline rather than guessing a YUV edge.
        probed_matrix = "bt709"
    else:
        probed_matrix = None

    missing = [
        name
        for name, value in (("range", probed_range), ("matrix", probed_matrix))
        if value is None and declared is None
    ]
    if missing:
        raise SourceEncodingError(
            "source metadata does not identify input "
            f"{', '.join(missing)}; provide an explicit ConvertParams declaration"
        )

    transfer_tag = evidence.get("color_transfer", "").lower()
    probed_transfer = (
        None
        if transfer_tag in {"", "unknown", "unspecified"}
        else transfer_tag
    )
    primaries_tag = evidence.get("color_primaries", "").lower()
    probed_primaries = (
        None
        if primaries_tag in {"", "unknown", "unspecified"}
        else primaries_tag
    )

    probed = {
        "range": probed_range,
        "matrix": probed_matrix,
        "transfer": probed_transfer,
        "primaries": probed_primaries,
    }
    conflicts: list[str] = []
    if declared is not None:
        for name, value in probed.items():
            declared_value = getattr(declared, name)
            if value is not None and value != declared_value:
                conflicts.append(f"{name}: metadata={value}, declared={declared_value}")
    if curve_gamut is not None:
        if probed_transfer in _DISPLAY_TRANSFER_TAGS:
            conflicts.append(
                f"encoding: declared log {curve_gamut}, source transfer tag {probed_transfer}"
            )
        if probed_primaries in _DISPLAY_PRIMARY_TAGS:
            conflicts.append(
                f"encoding: declared log {curve_gamut}, source primaries tag {probed_primaries}"
            )
    if conflicts and not confirm_metadata_override:
        raise SourceEncodingConflictError(
            "input declaration conflicts with source metadata: "
            + "; ".join(conflicts)
            + "; confirm_metadata_override=True is required to use the declaration"
        )

    resolved = declared if declared is not None else ConvertParams(
        range=probed_range,
        matrix=probed_matrix,
        transfer=probed_transfer or "bt709",
        primaries=probed_primaries or "bt709",
    )
    if curve_gamut is not None and resolved.range == "limited":
        # Camera log is recorded data-level (full range); its manufacturer curve
        # is defined on full-swing code. A limited-range tag on log input is
        # ambiguous (mislabeled data-level, or a rare manufacturer-specific
        # legal-range re-encode) and cannot be decoded safely, so it is refused
        # by name rather than silently misdecoded. Re-tag the file, or declare
        # --input-range full with --confirm-metadata-override if the stored
        # codes are genuinely data-level.
        raise SourceEncodingError(
            f"camera log {curve_gamut} must be full-range (data-level); a "
            "limited-range tag on log input is refused. Re-tag the file, or "
            "declare full range explicitly if the codes are data-level."
        )
    return resolved


def _write_concat_list(path: Path, mezzanines: list[Path]) -> None:
    if not mezzanines:
        raise ConcatError("cannot concatenate an empty mezzanine list")
    lines = ["ffconcat version 1.0"]
    for mezzanine in mezzanines:
        quoted = mezzanine.resolve().as_posix().replace("'", r"'\\''")
        lines.append(f"file '{quoted}'")
    path.write_text("\n".join(lines) + "\n")


def _concat_mezzanines(concat_list: Path, destination: Path) -> None:
    result = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-an",
            str(destination),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ConcatError(f"mezzanine concat failed: {result.stderr[-2000:]}")


def _encode_delivery(
    mezzanine: Path, source: Path, destination: Path, profile: DeliveryProfile
) -> None:
    vf = (
        "scale=in_range=pc:out_range="
        f"{profile.ffmpeg_range}:in_color_matrix={profile.colorspace}:"
        f"out_color_matrix={profile.colorspace},format={profile.pix_fmt}"
    )
    args = [
        FFMPEG,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        str(mezzanine),
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-map_metadata",
        "1",
        "-vf",
        vf,
        "-c:v",
        profile.vcodec,
        "-pix_fmt",
        profile.pix_fmt,
        "-color_range",
        profile.ffmpeg_range,
        "-colorspace",
        profile.colorspace,
        "-color_primaries",
        profile.color_primaries,
        "-color_trc",
        profile.color_trc,
    ]
    if profile.crf is not None:
        args += ["-crf", str(profile.crf)]
    if profile.maxrate is not None:
        args += ["-maxrate", profile.maxrate]
    if profile.bitrate is not None:
        args += ["-b:v", profile.bitrate]
    if profile.profile is not None:
        args += ["-profile:v", str(profile.profile)]
    if profile.vcodec == "libx264":
        # libx264 otherwise omits default-valued primaries and transfer from
        # the H.264 VUI, which makes ffprobe report them as unknown even though
        # the generic output options were supplied.
        fullrange = "on" if profile.range == "full" else "off"
        args += [
            "-x264-params",
            "colorprim="
            f"{profile.color_primaries}:transfer={profile.color_trc}:"
            f"colormatrix={profile.colorspace}:fullrange={fullrange}",
        ]
    if profile.movflags is not None:
        args += ["-movflags", profile.movflags]
    args += ["-c:a", profile.acodec, "-f", profile.container, str(destination)]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise DeliveryEncodeError(f"delivery encode failed: {result.stderr[-2000:]}")


def _finalize_delivery_tags(encoded: Path, profile: DeliveryProfile) -> Path:
    """Repair the MOV colour atom that FFmpeg 8.1's prores_ks leaves unknown.

    ``prores_ks`` receives the profile's explicit colour options during the
    delivery encode but writes unknown primaries and transfer in MOV's ``nclc``
    atom.  A stream-copy remux does not encode pixels again, and lets the MOV
    muxer write the already-declared four profile tags correctly.
    """
    if (profile.container, profile.vcodec) != ("mov", "prores_ks"):
        return encoded
    tagged = encoded.with_name(f"{encoded.stem}.tagged{encoded.suffix}")
    result = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(encoded),
            "-map",
            "0",
            "-c",
            "copy",
            "-color_range",
            profile.ffmpeg_range,
            "-colorspace",
            profile.colorspace,
            "-color_primaries",
            profile.color_primaries,
            "-color_trc",
            profile.color_trc,
            "-movflags",
            "+write_colr",
            "-f",
            profile.container,
            str(tagged),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DeliveryEncodeError(
            f"delivery tag remux failed: {result.stderr[-2000:]}"
        )
    return tagged


def _cleanup_success(run_dir: Path) -> None:
    """Remove all temporary LUTs, list files, and RGB mezzanines after success."""
    for path in run_dir.iterdir():
        if path.is_file():
            path.unlink()
    run_dir.rmdir()
