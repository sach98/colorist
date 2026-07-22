# Color appearance basics

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Measurement describes a signal; appearance describes a viewer's response. A controlled grading environment reduces avoidable variation between them [S: CIE 15:2018, Colorimetry].

## Adaptation

Chromatic adaptation is modeled by colorimetry and color-appearance methods [S: CIE 15:2018, Colorimetry].

Project guidance: in common grading experience, an observer can become accustomed to a cast within minutes, but the timing varies by person and condition. Use scopes and frozen regions to check neutrality rather than relying only on an adapted visual impression.

This tool uses frozen regions for its neutrality measurements [E: src/colorist/measure.py, _measure_mask].

## Simultaneous contrast and surround

A patch's appearance changes with its surround, so review-room surround and ambient light matter. ITU-R BT.2035 specifies a reference viewing environment for HDTV programme evaluation [S: ITU-R BT.2035, identifier-cited]. BT.1886 defines the reference EOTF used for SDR display practice; it is a separate source from BT.709 [S: ITU-R BT.1886, identifier-cited].

## The grading environment

The reference environment calls for controlled viewing conditions around a calibrated reference display [S: ITU-R BT.2035, identifier-cited]. Project guidance: keep review lighting stable, use a calibrated display where possible, and treat a bright, variable laptop environment as unsuitable for final color decisions.

## Why appearance still matters to a measurement tool

Gates measure a signal, while targets such as grey placement, headroom, and skin saturation encode appearance choices. Project guidance: treat this repository's soft-gate defaults as provisional working values, not laws [E: presets/gates/interview.yaml].

## Practical rules

1. Project guidance: look at a neutral reference or away from the screen before judging a suspected cast.
2. Project guidance: compare review conditions with the intended delivery conditions when appearance is disputed.
3. Project guidance: when a human and the numbers disagree about neutrality, inspect the mask, then the viewing environment, then the gate value.
