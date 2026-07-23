# SPDX-License-Identifier: MIT
"""Test whether the vectorscope skin tone line is derived from skin, or from NTSC.

WHY THIS MEASUREMENT EXISTS

Every colourist is taught that skin sits on the vectorscope's skin tone line, at
roughly 123 degrees. If this project is going to ship a skin hue target, it needs
to know what that line actually is. There are two incompatible stories in
circulation:

  (a) the line marks where human skin empirically falls, or
  (b) the line is the NTSC YIQ I axis, which exists for bandwidth reasons, and
      skin sits near it by coincidence or by approximation.

These make different predictions and the difference is measurable here, with no
citation required for either half.

  PART 1 is pure arithmetic. The YIQ I axis is defined by the NTSC luma and
  chroma matrices. Its angle in the Cb/Cr plane can be computed exactly. If it
  lands on 123 degrees, then 123 is an NTSC constant and has nothing to do with
  skin reflectance.

  PART 2 is spectral rendering. Real skin reflectances are rendered under a range
  of illuminants and projected onto a Rec.709 Cb/Cr vectorscope. If skin lands on
  the same angle, story (a) survives. If it lands somewhere else, the line is an
  approximation and any target built on it inherits that error.

SKIN DATA

Two independent sources, both shipped with colour-science:

  ISO 17321-1   two patches, 'dark skin' and 'light skin'.
  PMC           four patches, 'Caucasian', 'Oriental', 'South Asian', 'African',
                from the preferred memory colour chart. colour-science attributes
                this dataset to doi:10.1002/col.22940, an attribution recorded and
                checked in references/CITATIONS.yaml under pmc-chart-luo-2024.
                The patch names are the dataset's own.

Six skin samples is a small corpus and the conclusions are bounded accordingly.
This measures where these published reflectances fall, not where all human skin
falls.

Run:

    .venv/bin/python tools/measure_skin_line.py
"""

from __future__ import annotations

import argparse
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")

import colour  # noqa: E402


OBSERVER_NAME = "CIE 1931 2 Degree Standard Observer"

#: NTSC 1953 luma coefficients, the basis of the YIQ system the I axis comes from.
NTSC_LUMA = np.array([0.299, 0.587, 0.114])
#: NTSC YIQ chroma matrix rows for I and Q, as published for the 1953 system.
NTSC_I = np.array([0.596, -0.274, -0.322])
NTSC_Q = np.array([0.211, -0.523, 0.312])

#: BT.709 luma coefficients, used by every modern Rec.709 vectorscope.
REC709_LUMA = np.array([0.2126, 0.7152, 0.0722])

#: A vectorscope does not plot B-Y against R-Y raw. It plots the standard scaled
#: Cb and Cr, and the two scale factors are not equal, so the SCALING CHANGES THE
#: ANGLE. Any claim of the form "the skin line is at N degrees" is meaningless
#: without saying which plane N is measured in. All three conventions are
#: reported below for exactly that reason.
#: Divisors are 2*(1 - luma_B) for Cb and 2*(1 - luma_R) for Cr.
AXIS_SCALINGS = {
    "unscaled B-Y, R-Y": (1.0, 1.0),
    "BT.601 Cb, Cr": (1.772, 1.402),
    "BT.709 Cb, Cr": (1.8556, 1.5748),
}

SKIN_SAMPLES = (
    ("ISO 17321-1", "dark skin"),
    ("ISO 17321-1", "light skin"),
    ("PMC", "Caucasian"),
    ("PMC", "Oriental"),
    ("PMC", "South Asian"),
    ("PMC", "African"),
)
ILLUMINANTS = ("D65", "D55", "D50", "A", "FL2", "FL11")


def scaled_angle(cb: float, cr: float, scaling: tuple[float, float]) -> float:
    """Angle in degrees from +Cb, after applying a named Cb/Cr scaling."""
    cb_divisor, cr_divisor = scaling
    return float(np.degrees(np.arctan2(cr / cr_divisor, cb / cb_divisor)) % 360.0)


def axis_angle_in_cbcr(chroma_row: np.ndarray, luma: np.ndarray) -> float:
    """Angle, in degrees from +Cb, of the direction a YIQ-style axis points.

    A chroma axis is a linear form on RGB. Expressed in the (B - Y, R - Y) plane
    it becomes a direction, and that direction is what a vectorscope graticule
    draws. Solving is exact: write the axis as a(R - Y) + b(B - Y), match
    coefficients against the published RGB row, and the graticule direction is
    (b, a) normalised.
    """
    # R - Y and B - Y as linear forms on RGB.
    r_minus_y = np.array([1.0, 0.0, 0.0]) - luma
    b_minus_y = np.array([0.0, 0.0, 1.0]) - luma
    # Least squares because the three RGB coefficients are constrained: any
    # combination of R-Y and B-Y sums to zero, as does a valid chroma row.
    basis = np.vstack([r_minus_y, b_minus_y]).T
    coefficients, *_ = np.linalg.lstsq(basis, chroma_row, rcond=None)
    residual = basis @ coefficients - chroma_row
    a, b = coefficients
    return (b, a), float(np.abs(residual).max())


def skin_cbcr(chart: str, patch: str, illuminant_name: str) -> tuple[tuple[float, float], float]:
    """Return ``((unscaled Cb, unscaled Cr), Rec.709 luma)`` for one skin reflectance."""
    cmfs = colour.MSDS_CMFS[OBSERVER_NAME]
    illuminant = colour.SDS_ILLUMINANTS[illuminant_name]
    white = colour.sd_to_XYZ(colour.colorimetry.sd_ones(illuminant.shape), cmfs, illuminant)
    xyz = colour.sd_to_XYZ(colour.SDS_COLOURCHECKERS[chart][patch], cmfs, illuminant) / white[1]

    # A camera white balanced for the scene: adapt to D65 before encoding, which
    # is what a correctly balanced shot delivers. The uncorrected case is covered
    # by tools/measure_white_balance.py and is not the question here.
    xyz_d65 = colour.chromatic_adaptation(
        xyz,
        colour.xy_to_XYZ(colour.CCS_ILLUMINANTS[OBSERVER_NAME][illuminant_name])
        if illuminant_name in colour.CCS_ILLUMINANTS[OBSERVER_NAME]
        else white / white[1],
        colour.xy_to_XYZ(colour.CCS_ILLUMINANTS[OBSERVER_NAME]["D65"]),
        method="Von Kries",
        transform="CAT02",
    )
    linear = colour.XYZ_to_RGB(
        xyz_d65,
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        apply_cctf_encoding=False,
        chromatic_adaptation_transform=None,
    )
    # A vectorscope reads the gamma-encoded signal, not linear light.
    encoded = colour.RGB_COLOURSPACES["ITU-R BT.709"].cctf_encoding(np.clip(linear, 0.0, 1.0))
    luma = float(encoded @ REC709_LUMA)
    return (float(encoded[2]) - luma, float(encoded[0]) - luma), luma


def skin_oklab(chart: str, patch: str, illuminant_name: str) -> tuple[float, float]:
    """Return ``(Oklab hue angle in degrees, Oklab chroma)`` for one reflectance."""
    cmfs = colour.MSDS_CMFS[OBSERVER_NAME]
    illuminant = colour.SDS_ILLUMINANTS[illuminant_name]
    white = colour.sd_to_XYZ(colour.colorimetry.sd_ones(illuminant.shape), cmfs, illuminant)
    xyz = colour.sd_to_XYZ(colour.SDS_COLOURCHECKERS[chart][patch], cmfs, illuminant) / white[1]
    xyz_d65 = colour.chromatic_adaptation(
        xyz,
        colour.xy_to_XYZ(colour.CCS_ILLUMINANTS[OBSERVER_NAME][illuminant_name])
        if illuminant_name in colour.CCS_ILLUMINANTS[OBSERVER_NAME]
        else white / white[1],
        colour.xy_to_XYZ(colour.CCS_ILLUMINANTS[OBSERVER_NAME]["D65"]),
        method="Von Kries",
        transform="CAT02",
    )
    _, a, b = colour.XYZ_to_Oklab(xyz_d65)
    return float(np.degrees(np.arctan2(b, a)) % 360.0), float(np.hypot(a, b))


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)

    def separation(a: float, b: float) -> float:
        return abs(((a - b) + 180) % 360 - 180)

    print("PART 1: where the graticule line comes from, by arithmetic alone")
    print()
    i_vector, i_residual = axis_angle_in_cbcr(NTSC_I, NTSC_LUMA)
    q_vector, q_residual = axis_angle_in_cbcr(NTSC_Q, NTSC_LUMA)
    print(f"  NTSC 1953 YIQ, luma {tuple(NTSC_LUMA)}")
    print(f"  exact solve, worst residual {max(i_residual, q_residual):.2e}")
    print()
    print(f"  {'plane':<22} {'+I':>9} {'-I':>9} {'+Q':>9}")
    print(f"  {'-' * 22} {'-' * 9} {'-' * 9} {'-' * 9}")
    i_angles = {}
    for plane, scaling in AXIS_SCALINGS.items():
        i_angle = scaled_angle(*i_vector, scaling)
        q_angle = scaled_angle(*q_vector, scaling)
        i_angles[plane] = i_angle
        print(
            f"  {plane:<22} {i_angle:9.3f} {(i_angle + 180) % 360:9.3f} {q_angle:9.3f}"
        )
    print()
    print("  Against the conventionally quoted 123 degrees:")
    for plane, i_angle in i_angles.items():
        print(f"    {plane:<22} +I is {separation(i_angle, 123.0):6.3f} deg away")
    print()

    print("PART 2: where published skin reflectances actually fall")
    print()
    vectors: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for chart, patch in SKIN_SAMPLES:
        vectors[(chart, patch)] = [
            skin_cbcr(chart, patch, illuminant_name)[0] for illuminant_name in ILLUMINANTS
        ]

    for plane, scaling in AXIS_SCALINGS.items():
        print(f"  plane: {plane}")
        print(f"    {'sample':<28} " + " ".join(f"{name:>7}" for name in ILLUMINANTS))
        print(f"    {'-' * 28} " + " ".join("-" * 7 for _ in ILLUMINANTS))
        collected: list[float] = []
        for (chart, patch), samples in vectors.items():
            row = [scaled_angle(cb, cr, scaling) for cb, cr in samples]
            collected.extend(row)
            print(f"    {chart + '/' + patch:<28} " + " ".join(f"{a:7.2f}" for a in row))

        angles = np.asarray(collected)
        radians = np.radians(angles)
        mean_direction = float(
            np.degrees(np.arctan2(np.sin(radians).mean(), np.cos(radians).mean())) % 360.0
        )
        deviations = np.degrees(
            np.arctan2(
                np.sin(radians - np.radians(mean_direction)),
                np.cos(radians - np.radians(mean_direction)),
            )
        )
        print(
            f"    mean direction {mean_direction:8.3f} deg, "
            f"spread {deviations.min():+.2f} to {deviations.max():+.2f}, "
            f"vs +I {separation(mean_direction, i_angles[plane]):6.3f}, "
            f"vs 123 deg {separation(mean_direction, 123.0):6.3f}"
        )
        print()

    print(f"  samples per plane: {len(SKIN_SAMPLES)} reflectances x {len(ILLUMINANTS)} illuminants")
    print()

    # The vectorscope angle is what a colourist reads. The gated statistic is the
    # Oklab hue angle, chosen on the Munsell evidence in
    # references/color-theory/uniform-spaces-for-grading.md. Both come from the
    # same rendering, so they are computed together and cannot disagree by
    # accident of pipeline.
    print("PART 3: the same reflectances in Oklab, the space the scorecard gates in")
    print()
    print(f"  {'sample':<28} " + " ".join(f"{name:>7}" for name in ILLUMINANTS) + "   chroma@D65")
    print(f"  {'-' * 28} " + " ".join("-" * 7 for _ in ILLUMINANTS) + "   ----------")
    oklab_angles: list[float] = []
    for chart, patch in SKIN_SAMPLES:
        row = []
        chroma_d65 = 0.0
        for illuminant_name in ILLUMINANTS:
            hue, chroma = skin_oklab(chart, patch, illuminant_name)
            row.append(hue)
            oklab_angles.append(hue)
            if illuminant_name == "D65":
                chroma_d65 = chroma
        print(
            f"  {chart + '/' + patch:<28} "
            + " ".join(f"{a:7.2f}" for a in row)
            + f"   {chroma_d65:10.5f}"
        )

    angles = np.asarray(oklab_angles)
    radians = np.radians(angles)
    mean_direction = float(
        np.degrees(np.arctan2(np.sin(radians).mean(), np.cos(radians).mean())) % 360.0
    )
    deviations = np.degrees(
        np.arctan2(
            np.sin(radians - np.radians(mean_direction)),
            np.cos(radians - np.radians(mean_direction)),
        )
    )
    print()
    print(f"  Oklab mean hue {mean_direction:.3f} deg, spread {deviations.min():+.2f} to {deviations.max():+.2f}")

    # Excluding the spiky fluorescent, which is a known metameric outlier.
    without_fl2 = [
        hue
        for (chart, patch) in SKIN_SAMPLES
        for name in ILLUMINANTS
        if name != "FL2"
        for hue in [skin_oklab(chart, patch, name)[0]]
    ]
    trimmed = np.asarray(without_fl2)
    trimmed_radians = np.radians(trimmed)
    trimmed_mean = float(
        np.degrees(
            np.arctan2(np.sin(trimmed_radians).mean(), np.cos(trimmed_radians).mean())
        )
        % 360.0
    )
    trimmed_dev = np.degrees(
        np.arctan2(
            np.sin(trimmed_radians - np.radians(trimmed_mean)),
            np.cos(trimmed_radians - np.radians(trimmed_mean)),
        )
    )
    print(
        f"  excluding FL2  {trimmed_mean:.3f} deg, "
        f"spread {trimmed_dev.min():+.2f} to {trimmed_dev.max():+.2f}, "
        f"n={len(trimmed)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
