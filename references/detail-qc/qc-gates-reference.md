# QC gates reference

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Gates are the tool's spine: numeric pass/fail with exact values, never impressions. They come in two classes with different authority.

## Hard gates (never overridable)

- Delivery sample-range legality: Y/Cb/Cr extrema on the decoded delivered file against the declared range, scaled by bit depth. For limited 8-bit signals, the project checks Y 16 to 235 and C 16 to 240 [S: ITU-R BT.709-6, identifier-cited] [E: presets/gates/interview.yaml] [E: src/colorist/verify.py].
- Delivery tag correctness: color_range, color_space, color_transfer, color_primaries must match the delivery profile. Tags are declarations, not proof, which is why sample extrema are checked separately; and encoders genuinely drop tags [E: prores_ks on ffmpeg 8.1 dropped BT.709 primaries/transfer tags, caught and remuxed, observed in this repository's delivery-encode work].
- Grade-introduced clipping beyond the shipped threshold, measured source-relative so camera-baked clipping is reported but not attributed to the grade [E: presets/gates/interview.yaml].
- Processing invariants (NaN/inf in the float pipeline) are not gates at all: they abort the run as ERROR.

## Soft gates (waiver-able, recorded)

The shipped interview preset values, with their domains stated in the YAML schema:

- Whites R-B: median |R minus B| <= 4 on frozen neutral regions, 8-bit full-range RGB scale [E: presets/gates/interview.yaml].
- Whites green axis: median |G minus (R+B)/2| <= 3 in the same domain [E: presets/gates/interview.yaml].
- Shadow floor: luma p1 >= 0.5 on the stated 8-bit scale [E: presets/gates/interview.yaml].
- Highlight ceiling: luma p99 <= 205 [E: presets/gates/interview.yaml].
- Skin saturation: HSV S median within 25 to 38 percent on frozen skin regions [E: presets/gates/interview.yaml].

## Validation status: unvalidated. Read this before trusting defaults.

The values are provisional interview-preset defaults, not validated universal targets [E: presets/gates/interview.yaml]. A grade that intentionally fails a soft gate can record a waiver with gate id, reason, and scope in the manifest and report [E: src/colorist/gates.py]. This repository currently ships only `interview.yaml`; it does not claim documentary, night, commercial, or music-video presets.

## Run states

Every run terminates PASS, FAIL, INDETERMINATE (required evidence absent: honest, common on real footage), or ERROR. Exit codes 0/2/3/4 respectively in the CLI. INDETERMINATE is a feature: it is what refusing to fabricate looks like at the run level.
