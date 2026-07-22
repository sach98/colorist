# LUTs explained

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

A lookup table maps input color to output color by sampling a function on a lattice and interpolating between samples.

## 1D vs 3D

A 1D LUT maps each channel independently (curves: contrast, transfer functions); it cannot express cross-channel operations like saturation or hue shifts. A 3D LUT samples the full RGB cube (size N means N^3 entries) and can express any per-pixel color-to-color mapping, including gamut conversions, looks, and this tool's entire compiled correction stack [E: repository lut.py and corrections.py]. What no LUT can express: anything spatial (windows, blurs, tracking, matte cleanup) [E: repository LIMITS].

## The .cube dialect, pinned

The .cube format is a de facto standard with dialect variation, so this repository pins one and tests it: LUT_3D_SIZE (65 shipped, 17/33 in tests), DOMAIN_MIN 0 0 0, DOMAIN_MAX 1 1 1, R varies fastest in data order, six decimal places, out-of-domain input clamps [E: lut.py, dialect asserted by tests]. When a vendor tool reads a .cube differently (domain lines ignored, ordering assumed), neutral ramps expose it instantly: pass a grey ramp and check monotonic equal channels.

## Interpolation: trilinear vs tetrahedral

Between lattice points, trilinear interpolation blends eight corners; tetrahedral interpolation divides a cell into six tetrahedra and blends four vertices. Tetrahedral interpolation is widely preferred for color pipelines, but this repository does not claim it is universally better on every signal. What the repository proves is implementation agreement: its Python tetrahedral implementation matches FFmpeg `lut3d=interp=tetrahedral` with maximum channel error 0.00064 on the selected smooth-LUT test, within a tolerance of 2/1023 [E: docs/spike-verdict.md].

## Precision and shapers

Lattice density limits fidelity where a mapped function changes fastest. This tool's shaper maps scene-linear 0.001 to 1024.0 into 0 to 1 before its 3D table, using an affine toe below 2^-7 and log2 above it so the map stays invertible down to zero [E: src/colorist/corrections.py, shaper]. Project guidance: place any LUT only after confirming its expected input encoding and domain.

## Failure modes

Rounded table values and low lattice density can reduce fidelity, particularly for steep mappings. This project's shaper clamps out-of-domain inputs, so values above its stated ceiling require an explicit policy [E: src/colorist/corrections.py, shaper and inverse_shaper]. A LUT associated with the wrong curve or gamut pair is a transform mismatch that must be diagnosed from its declared input and measured output [E: tests/vectors/*.json].
