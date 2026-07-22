# SPDX-License-Identifier: MIT
"""Evidence-oriented per-shot image measurement.

Mask selection, frozen ROI medians, skin statistics, and reported luma use one
canonical measurement space: full-range Rec.709 display-code RGB floats in the
0 to 1 range. Luma percentiles are reported in the equivalent 8-bit full-range
scale. Display-referred sources enter that space through explicit range and
matrix decoding. Log sources are decoded, converted to scene-linear Rec.709
with their declared camera curve and gamut, then BT.1886 encoded back to
Rec.709 display code. This keeps the calibrated mask thresholds and 8-bit gate
signals encoding-independent.

Exposure solving uses a separate domain. ``workflow._working_luma_p50``
converts decoded source code to scene-linear Rec.709/D65 and computes luma
there. It does not use the display-code luma percentiles reported here.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from typing import Final
import zlib

import numpy as np
from scipy import ndimage

from colorist.corrections import bt1886_encode
from colorist.idt import camera_to_working
from colorist.render import ConvertParams, read_frame_rgb
from colorist.tools import resolve_tool


#: Largest allowed max(R, G, B) - min(R, G, B) for a neutral candidate.
NEUTRAL_CHANNEL_SPREAD_MAX: Final[float] = 28 / 255
#: Inclusive lower Rec.709 luma bound for a neutral candidate.
NEUTRAL_LUMA_MIN: Final[float] = 0.25
#: Inclusive upper Rec.709 luma bound for a neutral candidate.
NEUTRAL_LUMA_MAX: Final[float] = 0.90

#: Inclusive lower HSV hue, in degrees, for a skin candidate.
SKIN_HUE_MIN_DEGREES: Final[float] = 5.0
#: Inclusive upper HSV hue, in degrees, for a skin candidate.
SKIN_HUE_MAX_DEGREES: Final[float] = 45.0
#: Inclusive lower HSV saturation for a skin candidate.
SKIN_SATURATION_MIN: Final[float] = 0.10
#: Inclusive upper HSV saturation for a skin candidate.
SKIN_SATURATION_MAX: Final[float] = 0.60
#: Inclusive lower HSV value for a skin candidate.
SKIN_VALUE_MIN: Final[float] = 0.25
#: Inclusive upper HSV value for a skin candidate.
SKIN_VALUE_MAX: Final[float] = 0.95

#: R-B disagreement in Rec.709 display code that makes regions multimodal.
MULTIMODAL_R_MINUS_B_SPREAD: Final[float] = 6 / 255
#: Green-axis disagreement in Rec.709 display code that makes regions multimodal.
#: Six code values matches the existing R-B spread. This avoids inventing an
#: unvalidated axis preference while keeping both axes in the same domain.
MULTIMODAL_GREEN_BALANCE_SPREAD: Final[float] = 6 / 255

#: Bump whenever mask selection or connected-region semantics change.
MASK_ALGORITHM_VERSION: Final[str] = "measurement-v3"

#: Fixed square side, in pixels, for each contact-sheet region tile.
MASK_SHEET_TILE_SIZE: Final[int] = 128
#: Fixed number of columns used by a contact sheet.
MASK_SHEET_COLUMNS: Final[int] = 2

_REC709_LUMA = np.array((0.2126, 0.7152, 0.0722), dtype=np.float64)
FFPROBE = resolve_tool("ffprobe")


class FrozenMaskIdentityError(ValueError):
    """Raised when cached ROI evidence does not match its measurement input."""


@dataclass(frozen=True)
class RegionStat:
    """One connected frozen-mask region.

    ``bbox`` is ``(x0, y0, x1, y1)`` with exclusive right and lower edges.
    ``px`` counts pixels in this region's frozen mask, not frames pooled.
    ``median_rgb`` feeds the white-balance solver. ``r_minus_b_median`` and
    ``green_balance_median`` are the gate statistics: the median over the
    region's pixels of the per-pixel ``R - B`` and ``G - (R + B) / 2``, in the
    0 to 1 display-code domain. These are NOT ``median(R) - median(B)``: a
    region with symmetric warm and cool casts has equal channel medians but a
    large per-pixel spread, and only the per-pixel statistic catches it.
    """

    median_rgb: tuple[float, float, float]
    px: int
    bbox: tuple[int, int, int, int]
    r_minus_b_median: float
    green_balance_median: float


@dataclass(frozen=True)
class MaskStat:
    """Measurement evidence for one named mask class.

    ``saturation_median`` is the median over the mask's pixels of the per-pixel
    HSV saturation, the declared skin statistic. It is NOT the saturation of the
    pooled median RGB.
    """

    median_rgb: tuple[float, float, float] | None
    sample_px: int
    frames_used: int
    frozen_mask_path: Path
    regions: list[RegionStat]
    multimodal: bool
    multimodal_axes: tuple[str, ...]
    saturation_median: float | None


@dataclass(frozen=True)
class ShotMeasurement:
    """Luma and ROI measurements for a set of decoded shot frames."""

    luma_percentiles: dict[str, float]
    neutral: MaskStat | None
    skin: MaskStat | None
    temporal_coverage_sufficient: bool


@dataclass(frozen=True)
class _Component:
    """Internal connected-component metadata for a boolean mask."""

    label: int
    px: int
    bbox: tuple[int, int, int, int]


def sample_positions(n_frames: int) -> list[int]:
    """Choose frames at 25, 50, and 75 percent, preserving short shots.

    A shot with fewer than three frames has insufficient temporal coverage, so
    every frame is returned for the caller to mark as indeterminate if needed.
    """
    if n_frames < 0:
        raise ValueError("n_frames must be non-negative")
    if n_frames < 3:
        return list(range(n_frames))
    return [n_frames // 4, n_frames // 2, (3 * n_frames) // 4]


def measure_shot(
    src: Path,
    frames: list[int],
    in_params: ConvertParams,
    curve_gamut: str | None,
    *,
    artifact_dir: Path,
    shot_frame_count: int | None = None,
) -> ShotMeasurement:
    """Measure display-code luma plus frozen neutral and skin ROIs."""
    if not isinstance(in_params, ConvertParams):
        raise TypeError("in_params must be a ConvertParams instance")
    if not frames:
        raise ValueError("measure_shot requires at least one frame")
    if any(frame < 0 for frame in frames):
        raise ValueError("frame indices must be non-negative")
    if shot_frame_count is not None and shot_frame_count < 1:
        raise ValueError("shot_frame_count must be positive when supplied")

    src = Path(src)
    artifact_dir = Path(artifact_dir)
    decoded = [
        _to_measurement_rgb(read_frame_rgb(src, frame, in_params), curve_gamut)
        for frame in frames
    ]
    shape = decoded[0].shape[:2]
    if any(frame.shape[:2] != shape for frame in decoded):
        raise ValueError("all measured frames must have the same dimensions")
    identity = _mask_cache_identity(
        src, frames, in_params, curve_gamut, shape
    )

    luma = np.concatenate([(frame @ _REC709_LUMA).ravel() for frame in decoded])
    luma_percentiles = {
        "p1": float(np.percentile(luma, 1) * 255),
        "p50": float(np.percentile(luma, 50) * 255),
        "p99": float(np.percentile(luma, 99) * 255),
    }
    neutral = _measure_mask(
        decoded,
        _neutral_mask,
        _frozen_mask_path(
            src, frames, "neutral", in_params, curve_gamut, artifact_dir
        ),
        {**identity, "mask_type": "neutral"},
        refuse_multimodal=True,
    )
    skin = _measure_mask(
        decoded,
        _skin_mask,
        _frozen_mask_path(
            src, frames, "skin", in_params, curve_gamut, artifact_dir
        ),
        {**identity, "mask_type": "skin"},
        refuse_multimodal=False,
    )
    return ShotMeasurement(
        luma_percentiles=luma_percentiles,
        neutral=neutral,
        skin=skin,
        temporal_coverage_sufficient=(
            shot_frame_count is None or shot_frame_count >= 3
        ),
    )


def write_mask_sheet(
    src: Path,
    frame: int,
    mask: np.ndarray,
    out_png: Path,
    in_params: ConvertParams,
    curve_gamut: str | None,
) -> None:
    """Write a two-column PNG contact sheet of the top five masked regions.

    Each 128 by 128 tile is a nearest-neighbour rendering of its component's
    bounding box. Pixels outside that component are black, making the exact
    sampled area visible during human verification.
    """
    rgb = _to_measurement_rgb(
        read_frame_rgb(Path(src), frame, in_params),
        curve_gamut,
    )
    boolean_mask = np.asarray(mask, dtype=bool)
    if boolean_mask.ndim != 2 or boolean_mask.shape != rgb.shape[:2]:
        raise ValueError("mask must be a 2D array matching the decoded frame")

    labels, components = _components(boolean_mask)
    rows = max(1, (len(components) + MASK_SHEET_COLUMNS - 1) // MASK_SHEET_COLUMNS)
    sheet = np.zeros(
        (rows * MASK_SHEET_TILE_SIZE, MASK_SHEET_COLUMNS * MASK_SHEET_TILE_SIZE, 3),
        dtype=np.uint8,
    )
    rgb_u8 = np.clip(np.rint(rgb * 255), 0, 255).astype(np.uint8)

    for index, component in enumerate(components):
        x0, y0, x1, y1 = component.bbox
        crop = rgb_u8[y0:y1, x0:x1].copy()
        component_mask = labels[y0:y1, x0:x1] == component.label
        crop[~component_mask] = 0
        tile = _resize_nearest(crop, MASK_SHEET_TILE_SIZE, MASK_SHEET_TILE_SIZE)
        row, column = divmod(index, MASK_SHEET_COLUMNS)
        y_start = row * MASK_SHEET_TILE_SIZE
        x_start = column * MASK_SHEET_TILE_SIZE
        sheet[
            y_start : y_start + MASK_SHEET_TILE_SIZE,
            x_start : x_start + MASK_SHEET_TILE_SIZE,
        ] = tile

    _write_png_rgb(Path(out_png), sheet)


def _measure_mask(
    frames: list[np.ndarray],
    candidate_mask,
    frozen_mask_path: Path,
    cache_identity: dict[str, object],
    *,
    refuse_multimodal: bool,
) -> MaskStat | None:
    """Load or create a mask, then measure all supplied frames through it."""
    shape = frames[0].shape[:2]
    if frozen_mask_path.exists():
        mask = _load_frozen_mask(frozen_mask_path, shape, cache_identity)
    else:
        mask = next(
            (mask for frame in frames if (mask := candidate_mask(frame)).any()),
            None,
        )
        if mask is None:
            return None
        _save_frozen_mask(frozen_mask_path, mask, cache_identity)

    labels, components = _components(mask)
    if not components:
        return None
    sampled = np.concatenate([frame[mask] for frame in frames], axis=0)
    regions = [_region_stat(frames, labels, component) for component in components]
    multimodal_axes: list[str] = []
    if refuse_multimodal:
        # Disagreement between regions is judged on the signed per-region median
        # of each axis, so a warm region and a cool region cannot pool to neutral.
        r_minus_b = [region.median_rgb[0] - region.median_rgb[2] for region in regions]
        green_balance = [
            region.median_rgb[1]
            - ((region.median_rgb[0] + region.median_rgb[2]) / 2)
            for region in regions
        ]
        if max(r_minus_b) - min(r_minus_b) > MULTIMODAL_R_MINUS_B_SPREAD:
            multimodal_axes.append("r_minus_b")
        if (
            max(green_balance) - min(green_balance)
            > MULTIMODAL_GREEN_BALANCE_SPREAD
        ):
            multimodal_axes.append("green_balance")
    multimodal = bool(multimodal_axes)
    pooled = None if multimodal else _as_rgb_tuple(np.median(sampled, axis=0))
    _, saturation, _ = _rgb_to_hsv(sampled)
    return MaskStat(
        median_rgb=pooled,
        sample_px=int(mask.sum()) * len(frames),
        frames_used=len(frames),
        frozen_mask_path=frozen_mask_path,
        regions=regions,
        multimodal=multimodal,
        multimodal_axes=tuple(multimodal_axes),
        saturation_median=float(np.median(saturation)),
    )


def _neutral_mask(rgb: np.ndarray) -> np.ndarray:
    """Return neutral candidates using Rec.709 display-code constants."""
    channel_spread = rgb.max(axis=-1) - rgb.min(axis=-1)
    luma = rgb @ _REC709_LUMA
    return (
        (channel_spread < NEUTRAL_CHANNEL_SPREAD_MAX)
        & (luma >= NEUTRAL_LUMA_MIN)
        & (luma <= NEUTRAL_LUMA_MAX)
    )


def _skin_mask(rgb: np.ndarray) -> np.ndarray:
    """Return skin candidates using HSV criteria in Rec.709 display code."""
    hue, saturation, value = _rgb_to_hsv(rgb)
    return (
        (hue >= SKIN_HUE_MIN_DEGREES)
        & (hue <= SKIN_HUE_MAX_DEGREES)
        & (saturation >= SKIN_SATURATION_MIN)
        & (saturation <= SKIN_SATURATION_MAX)
        & (value >= SKIN_VALUE_MIN)
        & (value <= SKIN_VALUE_MAX)
    )


def _rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert an RGB float image to hue in degrees, saturation, and value."""
    red, green, blue = np.moveaxis(rgb, -1, 0)
    maximum = rgb.max(axis=-1)
    minimum = rgb.min(axis=-1)
    delta = maximum - minimum
    hue = np.zeros_like(maximum)
    nonzero = delta > 0
    red_max = nonzero & (maximum == red)
    green_max = nonzero & (maximum == green)
    blue_max = nonzero & (maximum == blue)
    hue[red_max] = ((green[red_max] - blue[red_max]) / delta[red_max]) % 6
    hue[green_max] = ((blue[green_max] - red[green_max]) / delta[green_max]) + 2
    hue[blue_max] = ((red[blue_max] - green[blue_max]) / delta[blue_max]) + 4
    hue *= 60
    saturation = np.divide(delta, maximum, out=np.zeros_like(delta), where=maximum > 0)
    return hue, saturation, maximum


def _to_measurement_rgb(
    decoded_rgb: np.ndarray, curve_gamut: str | None
) -> np.ndarray:
    """Normalize decoded RGB to the canonical Rec.709 display-code domain."""
    if curve_gamut is None:
        return np.asarray(decoded_rgb, dtype=np.float64)
    return bt1886_encode(camera_to_working(curve_gamut, decoded_rgb))


def _frozen_mask_path(
    src: Path,
    frames: list[int],
    name: str,
    in_params: ConvertParams,
    curve_gamut: str | None,
    artifact_dir: Path,
) -> Path:
    """Return a transform-specific path for one frozen source mask."""
    transform = f"{in_params.range}-{in_params.matrix}-{curve_gamut or 'display'}"
    safe_transform = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in transform
    )
    return Path(artifact_dir) / (
        f"{src.stem}.frames-{frames[0]}-{frames[-1]}.measurement-v2-"
        f"{safe_transform}.{name}.mask.npz"
    )


def _mask_cache_identity(
    src: Path,
    frames: list[int],
    in_params: ConvertParams,
    curve_gamut: str | None,
    shape: tuple[int, int],
) -> dict[str, object]:
    """Return every input field that makes a frozen mask reusable."""
    height, width = shape
    return {
        "source_digest": _source_digest(src),
        "stream_identity": _stream_identity(src),
        "declared_encoding": curve_gamut or "display-referred",
        "convert_params": {
            "range": in_params.range,
            "matrix": in_params.matrix,
            "transfer": in_params.transfer,
            "primaries": in_params.primaries,
        },
        "frames": list(frames),
        "mask_algorithm_version": MASK_ALGORITHM_VERSION,
        "dimensions": {"width": width, "height": height},
    }


def _source_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _stream_identity(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=index,codec_name,codec_tag_string,profile,level,width,height,"
            "pix_fmt,time_base,start_time,duration,nb_frames,avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        stream = json.loads(result.stdout)["streams"][0]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"ffprobe found no video stream for mask identity: {path}") from error
    if not isinstance(stream, dict):
        raise ValueError(f"ffprobe returned an invalid video stream for mask identity: {path}")
    return stream


def _save_frozen_mask(
    path: Path, mask: np.ndarray, identity: dict[str, object]
) -> None:
    """Atomically persist a boolean ROI mask as an NPZ file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(
            handle,
            mask=np.asarray(mask, dtype=bool),
            identity_json=np.asarray(json.dumps(identity, sort_keys=True)),
        )
    temporary.replace(path)


def _load_frozen_mask(
    path: Path,
    shape: tuple[int, int],
    expected_identity: dict[str, object],
) -> np.ndarray:
    """Load one persisted ROI and loudly reject any identity mismatch."""
    with np.load(path, allow_pickle=False) as archive:
        if "mask" not in archive:
            raise ValueError(f"frozen mask {path} does not contain a mask array")
        if "identity_json" not in archive:
            raise FrozenMaskIdentityError(
                f"frozen mask cache identity missing for {path}; remove the stale cache"
            )
        mask = np.asarray(archive["mask"], dtype=bool)
        try:
            identity = json.loads(str(archive["identity_json"].item()))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise FrozenMaskIdentityError(
                f"frozen mask cache identity is invalid for {path}; remove the stale cache"
            ) from error
    if not isinstance(identity, dict):
        raise FrozenMaskIdentityError(
            f"frozen mask cache identity is invalid for {path}; remove the stale cache"
        )
    mismatches = sorted(
        key
        for key in set(identity) | set(expected_identity)
        if identity.get(key) != expected_identity.get(key)
    )
    if mismatches:
        raise FrozenMaskIdentityError(
            f"frozen mask cache identity mismatch for {path}: {', '.join(mismatches)}; "
            "remove the stale cache"
        )
    if mask.shape != shape:
        raise FrozenMaskIdentityError(
            f"frozen mask {path} has shape {mask.shape}, expected measured frame shape {shape}"
        )
    return mask


def _components(mask: np.ndarray) -> tuple[np.ndarray, list[_Component]]:
    """Return the top five 4-connected components, largest first."""
    labels, count = ndimage.label(mask)
    components: list[_Component] = []
    for label in range(1, count + 1):
        ys, xs = np.nonzero(labels == label)
        if not len(xs):
            continue
        components.append(
            _Component(
                label=label,
                px=int(len(xs)),
                bbox=(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
            )
        )
    components.sort(key=lambda component: (-component.px, component.label))
    return labels, components[:5]


def _region_stat(
    frames: list[np.ndarray], labels: np.ndarray, component: _Component
) -> RegionStat:
    """Pool one component across frames and report its per-pixel gate statistics."""
    region_mask = labels == component.label
    sampled = np.concatenate([frame[region_mask] for frame in frames], axis=0)
    red, green, blue = sampled[:, 0], sampled[:, 1], sampled[:, 2]
    return RegionStat(
        median_rgb=_as_rgb_tuple(np.median(sampled, axis=0)),
        px=component.px,
        bbox=component.bbox,
        r_minus_b_median=float(np.median(np.abs(red - blue))),
        green_balance_median=float(np.median(np.abs(green - (red + blue) / 2))),
    )


def _as_rgb_tuple(rgb: np.ndarray) -> tuple[float, float, float]:
    """Convert one RGB vector to the public immutable representation."""
    return tuple(float(channel) for channel in rgb)  # type: ignore[return-value]


def _resize_nearest(image: np.ndarray, height: int, width: int) -> np.ndarray:
    """Resize an RGB image using dependency-free nearest-neighbour sampling."""
    source_height, source_width = image.shape[:2]
    ys = np.minimum(np.arange(height) * source_height // height, source_height - 1)
    xs = np.minimum(np.arange(width) * source_width // width, source_width - 1)
    return image[ys[:, None], xs[None, :]]


def _write_png_rgb(path: Path, image: np.ndarray) -> None:
    """Write a uint8 RGB PNG without adding a runtime image-library dependency."""
    if image.ndim != 3 or image.shape[-1] != 3 or image.dtype != np.uint8:
        raise ValueError("PNG image must be a uint8 array shaped (height, width, 3)")
    height, width = image.shape[:2]
    rows = b"".join(b"\x00" + row.tobytes() for row in np.ascontiguousarray(image))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
