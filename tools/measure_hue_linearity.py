# SPDX-License-Identifier: MIT
"""Measure how well each candidate uniform colour space holds hue under chroma change.

WHY THIS MEASUREMENT EXISTS

The evaluation harness has to report skin hue and skin chroma in some space, and
v2's selective-saturation operator has to scale chroma in some space. Naive RGB
saturation shifts hue, which is a known defect but not a measured one in this
repository. Picking a space by reputation would be exactly the kind of unsourced
choice this project is trying to stop making.

WHY IT IS NOT CIRCULAR

The obvious experiment, "scale chroma in space X and see how much the hue angle
moves in space X", is worthless: every space wins its own test by construction.
This measurement instead uses the standard approach from the hue-linearity
literature, with an external perceptual reference.

The Munsell renotation data defines colours by perceived hue, value, and chroma,
judged by human observers. A set of samples sharing a Munsell hue and value, and
differing only in Munsell chroma, is a perceptual constant-hue locus: to the eye,
those samples are the same hue at increasing colourfulness. A colour space with
good hue linearity will report a near-constant hue angle along such a locus. A
space with poor hue linearity will report an angle that swings as chroma rises,
which is precisely the failure that makes a saturation change look like a hue
change.

So the measured quantity is: along each perceptual constant-hue locus, how many
degrees does this space's hue angle wander?

METHOD, AND EVERY CHOICE IT MAKES

- Source data: the Munsell renotation "real" set, which is restricted to colours
  realisable with real surface reflectances.
- The renotation is specified under CIE illuminant C for the 1931 2 degree
  observer. Every space here except CIELAB is referred to D65, so samples are
  chromatically adapted from C to D65 before conversion. The transform used is
  named in the output and is a parameter, so the sensitivity of the result to
  that choice can be checked rather than assumed.
- Loci are (hue, value) groups with at least MIN_CHROMA_STEPS distinct chromas.
- Hue angle wander is computed with circular statistics about the locus mean
  direction, so a locus straddling zero degrees is not reported as a 360 degree
  swing.
- Jzazbz is an absolute-luminance space. Samples are scaled so that a Munsell
  value of 10, meaning diffuse white, sits at DIFFUSE_WHITE_CD_M2.
- CAM16 viewing conditions are stated in CAM16_VIEWING and printed in the output.

Lower numbers are better. The reported statistic is per-locus angular wander in
degrees, aggregated as a median and a 90th percentile over loci, plus the worst
single locus so that a space with one catastrophic region is not hidden by a good
median.

Run:

    .venv/bin/python tools/measure_hue_linearity.py
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")

import colour  # noqa: E402
from colour.notation import MUNSELL_COLOURS  # noqa: E402


#: A locus needs this many distinct Munsell chromas to say anything about wander.
MIN_CHROMA_STEPS = 4
#: Luminance assigned to Munsell value 10 when feeding the absolute-referred space.
DIFFUSE_WHITE_CD_M2 = 100.0
#: Stated CAM16 viewing conditions. L_A is the usual one fifth of diffuse white.
CAM16_VIEWING = {
    "L_A": DIFFUSE_WHITE_CD_M2 / 5.0,
    "Y_b": 20.0,
    "surround": "average",
}

#: Munsell hue families that carry human skin. Skin reflectance places skin in
#: the red to yellow-red arc, so these are the families whose hue linearity
#: actually governs a skin hue target. Reported separately from the global
#: median, which is dominated by hues this project never gates on.
SKIN_FAMILIES = ("R", "YR", "Y")

OBSERVER = "CIE 1931 2 Degree Standard Observer"
WHITE_C = colour.CCS_ILLUMINANTS[OBSERVER]["C"]
WHITE_D65 = colour.CCS_ILLUMINANTS[OBSERVER]["D65"]


def _hue_degrees(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hue angle in degrees from a pair of opponent axes."""
    return np.degrees(np.arctan2(b, a)) % 360.0


def hue_angles(xyz_c: np.ndarray, cat: str) -> dict[str, np.ndarray]:
    """Return each candidate space's hue angle for XYZ samples given under illuminant C.

    ``xyz_c`` is relative XYZ on a 0 to 1 scale with Y = 1 at diffuse white.
    """
    xyz_d65 = colour.chromatic_adaptation(
        xyz_c,
        colour.xy_to_XYZ(WHITE_C),
        colour.xy_to_XYZ(WHITE_D65),
        method="Von Kries",
        transform=cat,
    )

    angles: dict[str, np.ndarray] = {}

    # CIELAB, kept as the familiar baseline. Evaluated against its own native
    # illuminant C so it is not penalised for an adaptation it does not need.
    lab = colour.XYZ_to_Lab(xyz_c, illuminant=WHITE_C)
    angles["CIELAB"] = _hue_degrees(lab[..., 1], lab[..., 2])

    ipt = colour.XYZ_to_IPT(xyz_d65)
    angles["IPT"] = _hue_degrees(ipt[..., 1], ipt[..., 2])

    oklab = colour.XYZ_to_Oklab(xyz_d65)
    angles["Oklab"] = _hue_degrees(oklab[..., 1], oklab[..., 2])

    jzazbz = colour.XYZ_to_Jzazbz(xyz_d65 * DIFFUSE_WHITE_CD_M2)
    angles["Jzazbz"] = _hue_degrees(jzazbz[..., 1], jzazbz[..., 2])

    ictcp = colour.XYZ_to_ICtCp(xyz_d65, illuminant=WHITE_D65)
    # BT.2100 orders the components I, Ct, Cp. Cp is the red-green axis and Ct
    # the blue-yellow axis, so the hue angle is atan2(Ct, Cp).
    angles["ICtCp"] = _hue_degrees(ictcp[..., 2], ictcp[..., 1])

    cam16 = colour.XYZ_to_CAM16UCS(
        xyz_d65,
        XYZ_w=colour.xy_to_XYZ(WHITE_D65),
        L_A=CAM16_VIEWING["L_A"],
        Y_b=CAM16_VIEWING["Y_b"],
    )
    angles["CAM16-UCS"] = _hue_degrees(cam16[..., 1], cam16[..., 2])

    return angles


def circular_wander(degrees: np.ndarray) -> float:
    """Peak-to-peak angular spread about the mean direction, in degrees.

    Using the mean direction rather than a plain max minus min keeps a locus that
    straddles zero degrees from being reported as a 360 degree swing.
    """
    radians = np.radians(degrees)
    mean_direction = np.arctan2(np.sin(radians).mean(), np.cos(radians).mean())
    deviations = np.degrees(
        np.arctan2(np.sin(radians - mean_direction), np.cos(radians - mean_direction))
    )
    return float(deviations.max() - deviations.min())


def hue_family(hue: str) -> str:
    """Return the letter part of a Munsell hue, so '7.5YR' becomes 'YR'."""
    return hue.lstrip("0123456789.")


def build_loci() -> list[tuple[tuple[str, float], np.ndarray]]:
    """Group the Munsell renotation into constant hue and value, varying chroma."""
    grouped: dict[tuple[str, float], list[tuple[float, np.ndarray]]] = defaultdict(list)
    for (hue, value, chroma), xyY in MUNSELL_COLOURS["real"]:
        grouped[(hue, value)].append((chroma, np.asarray(xyY, dtype=np.float64)))

    loci = []
    for key, samples in grouped.items():
        if len({chroma for chroma, _ in samples}) < MIN_CHROMA_STEPS:
            continue
        ordered = [xyY for _, xyY in sorted(samples, key=lambda item: item[0])]
        loci.append((key, np.vstack(ordered)))
    return sorted(loci)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--cat",
        default="CAT02",
        help="chromatic adaptation transform used for illuminant C to D65 (default CAT02)",
    )
    args = parser.parse_args(argv)

    loci = build_loci()
    if not loci:
        print("no usable constant-hue loci found", file=sys.stderr)
        return 1

    wander: dict[str, list[float]] = defaultdict(list)
    by_family: dict[tuple[str, str], list[float]] = defaultdict(list)
    worst: dict[str, tuple[float, str]] = {}

    for (hue, value), xyY_rows in loci:
        # Munsell renotation Y is on a 0 to 100 scale. Bring it to 0 to 1.
        xyY = xyY_rows.copy()
        xyY[:, 2] /= 100.0
        xyz = colour.xyY_to_XYZ(xyY)
        family = hue_family(hue)
        for space, angles in hue_angles(xyz, args.cat).items():
            spread = circular_wander(angles)
            wander[space].append(spread)
            by_family[(space, family)].append(spread)
            label = f"{hue} {value:g}/"
            if space not in worst or spread > worst[space][0]:
                worst[space] = (spread, label)

    print(f"Hue linearity against the Munsell renotation 'real' set")
    print(f"  loci                  {len(loci)} (constant hue and value, >= {MIN_CHROMA_STEPS} chromas)")
    print(f"  samples               {sum(len(rows) for _, rows in loci)}")
    print(f"  adaptation C to D65   Von Kries / {args.cat}")
    print(f"  Jzazbz diffuse white  {DIFFUSE_WHITE_CD_M2:g} cd/m2")
    print(f"  CAM16 viewing         L_A {CAM16_VIEWING['L_A']:g}, Y_b {CAM16_VIEWING['Y_b']:g}, {CAM16_VIEWING['surround']} surround")
    print()
    print("Per-locus hue angle wander in degrees. Lower is better.")
    print()
    print(f"  {'space':<12} {'median':>8} {'p90':>8} {'worst':>8}   worst locus")
    print(f"  {'-' * 12} {'-' * 8} {'-' * 8} {'-' * 8}   {'-' * 20}")
    ranking = sorted(wander.items(), key=lambda item: float(np.median(item[1])))
    for space, spreads in ranking:
        values = np.asarray(spreads)
        print(
            f"  {space:<12} {np.median(values):8.3f} "
            f"{np.percentile(values, 90):8.3f} {worst[space][0]:8.3f}   {worst[space][1]}"
        )
    print()
    print(f"Best median hue linearity, all hues: {ranking[0][0]}")

    # The global median is not the number this project needs. Skin sits in the
    # red and yellow-red families, so a space that wins overall while doing badly
    # there would be the wrong choice for a skin hue target.
    families = sorted({family for _, family in by_family})
    print()
    print(f"Median wander in degrees by Munsell hue family. {' '.join(SKIN_FAMILIES)} carry skin.")
    print()
    header = "  ".join(f"{family:>6}" for family in families)
    print(f"  {'space':<12}  {header}")
    print(f"  {'-' * 12}  {'  '.join('-' * 6 for _ in families)}")
    for space, _ in ranking:
        cells = []
        for family in families:
            spreads = by_family.get((space, family))
            cells.append(f"{np.median(spreads):6.2f}" if spreads else f"{'--':>6}")
        print(f"  {space:<12}  {'  '.join(cells)}")

    skin_rank = sorted(
        (
            (
                space,
                float(
                    np.median(
                        np.concatenate(
                            [
                                by_family[(space, family)]
                                for family in SKIN_FAMILIES
                                if by_family.get((space, family))
                            ]
                        )
                    )
                ),
            )
            for space, _ in ranking
        ),
        key=lambda item: item[1],
    )
    print()
    print("Skin-carrying families only (" + ", ".join(SKIN_FAMILIES) + "):")
    for space, median in skin_rank:
        print(f"  {space:<12} {median:6.3f}")
    print()
    print(f"Best hue linearity where skin lives: {skin_rank[0][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
