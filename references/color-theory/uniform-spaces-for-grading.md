# Uniform colour spaces for grading operations

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Which space should a grading operation work in? The question matters because a
saturation change applied in the wrong space is also a hue change, and a hue
change on skin is the defect a viewer notices first.

This file records what has been measured in this repository so far and names what
has only been located, not yet read. Nothing here should be read as a claim about
what any cited paper says: the citations below are verified to exist and to be
the works named, at `claim_depth: identifier_only` in
`references/CITATIONS.yaml`. Where this file states a number, that number came
from a script in this repository, not from a paper.

## The problem, stated precisely

Take a colour and increase its colourfulness while holding its perceived hue.
Every uniform colour space claims to represent hue as an angle in a plane, so the
operation should be "increase the radius, hold the angle". Spaces differ in how
well their angle actually tracks perceived hue. Where the angle drifts, holding
it constant does not hold hue constant, and scaling the radius drags hue with it.

The tool's v1 saturation operator, `corrections._saturate`, scales the distance
from a Rec.709 luma along each RGB axis in the log grading space. That is not a
uniform space and its angle is not a hue angle, so hue drift under saturation is
expected rather than surprising. It is quantified in the last section below.

## What was measured [E: tools/measure_hue_linearity.py, output recorded in docs/research/measurements/2026-07-23-hue-linearity.md]

The evaluation is the standard one from the hue-linearity literature, and it is
deliberately not self-referential. Asking "how far does the hue angle in space X
move when I scale chroma in space X" answers itself: zero, by construction. The
external reference used instead is the Munsell renotation, in which colours are
placed by human observers. A group of Munsell samples sharing a hue and value and
differing only in chroma is a perceptual constant-hue locus. A space with good
hue linearity reports a near-constant angle along such a locus.

Measured quantity: the peak-to-peak wander of the hue angle along each locus, in
degrees, computed with circular statistics about the locus mean direction.

Corpus: the Munsell renotation "real" set, restricted to loci with at least four
distinct chromas. That gives 304 loci over 2602 samples.

Stated choices, all of them parameters of the script rather than buried
constants: the renotation is specified under illuminant C, so samples are adapted
to D65 for every D65-referred space; CIELAB is evaluated under illuminant C
natively so it is not penalised for an adaptation it does not need; Jzazbz is
absolute-referred and is fed a diffuse white of 100 cd/m2; CAM16 uses L_A 20,
Y_b 20, average surround.

### Result, all hues

Median wander in degrees, lower is better:

| Space | median | p90 | worst | worst locus |
|---|---|---|---|---|
| Oklab | 3.796 | 9.076 | 32.539 | 5PB 3/ |
| CAM16-UCS | 3.993 | 11.113 | 37.649 | 7.5PB 1/ |
| Jzazbz | 4.329 | 8.891 | 19.783 | 5PB 4/ |
| ICtCp | 4.785 | 9.559 | 16.282 | 5PB 4/ |
| IPT | 4.895 | 11.627 | 18.870 | 5PB 3/ |
| CIELAB | 5.160 | 10.370 | 27.723 | 7.5PB 1/ |

### Result, restricted to the hue families that carry skin

Skin reflectance places skin in the red to yellow-red arc, so the global median
is the wrong summary for this project's purpose. Restricted to the R, YR, and Y
families:

| Space | median wander, degrees |
|---|---|
| Oklab | 3.618 |
| CAM16-UCS | 4.064 |
| Jzazbz | 4.694 |
| CIELAB | 5.250 |
| ICtCp | 5.871 |
| IPT | 7.359 |

### Robustness

The ranking is unchanged under four different chromatic adaptation transforms
used for the illuminant C to D65 step: CAT02, Bradford, CAT16, and classical von
Kries. Oklab is first and IPT last in all four. The skin-family medians move by
at most 0.6 degrees across the four.

## What this supports, and what it does not

**Supported.** Among these six spaces, Oklab has the best hue linearity in the
hue families where skin lives, and the result does not depend on the adaptation
transform. On this measurement it is the best-supported space for a skin hue
target and for a chroma-scaling operator that must not move hue.

**Supported, and counterintuitive enough to state plainly.** IPT is the worst of
the six in the skin families, at roughly twice Oklab's wander, despite IPT being
the space most often reached for when hue uniformity is the stated goal. Picking
IPT on reputation would have been a measurable mistake.

**Supported, and worth noting as a check on the method.** Every space's worst
locus falls in the purple-blue region. The measurement was not told to look
there. The blue region is the failure that the constant-hue literature reports,
so the method rediscovering it without being pointed at it is evidence the method
is measuring the thing it claims to measure.

**NOT supported: that space choice matters a great deal.** The six spaces span
3.6 to 7.4 degrees of median wander in the skin families, and 3.8 to 5.2 over all
hues. That is a real difference and it justifies choosing Oklab over IPT, but it
is not the order-of-magnitude gap the framing of "use a perceptually uniform
space" sometimes implies. A grading defect of tens of degrees, such as the 5
degree skin hue error and the 51 code-value neutral split recorded on the
motivating clip, is not going to be fixed by the choice of space alone.

**NOT supported: anything about HDR or wide gamut.** The Munsell renotation is a
set of surface colours under a diffuse illuminant. Nothing here transfers to PQ
or to BT.2020 primaries without a separate measurement.

**NOT claimed: that this reproduces any published ranking.** The literature on
this question has been located but not yet read: Zhao 2020 on hue linearity
across spaces for wide gamut and HDR media, Wang 2022 on constant hue loci in
Rec.2020, Hung and Berns 1995 on constant hue loci and their prediction, and
Lissner and Urban 2012. Whether their rankings agree with this one is an open
question, and comparing them is the next step. Until that is done, this file
claims only what the script measured on this machine.

## How far v1's own saturation control moves skin hue [E: tools/measure_saturation_hue_drift.py, output recorded in docs/research/measurements/2026-07-23-saturation-hue-drift.md]

Method: render the ISO 17321-1 skin patches under D65 to Rec.709 display code,
run them through v1's actual chain (`shaper`, then `_saturate`, then
`inverse_shaper`, then `bt1886_encode`), and measure the Oklab hue angle before
and after. The Oklab comparison arm is matched on the chroma ratio v1 actually
delivered, not on the nominal knob setting, because the two controls do not
deliver equal chroma change for equal numbers.

| v1 saturation | delivered chroma ratio | dark skin hue drift | light skin hue drift |
|---|---|---|---|
| 0.75 | 0.74 | +1.637 deg | +1.300 deg |
| 1.25 | 1.27 | -1.508 deg | -1.233 deg |
| 1.50 | 1.55 | -2.892 deg | -2.396 deg |
| 2.00 | 2.13 | -5.322 deg | -4.518 deg |

Negative is a rotation toward magenta. Raising v1's saturation rotates skin away
from yellow, and the drift grows with the setting.

**Read the zero column honestly.** The matched Oklab chroma scale shows 0.000
degrees of drift at every setting, and that is definitional, not a finding: the
scale was applied in Oklab and the angle was measured in Oklab, so it cannot be
anything else. The zero is a baseline showing what "no drift in the measurement
space" looks like. What makes the v1 numbers meaningful as an estimate of
PERCEIVED hue drift is the separate Munsell measurement above, which is where the
evidence for Oklab tracking perceived hue in the skin families comes from.

**Why the size matters.** At saturation 2.0 the operator moves skin hue by
roughly 5 degrees. The motivating clip's measured skin hue error was about the
same magnitude. So on that clip, turning global saturation up far enough to fix
the chroma deficit would have introduced a hue error comparable to the one
already being corrected. That is consistent with the recorded observation that
raising global saturation made the cast worse, and it means the chroma and hue
dimensions of the scorecard cannot be treated as independently correctable with
v1's controls.

## Located but not yet read

Every entry below is identifier-verified in `references/CITATIONS.yaml` and has
`claim_depth: identifier_only`. They are listed so the next reader knows where to
go, not as support for any statement above.

- Hue linearity evaluations: `hue-linearity-zhao-2020`, `constant-hue-wang-2022`,
  `constant-hue-hung-berns-1995`, `unified-space-lissner-urban-2012`.
- Space definitions: `ipt-ebner-fairchild-1998`, `jzazbz-safdar-2017`,
  `cam16-li-2017`, `cam02ucs-luo-2006`. ICtCp is defined in BT.2100 and Oklab is
  a published derivation whose locator is not yet in the ledger.
