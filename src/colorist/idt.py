# SPDX-License-Identifier: MIT
"""Input transforms from camera code values to scene-linear Rec.709/D65.

Curves and matrices come from colour-science; manufacturer documents are the
oracle via the vector fixtures in ``tests/vectors``. LUT inputs cover camera
code values from 0 to 1. Outputs intentionally remain unclamped because
scene-linear values may be negative or above 1.
"""

import colour
import numpy as np

from colorist.lut import write_cube  # noqa: F401 (used by build tooling)


_CURVES = {
    "slog3": colour.models.log_decoding_SLog3,
    "logc4": colour.models.log_decoding_ARRILogC4,
    "vlog": colour.models.log_decoding_VLog,
    "clog3": colour.models.log_decoding_CanonLog3,
    "logc3": colour.models.log_decoding_ARRILogC3,
}

_GAMUT = {
    "slog3_sgamut3cine": "S-Gamut3.Cine",
    "logc4_awg4": "ARRI Wide Gamut 4",
    "vlog_vgamut": "V-Gamut",
    "clog3_cgamut": "Cinema Gamut",
    "logc3ei800_awg3": "ARRI Wide Gamut 3",
}

_CURVE_BY_IDT = {
    "slog3_sgamut3cine": "slog3",
    "logc4_awg4": "logc4",
    "vlog_vgamut": "vlog",
    "clog3_cgamut": "clog3",
    "logc3ei800_awg3": "logc3",
}


def decode_curve(curve: str, code: np.ndarray) -> np.ndarray:
    """Decode camera code values to scene-linear reflectance."""
    return np.asarray(_CURVES[curve](code), dtype=np.float64)


def camera_to_working(curve_gamut: str, code_rgb: np.ndarray) -> np.ndarray:
    """Convert camera code RGB to scene-linear Rec.709/D65 RGB."""
    curve = _CURVE_BY_IDT[curve_gamut]
    source_space = colour.RGB_COLOURSPACES[_GAMUT[curve_gamut]]
    destination_space = colour.RGB_COLOURSPACES["ITU-R BT.709"]
    linear_camera = decode_curve(curve, code_rgb)
    return colour.RGB_to_RGB(
        linear_camera,
        source_space,
        destination_space,
        chromatic_adaptation_transform="CAT02",
        apply_cctf_decoding=False,
        apply_cctf_encoding=False,
    )


def build_idt(curve_gamut: str, n: int = 65) -> np.ndarray:
    """Build an ``n``-point camera-code to Rec.709/D65 scene-linear LUT."""
    axis = np.linspace(0.0, 1.0, n)
    red, green, blue = np.meshgrid(axis, axis, axis, indexing="ij")
    code = np.stack([red, green, blue], axis=-1)
    return camera_to_working(curve_gamut, code)
