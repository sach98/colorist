# SPDX-License-Identifier: MIT
"""Measure what this tool's channel-gain white balance costs against a real CAT.

WHY THIS MEASUREMENT EXISTS

v1 solves white balance as three per-channel gains. `corrections.solve_wb` takes
a sampled neutral in the linear working space and returns the gains that make it
equal-RGB at unchanged Rec.709 luma. That is the entire white-balance model.

A chromatic adaptation transform is a different operation: it maps colours from
one adapting illuminant to another through a cone-like response space, and it
does not generally reduce to three gains in the working RGB primaries. The
question this script answers is how much accuracy the simpler model gives up, in
units a colourist can read.

THE EXPERIMENT

Ground truth is analytic, not a matter of taste:

  REFERENCE   The ISO 17321-1 chart's spectral reflectances rendered under D65,
              through the CIE 1931 2 degree observer, encoded to linear Rec.709.
              This is what the chart is supposed to look like.

  DEFECT      The same reflectances rendered under a different illuminant and
              encoded through the same D65-referenced Rec.709 matrix. This models
              a camera left on a daylight balance under a different light. It
              carries the cast that white balance is supposed to remove.

  CORRECTIONS Each candidate maps DEFECT back toward REFERENCE:
                channel-gain  what v1 does, via corrections.solve_wb
                von Kries, Bradford, CAT02, CAT16  proper adaptation in XYZ

  SCORE       CIEDE2000 between each corrected chart and REFERENCE, over all 24
              patches, and separately over the two skin patches.

The channel-gain method is given the best case available to it: the exact
neutral patch as its sample, with no mask noise, no compression, and no mixed
lighting. If it loses under those conditions it loses under worse ones.

Run:

    .venv/bin/python tools/measure_white_balance.py
"""

from __future__ import annotations

import argparse
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")

import colour  # noqa: E402

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[1] / "src"))
from colorist.corrections import solve_wb  # noqa: E402


OBSERVER_NAME = "CIE 1931 2 Degree Standard Observer"
CHART_NAME = "ISO 17321-1"
#: Chart patches whose reflectance is human skin. Reported separately because a
#: white balance that is accurate on average but wrong on skin is the wrong
#: white balance for this project.
SKIN_PATCHES = ("dark skin", "light skin")
#: The chart's neutral patches, brightest first. The channel-gain solver needs a
#: neutral sample; it is given the brightest unclipped one.
NEUTRAL_PATCH = "white 9.5 (.05 D)"
#: Illuminants to test, spanning tungsten, two fluorescents, and two daylights.
TEST_ILLUMINANTS = ("A", "FL2", "FL11", "D50", "D75")
CATS = ("Von Kries", "Bradford", "CAT02", "CAT16")


def render_chart(illuminant_name: str) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Return ``(patch XYZ under this illuminant, the illuminant white XYZ)``.

    XYZ is normalised so a perfect diffuser under this illuminant has Y = 1, which
    is what a camera exposed for the scene would deliver.
    """
    cmfs = colour.MSDS_CMFS[OBSERVER_NAME]
    illuminant = colour.SDS_ILLUMINANTS[illuminant_name]
    white = colour.sd_to_XYZ(
        colour.colorimetry.sd_ones(illuminant.shape), cmfs, illuminant
    )
    scale = 100.0 / white[1]
    patches = {
        name: colour.sd_to_XYZ(sd, cmfs, illuminant) * scale / 100.0
        for name, sd in colour.SDS_COLOURCHECKERS[CHART_NAME].items()
    }
    return patches, white * scale / 100.0


def xyz_to_linear_rec709(xyz: np.ndarray) -> np.ndarray:
    """Encode XYZ through the D65-referenced Rec.709 matrix, without adaptation.

    No chromatic adaptation happens here on purpose. A camera set to a daylight
    balance applies this matrix whatever the light actually was, and the cast
    that produces is the defect under study.
    """
    return colour.XYZ_to_RGB(
        xyz,
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        apply_cctf_encoding=False,
        chromatic_adaptation_transform=None,
    )


def linear_rec709_to_lab(rgb: np.ndarray) -> np.ndarray:
    xyz = colour.RGB_to_XYZ(
        rgb,
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        apply_cctf_decoding=False,
        chromatic_adaptation_transform=None,
    )
    return colour.XYZ_to_Lab(xyz, illuminant=colour.RGB_COLOURSPACES["ITU-R BT.709"].whitepoint)


def correct_channel_gain(
    defect_rgb: dict[str, np.ndarray], neutral_name: str
) -> dict[str, np.ndarray]:
    """Apply v1's white balance: three gains solved from one neutral sample."""
    gains = np.asarray(solve_wb(defect_rgb[neutral_name]), dtype=np.float64)
    return {name: rgb * gains for name, rgb in defect_rgb.items()}


def correct_with_cat(
    defect_xyz: dict[str, np.ndarray],
    source_white: np.ndarray,
    target_white: np.ndarray,
    transform: str,
) -> dict[str, np.ndarray]:
    """Adapt from the shooting illuminant to D65 with a named CAT, then encode."""
    return {
        name: xyz_to_linear_rec709(
            colour.chromatic_adaptation(
                xyz, source_white, target_white, method="Von Kries", transform=transform
            )
        )
        for name, xyz in defect_xyz.items()
    }


def delta_e(
    corrected: dict[str, np.ndarray], reference: dict[str, np.ndarray], names
) -> np.ndarray:
    return np.array(
        [
            colour.delta_E(
                linear_rec709_to_lab(corrected[name]),
                linear_rec709_to_lab(reference[name]),
                method="CIE 2000",
            )
            for name in names
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)

    reference_xyz, d65_white = render_chart("D65")
    reference_rgb = {name: xyz_to_linear_rec709(xyz) for name, xyz in reference_xyz.items()}
    all_names = list(reference_rgb)

    print("White balance accuracy against an analytically known reference")
    print(f"  chart            {CHART_NAME} spectral reflectances, {len(all_names)} patches")
    print(f"  observer         {OBSERVER_NAME}")
    print(f"  reference        the same chart rendered under D65")
    print(f"  neutral sample   {NEUTRAL_PATCH!r}, given to the channel-gain solver exactly")
    print(f"  score            CIEDE2000 against the reference, lower is better")
    print()

    methods = ["channel-gain (v1)", *CATS]
    aggregate: dict[str, list[float]] = {method: [] for method in methods}
    aggregate_skin: dict[str, list[float]] = {method: [] for method in methods}

    for illuminant_name in TEST_ILLUMINANTS:
        defect_xyz, source_white = render_chart(illuminant_name)
        defect_rgb = {name: xyz_to_linear_rec709(xyz) for name, xyz in defect_xyz.items()}

        uncorrected = delta_e(defect_rgb, reference_rgb, all_names)
        uncorrected_skin = delta_e(defect_rgb, reference_rgb, SKIN_PATCHES)

        print(f"  illuminant {illuminant_name}")
        print(
            f"    {'uncorrected':<22} median {np.median(uncorrected):7.3f}   "
            f"max {uncorrected.max():7.3f}   skin {np.median(uncorrected_skin):7.3f}"
        )

        results = {"channel-gain (v1)": correct_channel_gain(defect_rgb, NEUTRAL_PATCH)}
        for transform in CATS:
            results[transform] = correct_with_cat(
                defect_xyz, source_white, d65_white, transform
            )

        for method in methods:
            errors = delta_e(results[method], reference_rgb, all_names)
            errors_skin = delta_e(results[method], reference_rgb, SKIN_PATCHES)
            aggregate[method].extend(errors.tolist())
            aggregate_skin[method].extend(errors_skin.tolist())
            worst_patch = all_names[int(errors.argmax())]
            print(
                f"    {method:<22} median {np.median(errors):7.3f}   "
                f"max {errors.max():7.3f}   skin {np.median(errors_skin):7.3f}"
                f"   worst on {worst_patch}"
            )
        print()

    print("  pooled over all tested illuminants")
    print(f"    {'method':<22} {'median':>8} {'p90':>8} {'max':>8} {'skin median':>13}")
    print(f"    {'-' * 22} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 13}")
    ranking = sorted(methods, key=lambda method: float(np.median(aggregate[method])))
    for method in ranking:
        errors = np.asarray(aggregate[method])
        skin = np.asarray(aggregate_skin[method])
        print(
            f"    {method:<22} {np.median(errors):8.3f} {np.percentile(errors, 90):8.3f} "
            f"{errors.max():8.3f} {np.median(skin):13.3f}"
        )

    v1_median = float(np.median(aggregate["channel-gain (v1)"]))
    best = ranking[0]
    best_median = float(np.median(aggregate[best]))
    print()
    print(f"  best method: {best}")
    if best != "channel-gain (v1)" and best_median > 0:
        print(
            f"  v1's channel-gain white balance leaves {v1_median:.3f} dE2000 median "
            f"where {best} leaves {best_median:.3f}, "
            f"a factor of {v1_median / best_median:.2f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
