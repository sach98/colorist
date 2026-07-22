# Color difference

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

"How different are these two colors?" needs a number, and the number needs a definition.

## The delta E family

Delta E is a color-difference value whose meaning depends on the selected formula, input colorimetry, observer, material, illumination, geometry, and viewing conditions [S: CIE 15:2018, Colorimetry]. A value near one is not a universal just-noticeable threshold.

- **CIE76**: plain Euclidean distance in Lab. Simple, overstates differences in saturated regions.
- **CIE94**: adds weighting for chroma and lightness dependency.
- **CIEDE2000 (delta E 2000)**: the CIEDE2000 method is specified by ISO/CIE 11664-6; this repository uses it for reported perceptual difference [S: ISO/CIE 11664-6, Colorimetry -- Part 6: CIEDE2000 Colour-difference formula]. The IDT tests use a repository tolerance of dE2000 <= 0.5 for grey anchors and measured 0.047 to 0.052 in the recorded spike [E: docs/spike-verdict.md].

## Prerequisites are part of the number

A delta E is meaningful only when both colors are converted to Lab correctly: defined RGB space, defined white point, correct transfer decode. Computing dE on raw display RGB without knowing its encoding produces a number with no meaning. This tool therefore emits dE (and CCT/Duv) in reports only when prerequisites hold: the encoding is identified and neutral evidence is present and unimodal; otherwise the report shows RGB-domain deltas and says why [E: repository spec 5.4].

## Interpretation scales

Working bands such as below 1, 1 to 2, 2 to 5, and above 5 are conventional communication aids under stated reference conditions, not universal perception bands. Their interpretation is formula and viewing dependent. Project guidance: state the formula, color space, viewing assumptions, and task before using a delta E threshold.

## Engineer units beside perceptual units

This tool gates in RGB-domain units (medians of code-value differences on frozen regions) because they are cheap, stable, and directly actionable by the solvers, and it reports perceptual units beside them for colorist communication. The two rank defects similarly on neutrals; they diverge on saturated colors, where perceptual weighting matters [E: repository reporting design]. When speaking to a colorist, lead with delta E; when driving a solver, use the domain the solver operates in.
