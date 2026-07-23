# The evaluation harness: specification

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Status: SPECIFICATION, not implementation.

- v1 written 2026-07-23, before any code.
- v2 written 2026-07-23 after independent review. The review is reproduced at
  `docs/reviews/2026-07-23-evaluation-harness-review.md` and its verdict was
  "revise the specification before implementation". Section 14 lists what changed
  and what was rejected.
- v3 written 2026-07-23 after a second review of v2. Verdict again "revise before
  implementation", and again acted on. Section 13 lists what changed. Two rounds
  of review have each found a null metric that passed the then-current validation
  plan, which is the strongest available evidence that the plan is a growing set
  of defences rather than a proof.

## 1. Why this exists

`README.md` currently contains this admission:

> The shipped gate values are unvalidated defaults. They are not the output of a
> published validation study, and there is no corpus, labeled dataset, false-pass
> rate, or reproducible report in this repository to back them.

That is honest, and it is also the ceiling on what this project can claim. A tool
cannot be argued to be better without an instrument that says what better means.
Every v2 capability, starting with spatial secondaries, has to be justified
against a number produced here, or it is a feature nobody can check.

The harness has one job: **given a delivery, and optionally the authenticated
source it was graded from, produce a per-dimension measurement of how good a
professional deliverable it is, and refuse to produce one where the evidence or
the applicability is absent.**

## 2. What the harness is NOT

- It is not a quality gate. Gates decide pass or fail on one delivery. The
  harness scores, compares, and ranks, which is a different job.
- It is not a replacement for a colourist's eye. It is a ruler, and section 9
  tests the ruler before anything is judged with it.
- **It is not a taste-free measurement, and v1 of this document was wrong to
  imply it could be.** Several things a colourist cares about, skin chroma most
  obviously, have no colorimetric ground truth: there is only measured human
  preference. The harness handles that by *naming the authority for every
  target* rather than by pretending targets are facts. A score against a
  published preference model is reported as conformity to that named model, never
  as correctness in general.

## 3. Every target declares its basis and its conditioning

This replaces v1's ABSOLUTE / RELATIVE / DECLARED taxonomy, which the review
correctly showed was not three mutually exclusive kinds. v1 was already writing
"DECLARED, with an ABSOLUTE band", which is two axes wearing one label. They are
now two fields, plus a third for state.

### 3.1 Target basis: where the number's authority comes from

| Basis | Meaning | Requirement |
|---|---|---|
| `delivery_standard` | A delivery specification or a colorimetric definition makes this true independent of content. | Cite the standard. |
| `source_reference` | The target is derived from the same clip's authenticated pre-grade source. | An authenticated source, and a stated direction of improvement that is defensible rather than "more is better". |
| `measured_reflectance` | The target is where published spectral reflectances render under stated conditions. A colorimetric fact about specific samples. | Name the dataset, the observer, the illuminant, and the rendering path. State the sample count. |
| `perceptual_population` | The target comes from a published study of what human observers prefer or perceive. | Cite the study, name it in the report, and state the population and viewing conditions it was measured under. |
| `declared_intent` | The target encodes a creative or delivery decision the operator states. | The declaration is recorded verbatim in the report. |

`measured_reflectance` was added after the second review, which caught a category
error: skin hue was labelled `perceptual_population` while its evidence was
spectral renderings of chart patches. Those establish where those reflectances
render. They say nothing about what observers prefer, and the measurement file
itself says so. Merging the two would have let a colorimetric fact masquerade as
a preference study, which is the exact confusion section 2 exists to prevent.

The distinction is not pedantic. `measured_reflectance` gives an **accurate**
target, `perceptual_population` gives a **preferred** one, and for skin they are
known to differ.

A dimension with no basis it can name does not get a score.

### 3.2 Conditioning: facts that must be supplied before a target can be selected

Separate from basis. A `perceptual_population` band for skin chroma still needs
to know which skin category. A `declared_intent` black target still needs to know
whether the look is high key. Conditioning facts are always operator-supplied and
always recorded. **The harness never infers a conditioning fact from the graded
delivery**, because a miscorrected image would then select the target that
excuses its own error.

### 3.3 Evidence and applicability state

Four states, distinguished because collapsing them is what made v1's composite
rule wrong:

| State | Meaning |
|---|---|
| `MEASURED` | Evidence present, statistic computed, target available, score produced. |
| `NOT_APPLICABLE` | The operator affirmatively declared this dimension does not apply. Landscape footage has no skin, and that is not a defect. |
| `EVIDENCE_ABSENT` | The dimension applies but the evidence was not found, for example skin is expected and no usable ROI exists. **Nothing was measured.** |
| `MEASUREMENT_INVALID` | Evidence was found but the statistic is undefined on it, for example a hue angle below the chroma floor of section 5.4. |
| `TARGET_UNAVAILABLE` | **The statistic was measured successfully, but no target with a nameable basis exists to score it against.** The value is reported; no score is. |

`TARGET_UNAVAILABLE` was added after review. An earlier draft used
`EVIDENCE_ABSENT` for both "we could not measure it" and "we measured it but have
nothing defensible to compare it to", which are different facts with different
remedies: the first needs better footage or a better ROI, the second needs a
citation. Skin chroma today is exactly the second case, and calling it absent
evidence would have hidden a perfectly good measurement behind a word that says
the measurement failed.

A `TARGET_UNAVAILABLE` dimension always reports its measured value. It never
contributes a score, and section 7 treats it like any other unscored dimension
when deciding whether a composite exists.

`NOT_APPLICABLE` must be declared. It is never inferred from a failed detection,
because "we could not find skin" and "there is no skin" are different facts and
only one of them is good news.

**A declaration alone is not enough, and the second review was right that it was
a hole.** As first written, declaring "no skin here" removed the three skin
dimensions and opened a composite with a smaller denominator. That makes the
worst-scoring dimensions removable by assertion, which is a way to buy a better
number by saying so, and this project cannot ship that.

So applicability splits by who can know it:

- **Factual applicability is attested, not declared.** When an authenticated
  source is available, the harness checks the source ROI for skin evidence. If it
  finds skin and the operator declared `NOT_APPLICABLE`, the run is an ERROR
  naming the conflict. The operator may be right and the detector wrong, but that
  is resolved by fixing the ROI, not by overriding the evidence.
- **Creative intent stays declarative**, because no detector can know it. The key
  level in 5.2 and the same-object assertion in 5.5 are the operator's to state.

With no authenticated source there is nothing to attest against, so a
`NOT_APPLICABLE` skin declaration is accepted and the report records that it was
accepted **unattested**. That fact travels with the composite.

## 4. Aggregation, defined before any statistic uses it

The review was right that section 11 of v1 asked which sampling density to use
while never saying how a pixel becomes a clip score. Settled here.

1. **Pixels to mask, within a frame set.** All sampled frames' masked pixels are
   pooled and one median is taken. This is what `measure._measure_mask` already
   does and it is kept.
2. **Minimum support.** A mask statistic is evidence only when the mask covers at
   least `MIN_MASK_PIXELS` pixels in at least `MIN_MASK_FRAMES` sampled frames.
   Below either floor the dimension is `EVIDENCE_ABSENT`, not a noisy number.
   Both floors are declared in the scoring file, not hardcoded.
3. **Regions within a mask.** Neutral disagreement is the **maximum over all
   region pairs** of the pairwise difference, not the range of a projected axis.
   Pairwise is the quantity that means "these two patches do not match".
4. **Masks to shot.** One score per dimension per shot.
5. **Shots to clip.** The headline is the **duration-weighted mean over shots**,
   and the **worst shot is always reported beside it**. Neither is allowed to
   appear alone. A duration-weighted mean alone hides a bad two-second shot; a
   worst-shot alone lets one shot condemn a programme.
6. **Circular quantities.** Hue is aggregated by mean direction, and its spread
   is reported as angular deviation about that direction. Never as an arithmetic
   mean of degrees.

## 5. The scorecard

Six dimensions, retained so results stay comparable with the manual scorecard
that motivated this work.

### 5.0 Note on technical conform, resolving an arithmetic contradiction in v1

v1 demoted technical conform from a score to a precondition while also claiming
the composite stayed comparable with the manual 5.5. The review showed that is
false: the six manual scores sum to 33 for 5.5, and the remaining five sum to 24
for 4.8.

Resolution: technical conform is **both**. It is scored, so the composite stays
on the same six-dimension scale, and it is additionally a precondition that
refuses the composite. Those are not in conflict.

**What comparability does and does not mean, stated once so nothing downstream
overclaims it.** The composite is a six-dimension unweighted mean on 0 to 10,
which is the manual scorecard's shape, so the two are read side by side without
conversion. It will **not reproduce the manual value exactly**. The manual
scorecard scored technical conform 9 against no defined scale; the defined scale
in 5.1 gives a conformant delivery 10, which alone moves the motivating clip from
5.5 to 5.667. Chasing exact reproduction would mean reverse-engineering scales
from six numbers, which is curve fitting, not measurement.

What must hold is **ordering and per-dimension direction**, and that is what
section 9 property 4 tests. Any claim that the harness reproduces 5.5 is wrong
and should be removed wherever it appears.

### 5.1 Technical conform

Three sub-checks, because they do not share a basis:

| Sub-check | Basis | Notes |
|---|---|---|
| Colour tags match the declared output profile | `delivery_standard` | Reuses v1's hard gate unchanged. |
| Decoded sample extrema legal for the declared range | `delivery_standard` | Reuses v1's hard gate unchanged. |
| Grade-introduced clipping | `source_reference` | **Needs an authenticated source.** Without one it is `EVIDENCE_ABSENT`, not a pass. The 0.5 percent threshold lives in the gate preset and is a project convention, not a cited delivery invariant, and the report says so. |

The composite refuses on technical FAIL **and** on technical
`EVIDENCE_ABSENT`, which v1 failed to state.

**The numeric rule, which v2 asserted a score without giving.** Technical conform
is the only dimension whose inputs are pass/fail rather than continuous, so it
does not use the section 6 deviation mapping. It scores:

| Condition | Score |
|---|---|
| all three sub-checks pass | 10 |
| tags and range pass, introduced clipping is `EVIDENCE_ABSENT` | no score; the composite refuses |
| any sub-check fails | 0 |

There is no partial credit and there are no intermediate values. A delivery with
wrong colour tags is not 70 percent conformant, it is non-conformant, and a scale
that says otherwise would let a broken file average its way to a respectable
composite.

This does mean a passing delivery scores 10 here where the manual scorecard gave
9. The manual 9 was a judgement about a dimension with no defined scale; this is
the defined scale. Section 7 records the consequence for comparability.

### 5.2 Skin luma placement

Basis: `declared_intent`, conditioned on the declared key level. Optionally
cross-checked against `source_reference`.

Statistic: median Rec.709 luma over the frozen skin mask, in IRE.

**v1 of this document proposed deriving an absolute band from published skin
lightness data. That was wrong and the reasoning is worth keeping visible.**
Surface reflectance does not determine rendered display luma. The same person is
legitimately placed at 35 IRE in a low-key scene and 65 IRE in a high-key one,
and declaring a skin tone category supplies neither the lighting nor the exposure
intent. Chardon 1991 and Xiao 2016 measure skin, not how skin should be exposed.

So there is no absolute skin luma target here. What the harness offers instead:

- the measured value, always;
- a score against a band the operator declares, when they declare one, recorded
  as their convention rather than as colorimetry;
- and a `source_reference` cross-check on whether the grade moved skin luma in
  the direction the operator asked for.

With no declaration, the dimension reports the number and scores
`EVIDENCE_ABSENT` for the target. It does not invent a middle band.

### 5.3 Skin hue

Basis: `measured_reflectance`, **not** `perceptual_population`. The evidence is
where six published reflectances render, not what any observer preferred. This is
therefore an accuracy target, and if the preferred skin hue turns out to differ
from the accurate one, this dimension changes basis and target together.

Conditioning: **on illuminant class, and provisionally not on skin category.**

Across the four PMC category exemplars under D65, Oklab hue spans 41.64 to 42.94
degrees while chroma varies about four times as much on a coefficient-of-variation
basis, 0.0137 against 0.0560. Pooled over six reflectances and five illuminants
excluding FL2 the hue mean is 42.157 degrees, spread -5.89 to +3.40. Recorded in
`references/color-theory/skin-targets-measured.md`.

**This is provisional, and the reason is a real limit, not a formality.** There
is one exemplar per category, so there is no within-category variance estimate,
and the data therefore cannot show that between-category hue spread is small
relative to variation among real people in one category. Dropping the
conditioning is the choice the available evidence best supports, not a settled
result. It is revisited if `issa-lu-2025` turns out to be usable, since a
multi-subject archive would supply the missing distributions.

Practically the choice is low risk: an unconditioned hue target that proves wrong
becomes a conditioned one without changing any other part of the scorecard.

**Illuminant conditioning is NOT optional, and an earlier draft wrongly implied
the target was unconditioned in every respect.** The non-FL2 measurements span
36.27 to 45.56 degrees, and that 9 degree range is driven almost entirely by the
illuminant: light skin under tungsten sits at 36.27 where the same reflectance
under D65 sits at 45.41. A single unconditioned number would score correctly
reproduced tungsten skin as a 9 degree error. So the target is stated for
correctly adapted capture referred to D65, the operator declares the illuminant
class, and narrow-band sources are `NOT_APPLICABLE` per the paragraph below.

**Narrow-band sources are out of scope for this target.** Under FL2 every sample
shifts about 14 degrees, which is metameric failure and not a grading defect. The
harness must report `NOT_APPLICABLE` rather than a 14 degree error when the
operator declares a narrow-band source.

The Cb/Cr vectorscope angle reported beside it is now grounded rather than
inherited: measured skin sits at 122.324 degrees in the BT.709 Cb/Cr plane,
0.676 degrees from the conventional 123. The usual explanation for that line, the
NTSC YIQ I axis, is wrong by 15 degrees; the I axis is at 107.230 degrees in the
same plane. The number survives checking, its folklore derivation does not.

Space: **Oklab**, on measured evidence rather than reputation. Munsell
constant-hue loci give Oklab the least hue wander of six candidate spaces in the
R, YR, and Y families that carry skin, at 3.618 degrees against IPT's 7.359, and
the ranking is stable under four chromatic adaptation transforms. Recorded in
`references/color-theory/uniform-spaces-for-grading.md`. The Cb/Cr vectorscope
angle is reported beside it for communication, as
`references/color-theory/color-difference.md` already does for delta E.

**The ROI must not come from the graded delivery.** This is the circularity the
review caught, and it is fatal if unaddressed: `measure._skin_mask` selects
candidates by HSV hue between 5 and 45 degrees, so a delivery whose skin hue is
badly wrong drops out of its own evidence set while orange wood joins it. The
harness therefore:

- derives the skin ROI from the **authenticated source**, and stages it onto the
  delivery, which is what `verify._stage_masks` exists for;
- **requires that staging to be identity-checked**, which it currently is not.
  `_stage_masks` confirms an `identity_json` member exists but never parses or
  compares it, so a same-sized mask from unrelated media is accepted. Fixing that
  is a prerequisite of this dimension, not an optional cleanup;
- or accepts an operator-supplied ROI, recorded;
- and reports `EVIDENCE_ABSENT` when neither is available. It does not fall back
  to qualifying the delivery.

### 5.4 Skin chroma

Basis: `perceptual_population`, conditioned on the declared skin category.

Statistic: **the median over masked pixels of per-pixel Oklab chroma.** Not the
chroma of the pooled median RGB. The two differ on heterogeneous skin, and the
existing code already keeps that distinction deliberately: `MaskStat` carries a
pooled `median_rgb` and separately a median of per-pixel HSV saturation. The
second review flagged the phrase "chroma of the skin mask median" as ambiguous
between them, and it was. Section 5.3's hue uses the same per-pixel convention,
aggregated by mean direction per section 4.

**Conditioning is retained here, unlike 5.3, and the reason is asymmetric risk
rather than a settled measurement.** The four PMC exemplars under D65 measure
0.07793, 0.07640, 0.07328, and 0.06854 Oklab chroma, four times more variable
than their hue on a coefficient-of-variation basis, but from the same one
exemplar per category and so subject to the same limit stated in 5.3.

The two dimensions resolve the same weak evidence in opposite directions on
purpose. Dropping conditioning where it is not needed costs nothing if wrong, and
is corrected by adding it back. Dropping it where it IS needed would bake a
single skin chroma target into a tool used on every skin tone, which is the more
damaging error. So chroma keeps its conditioning until there is evidence it can
safely lose it.

Those figures are the **accurate** reproduction baseline, meaning what skin
measures. They are not the target. A deliverable should reach the preferred
value, which is generally higher.

This dimension measures **conformity to a named published preference model**. It
is not a colorimetric fact and the report says which model it used. Preferred
skin is systematically more saturated than measured skin, which is why an
accurately balanced grade can look lifeless, and that preference is exactly what
a deliverable should hit.

**Status of the target, checked 2026-07-23.** Two routes, and the situation
changed since v2 of this document:

- **Zeng and Luo 2011** was the expected source of a tolerance band. Unpaywall
  reports it closed, so it cannot be read here. Its Crossref abstract does
  confirm it contains "hue and chroma tolerances" of observer skin preference,
  and that it works in the CIELAB a\*b\* plane, so a band taken from it would
  need converting to Oklab. The values remain unobtainable.
- **The PMC chart** may supply a target CENTRE without it. colour-science ships
  the chart's spectra, its four skin patches measure 23.5 percent more chromatic
  than the accuracy-oriented ColorChecker skin patches, and that direction
  matches the memory-colour literature. Recorded in
  `references/color-theory/skin-targets-measured.md`.

**Neither route is usable yet, and the reason is specific.** The PMC route
depends on the four skin patches belonging to the chart's preferred-memory-colour
group, which is currently inferred from the patch names and the abstract's
three-group structure rather than read from the paper. The paper is open access
under CC BY and the publisher returns HTTP 403 to automated requests. That single
unread fact is what stands between this dimension and a target centre.

Even with the centre, a centre is not a band, and the tolerance would still be
missing. So this dimension reports its measured value and `TARGET_UNAVAILABLE`
until at least the centre is confirmed, and reports a score only once a band has
a nameable basis too.

**Chroma floor.** Hue is undefined at zero chroma and unstable near it. Below
`MIN_CHROMA_FOR_HUE`, declared in the scoring file, section 5.3 reports
`MEASUREMENT_INVALID` rather than a meaningless angle.

### 5.5 Neutral consistency

Basis: `declared_intent`. **Changed from ABSOLUTE after review.**

Statistic: the maximum over region pairs of the disagreement between frozen
neutral region medians, reported in two units: per-region R minus B and green
balance in 8-bit code, and CIEDE2000 between the region medians.

v1 argued this was absolute because "two patches of the same physical white
object should render to the same colour, that is what neutral means". The review
is right that this overreaches. Two white areas under different motivated
illuminants need not match, and forcing a warm practical and a cool window to a
common white can destroy correct scene lighting. The tool also cannot know that
two candidate patches belong to one physical object.

So the same-object relationship is **declared**, and the harness scores
disagreement only between regions the operator has asserted are one object that
should match. Undeclared regions are measured and reported, never scored.

This keeps the motivating case fully in scope. A single white shirt reading
positive R minus B on the warm-lit upper body and negative in the cool-fill chest
is one declared object, and the residual disagreement after grading is exactly
what spatial secondaries are meant to reduce.

Two implementation notes the review surfaced:

- `measure.RegionStat` does **not** currently store signed differences. It stores
  `np.median(np.abs(...))`. v1 of this document claimed otherwise and was wrong.
  Signed per-region differences are reconstructed transiently for multimodality
  detection only. New primitives are needed.
- CIEDE2000 **is** available and already used, at `verify.py:1279`, via
  `colour.delta_E(..., method="CIE 2000")`. The review stated it was not
  implemented and this document repeated that; both were too broad. What is
  missing is its application between neutral region medians in `measure.py`, not
  the capability.

### 5.6 Tonal shaping

Three sub-measures.

**5.6a Black placement.** Basis: `declared_intent`. p1 luma against a target the
operator declares. Not absolute: a high-key or faded look legitimately has no
display black.

**Letterbox and pillarbox must be excluded before any luma percentile is
computed.** Bars occupying one percent of the frame produce a perfect p1
regardless of the photographed image, which would silently satisfy this
sub-measure on a matted delivery. This applies to 5.6b and 5.6c as well.

**5.6b Highlight handling.** Basis: `source_reference`. **Changed after review.**

v1 scored "did the grade preserve or improve the source's p99", and the review is
right that larger is not better: a good highlight roll-off reduces p99 while
preserving more usable detail. The defensible quantity is not reach, it is
**retained highlight distinguishability**.

**Operational definition, since the phrase alone is not computable.** Let the
source highlight band be the source pixels between its p90 and its maximum,
measured in the unclipped working-linear domain per the note below. Partition
that band into `HIGHLIGHT_BINS` equal-population quantile bins, so each bin holds
the same number of source pixels regardless of the source's distribution. For
each bin, take the corresponding delivery pixels and compute the interquartile
range of their output code values. A bin is **retained** when that range is at
least one code value, and **collapsed** when it is below that.

The statistic is the fraction of bins retained. Clipping collapses the top bins
and scores badly. A roll-off compresses them while keeping them separable and
scores well, even though it lowers p99. Both `HIGHLIGHT_BINS` and the one-code
threshold are declared in the scoring file.

**Grain defeats the naive version of this, and the fix is part of the
definition.** Noise added after a highlight has already collapsed still produces a
spread of output codes, so a plain within-bin range would call a clipped
highlight retained and would also break the grain invariance required by section
9 property 7. Retention is therefore judged on **between-bin separation, not
within-bin spread**: a bin is retained when its median output code differs from
the next bin's median by at least the threshold. Noise is zero-mean and moves
bin medians far less than it moves bin ranges, so a monotone tone curve keeps
its bins ordered and separated while clipping merges their medians whatever the
grain does.

The residual sensitivity is that very heavy noise relative to bin spacing will
still blur medians. Property 7 states the grain amplitude the statistic is
required to survive, and beyond it the dimension reports `MEASUREMENT_INVALID`
rather than a number it cannot stand behind.

This needs the source and delivery pixels to correspond per pixel, which the
harness already requires for introduced clipping, and it inherits that
requirement's registration limits from section 12.

**The source side must be measured in a domain that does not clip.**
`measure._to_measurement_rgb` routes log sources through `bt1886_encode`, which
clips linear to 0 to 1 first, so a log source carrying highlights above display
white reports p99 = 255 before grading. Comparing against that would reward
pushing the grade toward white. Source-relative highlight statistics are computed
in the working linear domain instead.

**5.6c Mid-tone separation.** Basis: `source_reference`, with the same caveat:
wider is not automatically better, because a wider percentile spread can come
from harmful tail compression. Scored as a bounded "not worse than the source"
rather than as a maximisation.

Any `source_reference` sub-measure is `EVIDENCE_ABSENT` without an authenticated
source.

## 6. Scoring

Each dimension maps a measurement to 0 to 10 through a stated piecewise-linear
function of deviation from target:

- **10** anywhere inside the target interval, if the target is an interval.
- **9** at the stated tolerance edge outside that interval.
- **0** at or beyond a stated gross-error bound.
- Linear between. Tolerances may be asymmetric, and both sides are declared
  separately.

Both the tolerance edge and the gross-error bound must name a basis under section
3.1. A target whose edge cannot name one does not get a score.

The mapping is data, not code. It lives in a versioned YAML file beside the gate
presets so a change is a visible diff.

## 7. Composites

v1 had one composite that refused whenever any dimension was INDETERMINATE. The
review showed that conflates NOT_APPLICABLE with UNKNOWN, and that as written it
would refuse on legitimate b-roll, contradicting the shipped policy that skin is
optional because landscape and product footage have no faces.

Replaced by **named composites with a fixed denominator and a reported coverage
signature**:

| Composite | Denominator | Requires |
|---|---|---|
| `full_interview` | all six dimensions | technical PASS, authenticated source, skin `MEASURED` |
| `no_skin` | the three non-skin dimensions | technical PASS, authenticated source, skin affirmatively `NOT_APPLICABLE` |
| none | | any other state |

Rules:

- Every composite carries its **coverage signature**, the exact set of dimensions
  in its denominator. **Composites with different signatures are never
  compared**, and the report says so rather than leaving the reader to notice.
- **Shots within one clip must share a signature for a clip composite to exist.**
  This case was undefined after the first revision and it is not rare: a
  three-shot interview where one shot is a cutaway with no face gives two shots
  `full_interview` and one `no_skin`. Averaging across that produces a number
  whose denominator changes per shot, which is the silent averaging this section
  forbids, one level up. So the clip composite is computed only over shots
  sharing a signature, it is reported **per signature** with the shot count and
  total duration behind each, and a clip whose shots disagree gets no single
  clip-level number. The per-shot vectors are always reported regardless.
- Skin `EVIDENCE_ABSENT` when skin is expected yields no composite. Only a
  declaration of `NOT_APPLICABLE` opens `no_skin`.
- Technical FAIL or `EVIDENCE_ABSENT` yields no composite.
- No authenticated source yields no composite. A separately named source-free
  diagnostic vector is still reported, and it is a vector, never a score.
- Aggregation is unweighted within a composite, matching the manual scorecard.

Silently averaging whatever dimensions happened to survive remains forbidden.

## 8. The corpus

### 8.1 Tier A: synthetic, with analytically known ground truth

Generated on this machine from published spectral data, no new dependencies.
`colour-science` 0.4.7 is already required and ships `SDS_COLOURCHECKERS`
including ISO 17321-1 with its `dark skin` and `light skin` patches, plus
`SDS_ILLUMINANTS` covering A, D50 through D75, and FL1 through FL12.

The generator renders a defined chart under a defined illuminant into Rec.709,
then encodes through the real ffmpeg delivery path, so the harness measures the
shipping pipeline rather than a numpy approximation.

| Family | Defect | Known correct answer |
|---|---|---|
| D1 | rendered under a non-D65 illuminant | the D65 rendering |
| D2 | spatially split illuminant, warm and cool regions | the per-region D65 rendering |
| D3 | known tone compression and lift | the original tone placement |
| D4 | known chroma scaling | the original chroma |
| D5 | known hue rotation | the original hue |

D2 is the acceptance test for spatial secondaries: no global operation can
correct it, which makes it the cleanest falsification test for the central v2
claim.

**What D1 and D2 do and do not assert.** The D65 answer is the correct answer to
*the injected task*, which is "undo a known illuminant transform". It is not a
claim that neutralising to D65 is professionally correct in general. Under
intentionally mixed lighting it is not. The corpus tests recovery of a known
transform; section 5.5 governs whether recovery is desirable.

**The injection and the recovery may not share an implementation.** The oracle
that injects a defect and the code that corrects it must be independent, or a
shared error cancels and the test passes while measuring nothing. v1's correction
algebra cannot express D2's spatial inverse or D5's hue rotation anyway, so the
oracle is separate code by necessity, and it stays separate by rule.

The repository ships the generator and the expected values, never rendered media.

### 8.2 Tier B: real footage

One clip, by absolute path and SHA-256 in an uncommitted manifest. Repository
ships the manifest schema and the harness, never pixels. No client footage.

Three items: ungraded, v1-graded, hand-corrected, with the recorded manual
scorecard as the only human label available.

**The ungraded item cannot be the source file.** `verify.py` refuses a source
reference whose pixels equal the delivery on every frame, because an ungraded
file measures no grade-introduced clipping. The ungraded item is therefore a
separately rendered pass-through delivery, and the harness must demonstrate that
it authenticates against the source rather than assuming it does.

## 9. Validating the ruler before using it

v1 proposed four properties. The review demonstrated they are jointly passable by
a metric with no semantic content: score 10 when the pixels equal the reference
within epsilon and 9 otherwise, plus a SHA-256 lookup returning the three Tier B
files in the expected order. That satisfies monotonicity, recovery,
discrimination, and ordering while measuring nothing this document describes.

The plan is therefore expanded. Properties 1 to 4 are retained but are no longer
claimed to be sufficient.

1. **Monotonicity.** More defect never scores better, across every family and
   severity step.
2. **Recovery.** The analytically correct inverse returns the score to the
   reference ceiling within a stated tolerance, **over the patches whose
   information survived clipping**, with the excluded count reported.

   That qualifier is not a loophole, it is forced by measurement. Rendering to
   Rec.709 clips, and two facts make clipping unavoidable rather than a bug to
   design away. The **reference scene itself clips**: under D65 with a D65
   balance the ISO 17321-1 cyan patch sits at linear R = -0.0334, outside the
   gamut as a matter of colorimetry with no defect involved. And **exposure
   cannot fix it**, because exposure is a multiplication and cannot change a
   sign, so a negative linear value stays negative at every gain. Under
   illuminant A on a daylight balance, six of 24 patches clip on top of the
   reference's own cyan, leaving 17 on which exact recovery can be demanded.

   `corpus.clipping_report` and `corpus.recoverable_patches` make this a reported
   fact per item rather than an unstated assumption. An item that claimed exact
   recoverability while clipping would be asserting something false.
3. **Discrimination.** The reference separates from the mildest injected defect.
4. **Ordering agreement.** On Tier B, the harness ranks the three items in the
   recorded manual order.
5. **Numeric agreement, not just ordering.** At every severity step, each
   dimension's measured statistic must agree with the analytically expected value
   within a stated tolerance. This is what kills the "10 or 9" null metric: it
   has no statistic to agree with anything.
6. **Effect size.** The score must change monotonically *and by a stated minimum*
   per severity step, until a documented saturation point.
7. **Invariance and null cases.** The score must not move materially under
   changes that are not grading defects: a codec re-encode at the same settings,
   added grain within a stated amplitude, added letterbox bars, and legitimate
   low-key and high-key images.

   **Every masked statistic must be computed through a PINNED mask, or this
   property cannot be stated.** This is not a refinement, it is a precondition,
   and it was found by measurement rather than reasoning.

   `measure._skin_mask` gates on absolute HSV value between 0.25 and 0.95, and
   `measure._neutral_mask` gates on absolute luma between 0.25 and 0.90. So
   exposure changes mask MEMBERSHIP, and a median over a changing population
   obeys no per-pixel invariance law however well behaved the pixels are.
   Measured on the ISO 17321-1 chart under D65:

   | exposure | skin mask px | skin saturation median |
   |---|---|---|
   | 1.000 | 512 | 0.362748 |
   | 0.250 | 512 | 0.362748 |
   | 0.125 | 256 | 0.318672 |

   The dark skin patch crosses `SKIN_VALUE_MIN` and leaves the mask, moving the
   statistic by 0.044. Neutral is worse. Under illuminant A on a daylight
   balance the neutral statistic is **not even monotonic**: 14.03 code values at
   full exposure, 11.19 at half, then **17.67 at a quarter**, rising as the image
   darkens because a different set of patches passes the gates, and at an eighth
   the mask is empty and the dimension is `EVIDENCE_ABSENT`.

   Four of the six scorecard dimensions are masked statistics and all four
   inherit this. The remedy is the frozen mask machinery that already exists:
   derive the ROI once from the authenticated source and stage it onto both
   members of an invariance pair, via `verify._stage_masks`, whose provenance
   check was repaired in section 11 item 1. `corpus.reference_roi` and
   `corpus.masked_statistic` are the corpus-side helpers for the same rule.

   **With the mask pinned, this property gets a much stronger form than "must
   not move".** Each statistic then obeys an exact stated law, and the law is
   not the same for every statistic:

   | Statistic | Law under an exposure gain k | Measured agreement |
   |---|---|---|
   | HSV saturation median | invariant, because it is a ratio | exact |
   | R minus B median | scales by k^(1/2.4), because it is a difference of display codes | relative error 1e-16 |

   So property 7 is stated as **"the statistic follows its declared law"**, not
   as "the score must not move materially". The second version needs a fudge
   factor and hides the fact that some statistics are supposed to move. The
   first is exact, and a design that asserted invariance for both of the above
   would have been wrong about the second.

   Where a mask cannot be pinned, the null case must be restricted to a range in
   which no region crosses a threshold, and that range computed and refused
   against rather than assumed.

   **The declared laws, measured.** Each null case has one per statistic, and
   they are not all "invariant":

   | Null case | Statistic | Law |
   |---|---|---|
   | exposure gain k | skin HSV saturation median | invariant, exact |
   | exposure gain k | neutral median R minus B | scales by k^(1/2.4), to 1e-16 |
   | letterbox matte | any luma percentile | invariant **within the declared aperture**, exact |
   | grain, amplitude a | skin HSV saturation median | within 0.01 at a = 2 |
   | grain, amplitude a | neutral median R minus B | biased **up** by 0.9539a |

   **The grain bias is derived, not fitted, and it matters beyond the corpus.**
   `median(abs(R - B))` is an absolute difference, so zero-mean noise cannot
   cancel and instead pushes it up. The difference of two independent channels
   has standard deviation a times root two, and the median of the absolute value
   of a zero-mean normal is 0.67449 of its standard deviation, giving 0.9539a.
   Measured ratio of observed to predicted: 1.0021 at a = 2 and within half a
   percent of unity through a = 16, which is convergence rather than a fit.

   The consequence for shipped behaviour is worth stating plainly.
   `presets/gates/interview.yaml` sets `whites_rb_balance` at 4.0 code values.
   Grain at 2 code values contributes **1.91 of that on its own**, on a delivery
   with no white balance error whatever. A noisy but correctly balanced delivery
   therefore spends nearly half the gate budget before any real defect is
   measured, and the gate cannot distinguish the two. That is a property of
   measuring an absolute difference and not a bug, but a validated threshold has
   to account for it or it is validating against noise.

   **Letterbox needs a declared aperture, not a detector.** Bars are exactly
   zero, so they own the low percentiles: measured on the reference chart with a
   twelve percent matte, p1 luma reads 0.000 with bars included and 61.976
   within the aperture, which is the unmatted reference's own p1 to the digit.
   There is no reliable way to separate a matte from a photographed black
   border, and guessing throws away a legitimately dark frame's blacks, so the
   operator declares it and the report records the declaration.

   **Translation invariance is deliberately excluded, and saying why matters
   more than the exclusion.** An earlier draft required it. It cannot honestly
   be required while frozen masks are fixed 2D coordinates applied to every
   frame with no tracking, and while registration between source and delivery is
   an open question in section 12. A translated frame moves the subject out from
   under the mask, so the harness would be measuring a different region and
   would be right to report a different number. Listing an invariance the design
   cannot deliver would mean either a permanently failing property or a quiet
   waiver, and both are worse than the honest exclusion. Translation invariance
   returns to this list when registration and tracking are specified, not
   before.
8. **Cross-dimension specificity.** An injected D4 chroma defect must move the
   chroma dimension and not masquerade as a hue or luma defect. Each family has a
   declared expected signature, and off-signature movement is a failure.
9. **ROI precision and recall.** Against known ground-truth masks, including
   defects strong enough to push skin outside the current qualifier thresholds,
   which is the failure mode behind section 5.3's circularity.
10. **Held-out content, not just held-out parameters.** Randomised and combined
    defect parameters are necessary and insufficient. A metric that has learned
    the generator interpolates unseen severities perfectly. The held-out set must
    therefore vary what a generator-fitting metric cannot interpolate: **chart
    layout and geometry**, **the implementation of each defect** (a second,
    independently written injector), **content that is not a chart at all**, and
    **at least one real clip never used while defining the metric**.
11. **No label leakage.** The metric may not read the validation labels, the
    hand-corrected target, or any Tier B file digest at evaluation time. Stated
    as a rule and enforced by the harness's own interface.
12. **Reference-free statistic correctness.** For every Tier A item, each
    dimension's statistic must be computed **with no access to the reference at
    all**, and must agree with the analytically known value within a stated
    tolerance.
13. **Equal-distance discrimination.** Pairs of items constructed to be equally
    far from the reference by a whole-image transform distance, but carrying
    different per-dimension defects, must receive different per-dimension scores
    in the direction of their actual defects.

**Why 12 and 13 exist, and what they are aimed at.** The first revision defeated
the "score 10 or 9 plus a hash lookup" metric. Review then constructed a second
null metric that passed all eleven properties, described here in full because the
next reader deserves the attack rather than a summary of it: register and low-pass
the delivery and source, crop known borders, fit the residual to the five known
synthetic transform families, estimate continuous severity parameters, map those
parameters to the expected dimension statistics through calibrated formulas, use
fixed chart rectangles as the ROI "detector", and for Tier B embed a linear
function of generic full-frame moments fitted once to order the three known
files. It understands the generator and its layout. It has no concept of skin,
neutrals, motivated lighting, or deliverable quality.

Property 12 attacks its dependence on the reference: with the reference withheld
there is no residual to fit, so a transform estimator cannot produce a skin Oklab
hue angle at all. Property 13 attacks the variant that recognises geometry but
not meaning. Property 10 as rewritten attacks the fixed chart rectangles, since a
changed layout and an independently written injector are exactly what a
generator-fitted metric cannot interpolate.

**Enforcement, because two of these rules were previously unenforceable
sentences.** Property 11 forbade reading labels "at evaluation time", which the
null metric satisfies trivially by baking the labels into fitted coefficients
beforehand. And "failures are reported, not tuned away" was procedural advice
with nothing behind it. Both become checkable through **pre-registration**: the
metric implementation and its complete scoring file are hashed and the hash
recorded **before** the held-out set is run, and the report carries that hash. A
metric whose coefficients were fitted to the labels is not thereby detected, but
a metric adjusted *after* seeing held-out results no longer matches its recorded
hash, and a report without a matching pre-registration hash is not a validation
result.

**This list is a growing set of specific defences, not a proof of sufficiency.**
Two rounds of review each produced a null metric that passed the plan as it then
stood. The reasonable expectation is that a third exists. Section 9 will keep
growing, and the document should be read as describing what the plan currently
defends against rather than as certifying semantic validity. Property 4 in
particular can only falsify, as it already says.

**Property 4 is not executable as written and is not pretended to be.** One clip
rated by one person establishes nothing about generalisation. What it can do is
falsify: if the harness contradicts the only human ordering available, the
harness is wrong. It is used as a falsifier, not as evidence of correctness, and
the report says which.

**Failures are reported, not tuned away.** A metric adjusted until it passes its
own validation has validated nothing. Where a property fails, the failure is
recorded here and in the report.

## 9a. What the first validation run actually found

Run and recorded at `docs/research/measurements/2026-07-23-first-validation-run.md`,
reproducible with `.venv/bin/python tools/run_validation.py`.

**Properties 1 and 5 hold, and property 5 holds exactly.** Chroma at severity 1.0
measures 0.02998 against a reference 0.05997, precisely the 0.5 scale the
injector declares. Hue rotates exactly 12.000 degrees, precisely the declared
rotation. That is numeric agreement of the statistic, not merely ordering.

**Property 8 as first written was wrong, and the run said so.** It read "a family
must move its own dimension more than any other". Tone compression moved skin
chroma by 45.98 percent while moving black placement by 2.87 percent, so it
failed. Both movements are real:

- Compressing the tonal range to 65 percent of its span pulls every colour toward
  mid grey, reducing colourfulness monotonically at 13.04, 24.98, 35.94 and
  45.98 percent across the sweep.
- The tone injector is a PER-CHANNEL curve, and per-channel curves do not
  preserve hue. Skin hue moves 0.477, 0.961, 1.452 and 1.948 degrees across the
  same sweep. A luminance-preserving curve would not do this, and the
  per-channel curves real grading software offers do, so a tonal defect on real
  footage arrives with a hue shift attached.

So each family now declares an expected SIGNATURE, a set of dimensions it should
move, and the property asserts that everything in the set moves and nothing
outside it does. The naive form was also comparing percentages across
incommensurable quantities, an angle against a ratio against an IRE value, which
is the same category error this document already made once over skin hue and
chroma.

**A limitation of the corpus surfaced too.** The chart's darkest patch sits at
24.3 IRE, so there is no true black for a lift to act on and black placement is a
weak detector on this content, moving only 2.87 percent where p99 falls from
95.14 to 59.27 IRE. The strong statistic for a tonal defect is the one that
currently reports `EVIDENCE_ABSENT` for want of an authenticated source.

## 10. What the harness produces

A JSON report and a human-readable summary containing, per item:

- per dimension: statistic, measured value, target, **target basis**,
  **conditioning facts used**, tolerance, score or state with a reason
- per composite: value, **coverage signature**, or the refusal with the states
  that caused it
- the duration-weighted mean and the worst shot, for every dimension
- provenance of every target: citation id, source measurement, or the operator's
  recorded declaration
- software, ffmpeg, and scoring-file versions

Every empirical number must be reproducible on this machine by a stated command.

## 11. Prerequisite fixes in existing code

These are not harness features. They are defects the harness would otherwise
inherit, found during review.

1. **`verify._stage_masks` does not authenticate the mask it stages.** It checks
   that `identity_json` is present, then reads only the array and re-saves under
   a freshly derived identity. A same-sized mask from unrelated media is
   accepted. Section 5.3 depends on staged masks being trustworthy.
2. **Log sources clip before measurement.** `measure._to_measurement_rgb` routes
   through `bt1886_encode`, which clips to 0 to 1. Section 5.6b needs an
   unclipped working-linear path for source-relative statistics.
3. **No signed per-region statistics and no CIEDE2000.** Section 5.5 needs both.
4. **No masked luma median, perceptual hue, or perceptual chroma in `MaskStat`.**
   Sections 5.2 to 5.4 need them. These are new primitives, not reuse.
5. **The frozen mask is one 2D mask taken from the first sampled frame with
   candidates and applied at fixed coordinates to every sampled frame.** A moving
   face means later samples measure background. There is no tracking. Until there
   is, the harness must either bound acceptable subject motion or report reduced
   confidence, and it must not silently average a face with a wall.

## 12. Open questions, recorded rather than assumed

- ~~Whether the corpus's gamma 2.4 pixels tagged `bt709` are standards-correct.~~
  **Settled.** The pixels are display referred and encode the inverse of the
  BT.1886 EOTF, so scene linear 0.18 encodes to 0.48944 and a BT.1886 display
  returns exactly 0.18000. The BT.709 OETF is a scene-referred camera transfer
  and is not the inverse of BT.1886: it puts 0.18 at 0.40901, which a BT.1886
  display renders as 0.11699, and that gap is the deliberate end-to-end system
  gamma for camera light in a dim surround. The encode is therefore right for a
  deliverable. The TAG is a vocabulary limit: ffmpeg's `color_trc` has no BT.1886
  value, so `bt709` is used as the conventional Rec.709 SDR signal, matching the
  shipped delivery profiles. Reproduced by `tools/measure_transfer_convention.py`.
- Whether Zeng and Luo 2011 contains preferred-skin tolerances usable as a band.
  Identifier verified, content not checked. This is now the single largest
  remaining gap: hue has a measured target, chroma has only an accurate baseline
  and still needs the preferred offset.
- ~~Whether the roughly 123 degree vectorscope skin line has a physical
  derivation.~~ **Settled.** It is not the NTSC I axis, which is 15 degrees away,
  but it does match measured skin to 0.676 degrees in the BT.709 Cb/Cr plane. See
  `references/color-theory/skin-targets-measured.md`.
- The tolerance edge for skin hue. The measured illuminant-driven spread of
  -5.89 to +3.40 degrees is a spread of correct values, not a tolerance for
  incorrect ones, and using it as a tolerance would be a category error.
- Registration requirements when source and delivery differ by crop,
  stabilisation, retiming, or overlays. The harness currently assumes they do
  not.
- Measurement uncertainty across codecs, ffmpeg builds, and sampling choices. No
  reproducibility bound is stated yet, and section 9 property 7 will produce the
  data for one.
- Multiple faces or multiple skin tones in one shot. Not handled.
- Whether six dimensions is the right shape when one of them scores a constant
  10 on every item that can be scored at all. See section 14.
- Letterbox exclusion has no algorithm. Section 5.6a mandates it without saying
  how bars are distinguished from photographed black borders, and an
  operator-declared active aperture is the likely answer but is not specified.
- How technical conform's three sub-checks and tonal shaping's three sub-measures
  combine into one dimension value is stated for tonal shaping (a mean) and for
  technical conform (a table), but the duration weighting when a dimension is
  `MEASURED` on some shots and `NOT_APPLICABLE` on others is not defined beyond
  the per-signature rule in section 7.
- Whether three sampled frames per shot suffice for scoring. Downstream of the
  mask-tracking limitation in section 11 item 5.

## 13. What changed in v3, after the second review

The revised document was reviewed again. The verdict was still "revise before
implementation", and the following came from it.

- `TARGET_UNAVAILABLE` added to section 3.3. The four-state model conflated "not
  measured" with "measured, nothing to compare against".
- Technical conform given an actual numeric rule in 5.1. v2 said it was scored
  and never said how.
- The comparability claim corrected in 5.0. Scoring technical conform 10 rather
  than the manual 9 means the composite cannot reproduce 5.5, so the document now
  claims same-scale readability and ordering, not equality.
- Highlight distinguishability given a computable definition in 5.6b. The phrase
  was not a statistic.
- Mixed-signature shots within one clip defined in section 7. Previously
  undefined, and it would have reintroduced silent averaging one level up.
- Validation properties 12 and 13 added, against a second null metric that passed
  all eleven.
- The skin hue and chroma conditioning claims in 5.3 and 5.4 weakened to what one
  exemplar per category supports, and the underlying reference note corrected: it
  had compared an angle spread against a ratio, which are not comparable units.

## 14. What changed in v2, and what was rejected

Accepted from the review and acted on: the basis and conditioning split (3), the
four-state evidence model (3.3), aggregation defined before use (4), technical
conform scored and gating with a third state (5.0, 5.1), skin luma demoted from
an absolute target (5.2), the skin ROI circularity and its dependency on fixing
`_stage_masks` (5.3, 11.1), skin chroma named as a preference model (5.4, 2),
neutral consistency changed to declared (5.5), highlight reach replaced by
retained distinguishability (5.6b), the log clipping path (5.6b, 11.2), letterbox
exclusion (5.6a), named composites with coverage signatures (7), the
injection-recovery independence rule (8.1), the ungraded Tier B item (8.2), seven
added validation properties (9), and the corrected reuse claims (11.3, 11.4).

Rejected, with reasons:

- **Dropping the manual six-dimension scale.** The review offered replacing it
  with a five-dimension composite. Comparability with the one human-labelled
  datapoint that exists is worth more than tidiness.

  **Recorded as UNRESOLVED after the second review, not rejected.** The reason
  given here, that scoring technical conform while also gating on it "costs
  nothing", is false: the dimension takes one sixth of the weight while
  simultaneously excluding every non-passing item, so it contributes a constant
  to every item that can be scored at all and discriminates between none of
  them. The second review also pointed out that one labelled item establishes a
  reference point, not scale comparability. What the first review actually asked
  for was a consistently defined scale, which 5.0 and 5.1 now supply. Whether
  six dimensions with a constant sixth is the right shape is still open, and it
  is listed in section 12.
- **Treating the neutral disagreement on the motivating clip as possibly correct
  motivated lighting.** The general principle is accepted and 5.5 now reflects
  it. On that specific clip the operator has judged the split a defect, and the
  declaration mechanism records exactly that rather than overriding it.
