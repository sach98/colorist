# Transfer functions and the log family

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

A transfer function maps linear light to code values. Three families matter here.

## Display transfer functions

- **BT.709 OETF**: camera-side encoding for broadcast: V = 4.5 L for L < 0.018, else 1.099 L^0.45 - 0.099 [S: Recommendation ITU-R BT.709-6, identifier-cited]. Display-side SDR reference behavior comes from BT.1886; this tool uses a stated 1/2.4 power implementation with clipping [S: ITU-R BT.1886, identifier-cited] [E: src/colorist/corrections.py].
- **sRGB EOTF**: piecewise linear/power for computer displays: C_lin = C/12.92 below 0.04045, else ((C+0.055)/1.055)^2.4 [S: IEC 61966-2-1]. Rec.709 and sRGB share primaries but differ in transfer; never conflate them [E: repository ingest matrix keeps them distinct].

## Camera log curves

Log curves compress scene-linear values into code values. The five supported curves are anchored to manufacturer documents in the repository's vector fixtures [M: Sony, ARRI, Panasonic, and Canon documentation anchors, tests/vectors/*.json]:

| Curve | 18% grey | 0% black | Convention note |
|---|---|---|---|
| S-Log3 | CV 420 (10-bit), 41 IRE | CV 95 | reflection = IRE x 0.9 |
| LogC3 EI800 | 0.391 = 400/1023 | encode(0) = 0.092809 | EI800 parameters recommended for exchange |
| LogC4 | 0.2784 | 0.0929 | signal 0 decodes below scene zero (-0.0181) |
| V-Log | CV 433 | CV 128 | linear toe below cut 0.01 |
| C-Log3 | CV 351 (34.3% full) | CV 128 (12.5%) | table in scene-linear percent; reflection = SL x 0.9 |

Two convention traps cost real projects: vendor tables mix REFLECTION and SCENE-LINEAR domains (both Sony and Canon carry a 0.9 factor between them), and table code values are rounded (decoding a rounded CV reproduces the anchor only within rounding, roughly 5e-3 at 90% white) [E: cross-check session 2026-07-19, every anchor verified against colour-science 0.4.7 with per-vector tolerances].

## Practical rules

1. Log footage viewed without its decode looks flat and desaturated; that is correct capture, not a defect.
2. This repository's architecture decodes to working scene-linear RGB before white balance and exposure, then uses its defined grading space for contrast and saturation before output encoding [E: src/colorist/corrections.py]. Other grading systems may choose different documented working spaces.
3. Never trust container metadata to identify a log curve; standard tags cannot express vendor (curve, gamut) pairs. Identification is explicit user confirmation with metadata as evidence [E: repository spec 6].
