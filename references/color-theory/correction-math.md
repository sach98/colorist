# Correction math

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

The ASC CDL names primary controls as Slope, Offset, Power, and Saturation. This tool does not export CDL, and its correction algebra is deliberately its own fixed implementation [C: American Society of Cinematographers, "ASC CDL" documentation] [E: src/colorist/corrections.py].

## The lift/gamma/gain trinity

User-interface controls called lift, gamma, and gain vary between applications. Project guidance: compare their declared formulas or measure a ramp rather than treating their labels as interchangeable with this tool's controls.

## This tool's algebra

Defined in `compile_shot_lut` with a fixed, non-commutative order [E: src/colorist/corrections.py, compile_shot_lut]:

1. **Decode**: camera code values decode to working scene-linear RGB through `camera_to_working`; Rec.709 input uses the project's BT.1886 decode.
2. **White balance and exposure**: per-channel white-balance gains and `2**exposure_ev` multiply scene-linear working RGB.
3. **Shaper**: scene-linear RGB maps into the grading space through an invertible shaper, a C1-continuous affine toe below scene-linear 2^-7 joined to a log2 segment above it, spanning 0.001 to 1024.0 [E: src/colorist/corrections.py, shaper and inverse_shaper]. The toe exists so the shaper is invertible at and near zero: a pure log2 shaper with a floor sends black to the floor value instead of back to black.
4. **Contrast**: `pivot * (clip(grading, 0, None) / pivot) ** contrast` runs in that grading space.
5. **Saturation**: after contrast, saturation is `luma + saturation * (grading - luma)`, with Rec.709 luma weights 0.2126, 0.7152, and 0.0722. It is not scene-linear saturation.
6. **Look and output**: the optional 3D look LUT runs in grading space; the inverse shaper clips to its domain, then the project BT.1886 encoder produces display values.

The per-shot stack compiles into one 65-point 3D LUT whose input is camera code values and whose output is display values. Parameters in the manifest are the source of truth, and the LUT is their deterministic compilation [E: src/colorist/corrections.py] [E: tests/test_corrections.py].

## Domains matter more than formulas

The same named operation in different domains is a different operation. This implementation's saturation occurs in the stated grading space; an HSV S-channel gain would be a different operator. Exposure as a linear multiplier is not an offset on log code values. Project guidance: state the domain and operation before comparing controls across systems.
