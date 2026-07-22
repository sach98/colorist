# SPDX-License-Identifier: MIT
"""Correction algebra and deterministic per-shot LUT compilation.

The grading shaper uses a C1-continuous affine toe below ``x_b = 2**-7``
and a log2 segment above it. With
``D = log2(1024.0) - log2(0.001)``, its definition is::

    A = 1 / (x_b * ln(2) * D)
    y_b = (log2(x_b) - log2(0.001)) / D
    B = y_b - A * x_b
    s(x) = clip(A * x + B                         if x < x_b else
                (log2(x) - log2(0.001)) / D, 0, 1)

The inverse splits at ``y_b`` and applies the matching inverse segment::

    s_inverse(y) = (y - B) / A                    if y < y_b else
                   2 ** (log2(0.001) + y * D)

Scene-linear zero maps to ``B`` and back to exactly zero. Supported camera
curves decode code value 1.0 to at most 469.8, and their gamut conversions
reach at most 889.4055204847825 over the code cube, so the 1024.0 ceiling
does not clip an uncorrected supported IDT input. Values above 1024.0 clamp
to 1024.0. Values below ``-B / A`` clamp to grading zero and invert to that
negative boundary; the BT.1886 output encode then clamps them to display
black. Camera black that decodes to scene-linear zero remains exactly zero.

The BT.1886 output encode is the simple gamma 2.4 inverse EOTF used by this
project::

    display = clip(linear_display, 0, 1) ** (1 / 2.4)

For display-referred Rec.709 input, the matching decode is
``linear = clip(display, 0, 1) ** 2.4``.
"""

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from colorist.idt import camera_to_working
from colorist.lut import apply_lut


LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
SHAPER_MIN = 0.001
SHAPER_MAX = 1024.0
SHAPER_BREAKPOINT = 2.0**-7
_SHAPER_LOG_MIN = math.log2(SHAPER_MIN)
_SHAPER_LOG_RANGE = math.log2(SHAPER_MAX) - _SHAPER_LOG_MIN
SHAPER_BREAKPOINT_GRADING = (
    math.log2(SHAPER_BREAKPOINT) - _SHAPER_LOG_MIN
) / _SHAPER_LOG_RANGE
SHAPER_TOE_SLOPE = 1.0 / (
    SHAPER_BREAKPOINT * math.log(2.0) * _SHAPER_LOG_RANGE
)
SHAPER_TOE_OFFSET = (
    SHAPER_BREAKPOINT_GRADING - SHAPER_TOE_SLOPE * SHAPER_BREAKPOINT
)


def shaper(scene_linear: np.ndarray) -> np.ndarray:
    """Map scene-linear RGB into the clipped affine-to-log2 grading space."""
    values = np.asarray(scene_linear, dtype=np.float64)
    log_values = (
        np.log2(np.clip(values, SHAPER_BREAKPOINT, None)) - _SHAPER_LOG_MIN
    ) / _SHAPER_LOG_RANGE
    shaped = np.where(
        values < SHAPER_BREAKPOINT,
        SHAPER_TOE_SLOPE * values + SHAPER_TOE_OFFSET,
        log_values,
    )
    return np.clip(shaped, 0.0, 1.0)


def inverse_shaper(grading_rgb: np.ndarray) -> np.ndarray:
    """Map clipped affine-to-log2 grading values back to scene-linear RGB."""
    values = np.clip(np.asarray(grading_rgb, dtype=np.float64), 0.0, 1.0)
    toe_values = (values - SHAPER_TOE_OFFSET) / SHAPER_TOE_SLOPE
    log_values = np.exp2(_SHAPER_LOG_MIN + values * _SHAPER_LOG_RANGE)
    return np.where(values < SHAPER_BREAKPOINT_GRADING, toe_values, log_values)


def bt1886_decode(display_rgb: np.ndarray) -> np.ndarray:
    """Decode display-referred Rec.709 values with the project gamma model."""
    values = np.clip(np.asarray(display_rgb, dtype=np.float64), 0.0, 1.0)
    return np.power(values, 2.4)


def bt1886_encode(linear_display_rgb: np.ndarray) -> np.ndarray:
    """Encode linear display RGB with the simple gamma 2.4 inverse EOTF."""
    values = np.clip(np.asarray(linear_display_rgb, dtype=np.float64), 0.0, 1.0)
    return np.power(values, 1.0 / 2.4)


DEFAULT_PIVOT = float(shaper(np.array(0.18)))


@dataclass(frozen=True)
class Correction:
    """One shot's reproducible correction parameters."""

    wb_gains: tuple[float, float, float] = (1.0, 1.0, 1.0)
    exposure_ev: float = 0.0
    contrast: float = 1.0
    pivot: float = DEFAULT_PIVOT
    saturation: float = 1.0


def solve_wb(neutral_median_rgb: np.ndarray) -> tuple[float, float, float]:
    """Map the sampled neutral median to equal RGB of identical Rec.709 luma.

    The input sample and returned gains are defined in the linear working space.
    """
    neutral = np.asarray(neutral_median_rgb, dtype=np.float64)
    if neutral.shape != (3,):
        raise ValueError("neutral_median_rgb must contain exactly three channels")
    if np.any(neutral <= 0.0):
        raise ValueError("neutral_median_rgb channels must be positive")

    grey = float(np.dot(neutral, LUMA_WEIGHTS))
    gains = grey / neutral
    return tuple(float(channel) for channel in gains)


def solve_exposure(current_luma: float, target_luma: float) -> float:
    """Return the exposure offset that maps current luma to target luma."""
    if current_luma <= 0.0 or target_luma <= 0.0:
        raise ValueError("current_luma and target_luma must be positive")
    return math.log2(target_luma / current_luma)


def _pivoted_contrast(
    grading_rgb: np.ndarray, contrast: float, pivot: float
) -> np.ndarray:
    if pivot <= 0.0:
        raise ValueError("contrast pivot must be positive")
    if contrast == 1.0:
        return grading_rgb
    return pivot * np.power(np.clip(grading_rgb, 0.0, None) / pivot, contrast)


def _saturate(grading_rgb: np.ndarray, saturation: float) -> np.ndarray:
    if saturation == 1.0:
        return grading_rgb
    luma = np.sum(grading_rgb * LUMA_WEIGHTS, axis=-1, keepdims=True)
    return luma + saturation * (grading_rgb - luma)


def compile_shot_lut(
    corr: Correction,
    look: np.ndarray | None,
    curve_gamut: str | None,
    n: int = 65,
) -> np.ndarray:
    """Compile the fixed camera-to-display correction chain on an RGB lattice."""
    if n < 2:
        raise ValueError("n must be at least 2")

    axis = np.linspace(0.0, 1.0, n)
    red, green, blue = np.meshgrid(axis, axis, axis, indexing="ij")
    code_rgb = np.stack([red, green, blue], axis=-1)
    if curve_gamut is None:
        working = bt1886_decode(code_rgb)
    else:
        working = camera_to_working(curve_gamut, code_rgb)

    gains = np.asarray(corr.wb_gains, dtype=np.float64)
    if gains.shape != (3,):
        raise ValueError("wb_gains must contain exactly three channels")
    working = working * gains * (2.0**corr.exposure_ev)
    grading = shaper(working)
    grading = _pivoted_contrast(grading, corr.contrast, corr.pivot)
    grading = _saturate(grading, corr.saturation)
    if look is not None:
        grading = apply_lut(look, grading)
    return bt1886_encode(inverse_shaper(grading))


def manifest_dict(corr: Correction) -> dict[str, Any]:
    """Serialize correction parameters using the versioned manifest schema."""
    return {
        "schema": "colorist/correction/v1",
        "wb_gains": list(corr.wb_gains),
        "exposure_ev": corr.exposure_ev,
        "contrast": corr.contrast,
        "pivot": corr.pivot,
        "saturation": corr.saturation,
    }


def from_manifest(data: dict[str, Any]) -> Correction:
    """Deserialize a v1 correction manifest."""
    if data.get("schema") != "colorist/correction/v1":
        raise ValueError("unsupported correction manifest schema")
    return Correction(
        wb_gains=tuple(data["wb_gains"]),
        exposure_ev=data["exposure_ev"],
        contrast=data["contrast"],
        pivot=data["pivot"],
        saturation=data["saturation"],
    )
