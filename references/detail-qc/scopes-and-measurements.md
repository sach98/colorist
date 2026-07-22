# Scopes and their numeric equivalents

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

A colorist's scopes are visual summaries of frame signals. This tool computes stated numeric measurements directly from decoded pixels; a scope view remains useful for human inspection [E: src/colorist/measure.py] [E: src/colorist/verify.py].

## Waveform

The waveform summarizes signal level against horizontal picture position. This tool's numeric measurements include per-shot luma p1, p50, and p99 using Rec.709 weights in the stated domain, plus decoded-delivery extrema checks [E: src/colorist/measure.py] [E: src/colorist/verify.py]. Project guidance: use p1 and p99 as diagnostic values, then inspect the frame and delivery intent before calling a creative choice a defect.

## Vectorscope

The vectorscope represents chroma in a signal-specific polar display. Its skin-tone line is an angular convention in that representation; it is not equivalent to a narrow HSV hue band. This tool's HSV skin mask is a chosen heuristic, while its neutral checks are R minus B and G minus the R/B midpoint on frozen regions [E: src/colorist/measure.py, _skin_mask and _measure_mask].

## Histogram

The histogram is the value distribution without positional information. Numeric equivalents: the same percentile set, plus clipped-pixel fractions at the range endpoints (the "walls" a colorist looks for). Grade-INTRODUCED clipping is distinguished from baked-in camera clipping by comparing source and output clipped fractions on the same frames [E: repository gate design].

## The discipline

Project guidance: base automated gates on stated measurements from decoded pixels, and retain rendered scope images for human review. Do not treat an unverified visual impression as a measurement.
