# SPDX-License-Identifier: MIT
"""Measure how far this tool's own saturation operator moves skin hue.

WHY THIS MEASUREMENT EXISTS

`references/color-theory/uniform-spaces-for-grading.md` measures which uniform
space best holds hue under a chroma change. That is a question about spaces. This
is the narrower and more immediately useful question about THIS tool: when v1's
saturation control is turned up, how much does skin hue move?

The motivating observation was that raising global saturation on a real interview
clip made the existing colour cast worse rather than better. This script asks
whether the operator itself is part of that, separately from the fact that a
global control cannot fix a spatially varying defect.

WHAT v1 ACTUALLY DOES

`corrections._saturate` interpolates each channel away from the Rec.709 luma of
the pixel, and it does so in the log grading space produced by
`corrections.shaper`, not in linear light and not in a uniform space:

    luma = sum(grading_rgb * LUMA_WEIGHTS)
    out  = luma + saturation * (grading_rgb - luma)

There is no reason for that operation to preserve hue, and this script measures
by how much it does not.

THE COMPARISON IS MATCHED ON EFFECT, NOT ON THE KNOB

Comparing "v1 at saturation 1.5" against "an Oklab chroma scale of 1.5" would be
unfair, because the two knobs do not deliver the same amount of chroma change.
Instead, for each v1 setting the script measures the Oklab chroma ratio v1
actually achieved, then applies the Oklab chroma scale that achieves the same
ratio, and compares the hue drift at equal delivered chroma.

Run:

    .venv/bin/python tools/measure_saturation_hue_drift.py
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

import colour  # noqa: E402

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from colorist.corrections import (  # noqa: E402
    _saturate,
    bt1886_decode,
    bt1886_encode,
    inverse_shaper,
    shaper,
)


OBSERVER_NAME = "CIE 1931 2 Degree Standard Observer"
CHART_NAME = "ISO 17321-1"
SKIN_PATCHES = ("dark skin", "light skin")
SATURATIONS = (0.75, 1.25, 1.5, 2.0)


def skin_display_rgb() -> dict[str, np.ndarray]:
    """Render the chart's skin patches under D65 to Rec.709 display code."""
    cmfs = colour.MSDS_CMFS[OBSERVER_NAME]
    illuminant = colour.SDS_ILLUMINANTS["D65"]
    white = colour.sd_to_XYZ(colour.colorimetry.sd_ones(illuminant.shape), cmfs, illuminant)
    scale = 1.0 / white[1]
    out = {}
    for name in SKIN_PATCHES:
        xyz = colour.sd_to_XYZ(colour.SDS_COLOURCHECKERS[CHART_NAME][name], cmfs, illuminant) * scale
        linear = colour.XYZ_to_RGB(
            xyz,
            colour.RGB_COLOURSPACES["ITU-R BT.709"],
            apply_cctf_encoding=False,
            chromatic_adaptation_transform=None,
        )
        out[name] = bt1886_encode(np.clip(linear, 0.0, 1.0))
    return out


def oklab_of_display(display_rgb: np.ndarray) -> np.ndarray:
    """Convert Rec.709 display code to Oklab through the project's own decode."""
    xyz = colour.RGB_to_XYZ(
        bt1886_decode(display_rgb),
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        apply_cctf_decoding=False,
        chromatic_adaptation_transform=None,
    )
    return colour.XYZ_to_Oklab(xyz)


def oklab_to_display(oklab: np.ndarray) -> np.ndarray:
    xyz = colour.Oklab_to_XYZ(oklab)
    linear = colour.XYZ_to_RGB(
        xyz,
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        apply_cctf_encoding=False,
        chromatic_adaptation_transform=None,
    )
    return bt1886_encode(np.clip(linear, 0.0, 1.0))


def hue_chroma(oklab: np.ndarray) -> tuple[float, float]:
    _, a, b = oklab
    return float(np.degrees(np.arctan2(b, a)) % 360.0), float(np.hypot(a, b))


def apply_v1_saturation(display_rgb: np.ndarray, saturation: float) -> np.ndarray:
    """Run the display value through v1's grading-space saturation and back."""
    grading = shaper(bt1886_decode(display_rgb))
    return bt1886_encode(inverse_shaper(_saturate(grading, saturation)))


def apply_oklab_chroma_scale(display_rgb: np.ndarray, factor: float) -> np.ndarray:
    oklab = oklab_of_display(display_rgb)
    scaled = oklab.copy()
    scaled[1:] *= factor
    return oklab_to_display(scaled)


def signed_hue_delta(before: float, after: float) -> float:
    return float((after - before + 180.0) % 360.0 - 180.0)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)

    patches = skin_display_rgb()
    print("Skin hue drift under a saturation change")
    print(f"  patches   {CHART_NAME}: {', '.join(SKIN_PATCHES)}, rendered under D65")
    print("  operator  corrections._saturate, in the log grading space, as v1 applies it")
    print("  measured  Oklab hue angle, the space measured most hue-linear where skin lives")
    print("  matched   the Oklab comparison uses the chroma ratio v1 actually delivered")
    print()

    for name, display_rgb in patches.items():
        base_hue, base_chroma = hue_chroma(oklab_of_display(display_rgb))
        print(f"  {name}: Oklab hue {base_hue:.2f} deg, chroma {base_chroma:.5f}")
        print(
            f"    {'v1 sat':>7} {'chroma x':>9} {'v1 hue drift':>13} "
            f"{'Oklab hue drift':>16}   at matched chroma"
        )
        for saturation in SATURATIONS:
            v1_hue, v1_chroma = hue_chroma(
                oklab_of_display(apply_v1_saturation(display_rgb, saturation))
            )
            delivered = v1_chroma / base_chroma
            ok_hue, _ = hue_chroma(
                oklab_of_display(apply_oklab_chroma_scale(display_rgb, delivered))
            )
            print(
                f"    {saturation:7.2f} {delivered:9.4f} "
                f"{signed_hue_delta(base_hue, v1_hue):12.3f}  "
                f"{signed_hue_delta(base_hue, ok_hue):15.3f}"
            )
        print()

    print("  A positive drift is a rotation toward yellow, negative toward magenta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
