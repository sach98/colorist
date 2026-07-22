# White balance and illuminants

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

White balance is the act of making the scene's intended neutral actually neutral in the encoded image: R = G = B on a grey object.

## CCT and Duv

Correlated color temperature describes an illuminant by the temperature of the Planckian radiator whose chromaticity it most resembles. Duv is a signed distance from the Planckian locus in the CIE 1960 u,v diagram and represents a direction CCT alone does not describe [S: CIE 15:2018, Colorimetry]. This tool uses two working-RGB neutrality axes, R minus B and G minus the R/B midpoint, as project measurements rather than as direct CCT or Duv values [E: src/colorist/measure.py].

## D65

Standard illuminant D65 is approximately 6504 K and is the white point of Rec.709 and sRGB [S: CIE 15:2018, Colorimetry] [S: ITU-R BT.709-6, identifier-cited]. In a D65-white RGB space, a corrected neutral encodes with equal RGB values.

## Chromatic adaptation

Conversion between spaces with different white points can use a chromatic adaptation transform. Bradford and CAT02 are discussed in CIE 160; this is an identifier citation because the repository's research record does not contain a directly verified text [S: CIE 160:2004, A Review of Chromatic Adaptation Transforms, identifier-cited]. This tool uses CAT02 through its color-science conversion path [E: src/colorist/idt.py, vendor-anchor tests].

## Solving white balance

Given a measured neutral median (Rn, Gn, Bn), the correcting gains are grey/channel, where grey is the sample's own Rec.709 luma, so the corrected neutral is equal-RGB at exactly the luma it started with: this is closed-form, per shot, and never hand-tuned [E: corrections.solve_wb, unit-tested for zero luma error and to invert injected casts]. Note the failure mode this replaced: renormalizing those gains by their weighted mean looks luma-preserving and is not, measured at -6.68 percent on one neutral. The hard part is never the math; it is the EVIDENCE: which pixels are really neutral. Mixed illumination produces multiple genuine neutrals that disagree (window daylight plus tungsten practicals), in which case a single global correction damages at least one region and the tool refuses and reports clusters instead [E: repository measurement methodology; multimodal refusal].

## Practical rules

1. Project guidance: do not infer the cause of a color difference from one garment or one measurement. Prefer several neutral candidates and per-region evidence.
2. On-set white cards beat inferred neutrals; when absent, verified low-chroma regions with visual mask confirmation are the fallback.
3. State the domain: gains solved in scene-linear light are not the same numbers as gains on log code values [E: correction algebra, repository spec 4.2].
