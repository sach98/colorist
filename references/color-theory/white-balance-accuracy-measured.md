# What this tool's white balance costs, measured

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

v1 models white balance as three per-channel gains: `corrections.solve_wb` takes
a neutral sample in the linear working space and returns the gains that make it
equal-RGB at unchanged Rec.709 luma. A chromatic adaptation transform is a
different operation, mapping colours between adapting illuminants through a
cone-like response space, and it does not generally reduce to three gains in the
working primaries.

This file records how much the simpler model gives up, measured rather than
asserted. Companion file:
`references/color-theory/white-balance-and-illuminants.md` covers the model and
the mixed-light refusal; this file covers only the accuracy question.

## Method [E: tools/measure_white_balance.py, output recorded in docs/research/measurements/2026-07-23-white-balance-accuracy.md]

The ground truth is analytic, so no taste enters:

- **Reference**: the ISO 17321-1 chart's 24 spectral reflectances rendered under
  D65 through the CIE 1931 2 degree observer, encoded to linear Rec.709.
- **Defect**: the same reflectances rendered under a different illuminant and
  encoded through the same D65-referenced matrix, which models a camera left on a
  daylight balance under another light.
- **Corrections**: v1's channel gains, and von Kries, Bradford, CAT02, and CAT16
  adaptation in XYZ.
- **Score**: CIEDE2000 against the reference, over all patches and separately
  over the chart's two skin patches.

The channel-gain method is given the best case it could ask for: the exact
neutral patch as its sample, with no mask noise, no compression, and no mixed
lighting. Its results here are therefore an upper bound on its real performance.

Illuminants tested: A, FL2, FL11, D50, D75.

## Result, pooled over all five illuminants

| Method | median dE2000 | p90 | max | skin median |
|---|---|---|---|---|
| Bradford | 0.727 | 4.352 | 10.101 | 1.444 |
| CAT02 | 0.822 | 4.298 | 9.338 | 1.504 |
| CAT16 | 1.028 | 4.852 | 9.900 | 1.549 |
| channel-gain (v1) | 1.132 | 7.951 | 27.752 | 2.782 |
| von Kries | 1.349 | 6.438 | 12.054 | 2.068 |

## What this does and does not support

**NOT supported: that v1's white balance is broken.** On the median it is 1.132
dE2000 against Bradford's 0.727, a factor of 1.56, and it beats classical von
Kries outright. For the two daylight shifts it is competitive or better: under
D75 it leaves 0.483 median where Bradford leaves 0.269, and under D50 it leaves
0.674 against Bradford's 0.563. For mild daylight corrections, three gains are a
reasonable model and the case for replacing them is weak.

**Supported: the model fails in the tail, and the tail is where the work is.**
v1's worst-case error is 27.752 dE2000 against Bradford's 10.101. The failure is
concentrated in large illuminant shifts, and it is severe under tungsten:

| Under illuminant A | median | max | worst patch | skin median |
|---|---|---|---|---|
| uncorrected | 18.670 | 28.956 | | 14.166 |
| channel-gain (v1) | 3.654 | 27.752 | **orange** | 5.102 |
| Bradford | 1.940 | 4.894 | cyan | 2.820 |
| CAT02 | 2.457 | 5.373 | magenta | 3.067 |
| von Kries | 4.454 | 9.081 | cyan | 2.741 |

The number worth staring at is the third row. Under tungsten, v1's correction
leaves 27.752 dE2000 on the **orange** patch, against 28.956 uncorrected. On that
patch the correction accomplishes almost nothing, while the same correction
brings the median from 18.670 down to 3.654. The proper transforms leave their
worst error on cyan or magenta, at roughly a fifth the magnitude.

**Supported, and directly relevant to this project's stated goal: the failure sits
where skin sits.** Orange is the chart's nearest neighbour to skin in hue.
Pooled over all illuminants, v1 leaves 2.782 dE2000 median on the skin patches
where Bradford leaves 1.444 and CAT02 leaves 1.504, roughly twice the error. The
gap is not in the average patch, it is in warm saturated colour, which is exactly
the region a skin hue and skin chroma target has to be accurate in.

**Supported: which transform to prefer, if one is adopted.** Bradford has the best
median and the best skin median of the five. CAT02 is within 0.1 dE2000 of it on
both and has a slightly better worst case. Classical von Kries is the weakest of
the four proper transforms on the median and should not be the default.

## Caveats that limit how far this generalises

- Five illuminants, one chart, 24 patches. This is not a survey.
- Spectral rendering only. The measurement never passes through a camera's actual
  spectral sensitivities, an encoder, or a compression stage, so it isolates the
  colorimetric question and says nothing about how the errors survive a real
  pipeline.
- The channel-gain solver was handed a perfect neutral. In use it samples a
  frozen mask from real footage and can be handed a contaminated neutral, which
  is a separate failure mode that v1 already refuses rather than mishandles.
- CIEDE2000 is a small-difference formula. Errors in the twenties are outside the
  range it was fitted for, so the tungsten orange figure should be read as
  "very large" rather than as a precise multiple of the others.
- Nothing here measures the mixed-lighting case, which is the defect that
  motivated v2. A spatially split illuminant cannot be represented in this
  experiment because the chart has one illuminant at a time.
