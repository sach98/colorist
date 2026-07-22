# Color spaces and gamuts

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

A complete image encoding pairs two independent things: a gamut, defined by primaries and a white point, and a transfer function, the nonlinear mapping between linear light and code values. ITU-R BT.2390 treats gamut and transfer as separate system components [S: Report ITU-R BT.2390, identifier-cited]. Confusing them can silently corrupt a transform; if retained source data and the mistaken transform are known, the material can be reprocessed.

## The delivery spaces

- **Rec.709 / BT.709**: HD broadcast and SDR web colorimetry. Primaries are R(0.640, 0.330), G(0.300, 0.600), B(0.150, 0.060), with D65 white (0.3127, 0.3290) [S: Recommendation ITU-R BT.709-6, identifier-cited]. This tool's working primaries and default delivery target.
- **DCI-P3**: a digital-cinema projection space specified for its reference projector context [S: SMPTE RP 431-2, identifier-cited]. Display P3 is a separate display convention and must be identified by its actual profile and transfer behavior.
- **Rec.2020 / BT.2020**: UHD system colorimetry with primaries wider than Rec.709 [S: Recommendation ITU-R BT.2020, identifier-cited]. Coverage and mapping must be assessed for the actual display and delivery chain.

## Camera gamuts

Cameras can encode into vendor gamuts such as S-Gamut3.Cine, ARRI Wide Gamut 3 and 4, V-Gamut, and Cinema Gamut. In this repository, the curve and gamut pair identifies the supported encoding [M: vendor documentation anchors, tests/vectors/*.json]. Conversion between RGB spaces is performed on decoded linear values with the chosen RGB-space and adaptation definitions [E: src/colorist/idt.py, vendor-anchor tests].

## Working space

This tool decodes camera code values to scene-linear Rec.709/D65 working RGB, performs white balance and exposure there, moves into a log2 grading space for contrast and saturation, then applies the optional look and output encode [E: src/colorist/corrections.py, compile_shot_lut]. The v1 choice favors a minimal, testable transform path.

## Practical rules

1. Project guidance: identify the curve and gamut pair before applying a transform.
2. Project guidance: measure delivery clipping and mapping outcomes on the rendered file instead of assuming them.
3. A neutral defined relative to the source white should remain neutral relative to the target white when the specified conversion and adaptation are applied [E: src/colorist/idt.py, vendor-anchor tests].
