# Aces And Color Management Literacy

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Color-management literacy starts with identifying the input encoding, the working transform, the output transform, and the viewing condition. This repository is not ACES-native in v1 [E: docs/design.md, section 4.1].

A 1D LUT maps channels independently; a 3D LUT maps RGB coordinates on a lattice. This repository uses 3D LUTs for its compiled per-pixel correction stack and does not use LUTs for spatial operations [E: src/colorist/lut.py] [E: repository LIMITS.md].

Adobe's Cube LUT Specification 1.0 documents the basic `.cube` header and data format [C: Adobe, "Cube LUT Specification 1.0"]. This repository pins its own dialect and tests its ordering, domain lines, and precision [E: src/colorist/lut.py] [E: tests/test_lut.py].

Interpolation is required between 3D-LUT lattice nodes. Trilinear interpolation uses eight cell corners; tetrahedral interpolation uses four vertices from one of six tetrahedra. Tetrahedral interpolation is widely preferred for color pipelines, while this repository's specific evidence is limited to agreement between its implementation and FFmpeg at maximum error 0.00064 [E: docs/spike-verdict.md].

Increasing lattice size increases the number of entries. The project applies an invertible affine-toe-plus-log2 shaper before its 65-point correction LUT so its stated grading range uses the lattice deliberately [E: src/colorist/corrections.py, shaper]. Project guidance: do not assume that user-interface controls called lift or gamma have the same implementation across applications.

Viewing environment affects appearance. Project guidance: evaluate a final grade in controlled, stable conditions rather than treating a variable office or laptop environment as a reference environment.

ITU-R BT.2035 and SMPTE ST 2080-3:2017 specify reference viewing-environment requirements including controlled lighting and neutral surround conditions [S: ITU-R BT.2035, identifier-cited] [S: SMPTE ST 2080-3:2017, identifier-cited]. Bias-light chromaticity must match the display's reference white; D65 follows when that reference white is D65.
