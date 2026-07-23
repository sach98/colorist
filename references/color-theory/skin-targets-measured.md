# Skin targets, measured

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Where the shipped skin targets come from, and what they are and are not entitled
to claim. Nothing in this file rests on a colourist convention that has not been
checked here.

## The question about the vectorscope skin line

Every colourist is taught that skin sits on the vectorscope's skin tone line at
roughly 123 degrees, and the usual explanation is that this line is the NTSC YIQ
I axis. Those are two separate claims and they make different predictions, so
both are testable.

**First, a trap in the question itself.** A vectorscope does not plot B minus Y
against R minus Y raw. It plots scaled Cb and Cr, and the two scale factors are
not equal, so the scaling changes the angle. "The skin line is at 123 degrees" is
not a well-formed statement until the plane is named. All results below are given
in three planes for that reason.

## Result 1: the I axis is not at 123 degrees, in any plane [E: tools/measure_skin_line.py, output recorded in docs/research/measurements/2026-07-23-skin-line.md]

Solved exactly from the NTSC 1953 luma and YIQ chroma matrices, worst residual
3.89e-16:

| Plane | +I axis | +Q axis | +I distance from 123 |
|---|---|---|---|
| unscaled B-Y, R-Y | 110.073 | 49.098 | 12.927 |
| BT.601 Cb, Cr | 106.125 | 55.573 | 16.875 |
| BT.709 Cb, Cr | 107.230 | 53.677 | 15.770 |

**The common explanation is wrong.** The I axis lands between 106 and 110 degrees
depending on the plane, never within 12 degrees of 123. Whatever the skin line
is, it is not the I axis.

## Result 2: real skin does land on 123 degrees, in the BT.709 Cb/Cr plane

Six published skin reflectances rendered under six illuminants, white balanced to
D65, encoded to Rec.709 and projected onto the vectorscope plane. Sources: ISO
17321-1 `dark skin` and `light skin`, and the four skin patches of the PMC chart,
`Caucasian`, `Oriental`, `South Asian`, and `African`. colour-science attributes
the PMC dataset to doi:10.1002/col.22940, recorded in
`references/CITATIONS.yaml` as `pmc-chart-luo-2024`.

| Plane | mean skin direction | distance from +I | distance from 123 |
|---|---|---|---|
| unscaled B-Y, R-Y | 126.659 | 16.585 | 3.659 |
| BT.601 Cb, Cr | 120.554 | 14.429 | 2.446 |
| **BT.709 Cb, Cr** | **122.324** | 15.094 | **0.676** |

So the folklore has **the right number attached to the wrong derivation**. The
123 degree line is an empirically good description of where skin falls, accurate
to 0.68 degrees in the BT.709 Cb/Cr plane that a modern vectorscope actually
draws, and it is 15 degrees away from the NTSC axis it is usually credited to.

That distinction matters practically. A target justified as "the I axis" would be
15 degrees wrong. A target justified as "measured skin" is close to right. Same
number, different provenance, and only one of them survives being checked.

## Result 3: the target the scorecard gates on, in Oklab

The vectorscope angle is what a colourist reads. The gated statistic is the Oklab
hue angle, chosen on the Munsell evidence in
`references/color-theory/uniform-spaces-for-grading.md`. Both come from the same
rendering, so they cannot disagree through a pipeline accident.

Oklab hue angle, degrees:

| Sample | D65 | D55 | D50 | A | FL2 | FL11 | Oklab chroma at D65 |
|---|---|---|---|---|---|---|---|
| ISO 17321-1 dark skin | 43.45 | 42.96 | 42.61 | 40.84 | 57.73 | 45.56 | 0.05651 |
| ISO 17321-1 light skin | 45.41 | 43.42 | 42.19 | 36.27 | 55.45 | 43.57 | 0.06340 |
| PMC Caucasian | 41.64 | 41.20 | 40.92 | 40.91 | 56.05 | 41.96 | 0.07793 |
| PMC Oriental | 42.94 | 42.52 | 42.25 | 42.48 | 57.77 | 42.77 | 0.07640 |
| PMC South Asian | 42.24 | 41.83 | 41.56 | 41.41 | 56.12 | 40.71 | 0.07328 |
| PMC African | 42.74 | 42.52 | 42.38 | 43.32 | 57.02 | 40.09 | 0.06854 |

Pooled over all 36 combinations: mean 44.565 degrees. Excluding FL2, which is
discussed below: **mean 42.157 degrees, spread -5.89 to +3.40, n = 30**.

## The two skin groups are not the same kind of thing, and pooling them was wrong

An earlier draft treated all six skin reflectances as one set. They are not.

- **ISO 17321-1 `dark skin` and `light skin`** are ColorChecker patches, designed
  to simulate the spectral reflectance of natural objects. Accuracy oriented.
- **The four PMC patches** come from a chart whose own title is the *preferred
  memory colour* chart. Its Crossref abstract states it "comprises 30 colored
  patches, divided into three groups: preferred memory colors, reference
  colour-gamut colors, and a gray scale", and that its purpose is "to enable
  users to produce satisfactory preferred color reproduction".

**This inference is strong but it is an inference.** The four skin patches are
memory colours of familiar objects, they are not gamut primaries, and they are
not greys, so they belong to the first group. That was reasoned from the patch
names and the abstract's structure, **not read from the paper**. The paper is
open access under CC BY, confirmed through Unpaywall, and the publisher returns
HTTP 403 to automated requests, so it could not be read here. Until it is, treat
the group assignment as unverified.

Separated, and computed at D65:

| Group | n | Oklab hue, degrees | Oklab chroma |
|---|---|---|---|
| ColorChecker, accuracy oriented | 2 | 44.433 | 0.05996 |
| PMC, preferred | 4 | 42.391 | 0.07404 |

**Preferred skin measures 23.5 percent more chromatic than accurate skin, and
2.04 degrees lower in hue.**

That direction is exactly what the memory-colour literature reports, that
remembered and preferred colours of familiar objects are more saturated than the
objects actually are. This measurement did not set out to test that and was not
told about it, so reproducing it is a check on the method rather than a result
claimed from it.

**How much weight this carries: not much on its own.** Two samples against four,
from two different datasets produced by different groups for different purposes.
The 23.5 percent gap could be a preferred-versus-accurate effect, or a difference
between the two datasets, and nothing here separates those. What it does do is
make the direction of the correction credible and give a first estimate of its
size, which is more than the project had before.

**Why it matters practically.** If preferred skin chroma really is above accurate
skin chroma, then a grade that lands on the accurate value is already under
target, and the motivating clip's measured skin chroma of roughly half natural is
further from a good deliverable than an accuracy comparison suggests.

## An asymmetry between hue and chroma, and exactly how far it can be pushed

Under D65 the four PMC category exemplars, Caucasian, Oriental, South Asian, and
African, fall at 41.64, 42.94, 42.24, and 42.74 degrees of Oklab hue, and at
0.07793, 0.07640, 0.07328, and 0.06854 Oklab chroma.

An earlier draft of this file compared "1.30 degrees of hue spread" against "a
factor of 1.14 in chroma" and concluded hue was category-independent while chroma
was not. **That comparison was between an angle and a ratio, which are not
comparable units, and the conclusion drawn from it was stronger than the data
supports.** Corrected, on the coefficient of variation, which is like for like:

| Quantity | n | mean | sample sd | CV |
|---|---|---|---|---|
| PMC hue, degrees | 4 | 42.390 | 0.580 | 0.0137 |
| PMC chroma | 4 | 0.07404 | 0.00414 | 0.0560 |

Chroma varies **4.09 times as much as hue** across these four exemplars. The
direction of the asymmetry survives the correction. Its strength does not survive
the next question.

**The limit that matters: there is one exemplar per category, so there is no
within-category variance at all.** Without it, nothing here can say whether a
1.30 degree between-category hue spread is small *relative to* the variation
among real people within any one category. It might be, and the asymmetry would
then be a real population fact. It might not be, and then the four exemplars are
simply four samples. This measurement cannot distinguish those.

So the defensible statement is narrow: **among these six published reflectances,
hue varies about four times less than chroma.** That is a description of the
swatches, not an established property of human skin, and
`docs/evaluation-harness.md` treats it as provisional for exactly that reason.

**What would settle it.** `issa-lu-2025` in `references/CITATIONS.yaml` is a
skin-spectra archive whose record title reports a multicultural collection, which
if usable would supply the within-category distributions this measurement lacks.
Its licence and contents are not yet verified and it has not been downloaded.
Until that is done, the conditioning decision in the harness specification stands
on four exemplars and says so.

## What varies, and where the target stops being usable

- **Illuminant dominates.** Under illuminant A, light skin drops to 36.27
  degrees in Oklab, 5.9 degrees below the pooled mean. That is the widest
  legitimate deviation among the non-fluorescent illuminants.
- **FL2 breaks it.** Every sample shifts to between 55.45 and 57.77 degrees under
  FL2, roughly 14 degrees off, and to about 130 degrees on the vectorscope. FL2
  is a spiky cool-white fluorescent and this is metameric failure, not a grading
  defect. A skin hue target must therefore **not be applied to footage shot under
  narrow-band sources without a stated caveat**, and the harness should say so
  rather than reporting a 14 degree error on correctly reproduced skin.

## Bounds on all of the above

- Six reflectances. This measures where these published samples fall, not where
  all human skin falls. The PMC categories are the dataset's own names.
- Spectral rendering only, with no camera spectral sensitivities, no encoder, and
  no compression. Real footage adds error this measurement does not see.
- These are **accurate** reproduction values, meaning what skin measures. The
  **preferred** target for a deliverable is a different and generally more
  saturated thing, per the memory-colour literature. The chroma column above is
  therefore the accurate baseline, not the number a grade should aim for. Setting
  the preferred chroma target needs `preferred-skin-zeng-luo-2011` read, which
  has not been done.
- The white balance step assumes a correctly balanced camera. What happens when
  it is not is measured separately in
  `references/color-theory/white-balance-accuracy-measured.md`.
