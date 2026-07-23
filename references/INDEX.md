# References index

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

One line per file. Load only what the task needs. Evidence tags used throughout: [S: standard], [M: manufacturer document, with anchors in tests/vectors/], [E: this repository's recorded measurement or code artifact], and [C: named craft source]. Policy: factual claims must not outrun their tags, and the fact-review process enforces that requirement.

## color-theory (the physics and math of the pipeline)

- color-spaces-and-gamuts.md: gamut vs transfer, 709/P3/2020, camera gamuts, working-space choice, matrix conversion invariants.
- transfer-functions-and-log.md: BT.709/sRGB transfers, the five verified log curves with anchor table, vendor convention traps.
- white-balance-and-illuminants.md: CCT/Duv and the two-axis white model, D65, CAT02, closed-form WB solving, mixed-light refusal.
- correction-math.md: ASC CDL vocabulary, lift/gamma/gain mapping, this tool's five-step algebra and LUT compilation, domain discipline.
- luts-explained.md: 1D vs 3D, pinned .cube dialect, tetrahedral vs trilinear with measured agreement, shapers, failure modes.
- color-appearance-basics.md: adaptation, surround, BT.2035 grading environment, why gate targets are appearance conventions.
- color-difference.md: delta E variants, prerequisites, interpretation bands, engineer vs perceptual units.
- uniform-spaces-for-grading.md: measured hue linearity of Oklab/CAM16-UCS/Jzazbz/ICtCp/IPT/CIELAB against the Munsell renotation, overall and in the skin hue families.
- white-balance-accuracy-measured.md: measured dE2000 cost of v1's channel-gain white balance against von Kries/Bradford/CAT02/CAT16, on an analytically known chart.
- skin-targets-measured.md: the vectorscope skin line is NOT the NTSC I axis but does match measured skin; Oklab skin hue and chroma targets across four skin categories and six illuminants.

## industry-standards (the live-research pillar; numbers here are dated and perishable)

- research-method.md: the live-research discipline (primary sources, cross-verification, dated citations, honest UNVERIFIED).
- delivery-specs-landscape.md: platform/broadcast delivery levels landscape, every number dated, agent-refresh pointer.
- aces-and-color-management-literacy.md: ACES concepts for literacy (this tool is not ACES-native in v1).
- ffmpeg-color-capabilities.md: the grading-relevant filter set, the auto-negotiation trap, range/pix_fmt discipline.

## cinematography (reading the shot before grading it)

- reading-a-shot.md: key/fill/ratio, motivated sources, inferring the setup, the play-the-clip rule.
- color-temperature-on-set.md: source temperatures, mixed-light contamination, gel conventions.
- exposure-placement.md: skin placement conventions, ETTR for log, vendor exposure guidance.
- what-grade-can-and-cannot-fix.md: honest fixability boundaries.
- lighting-and-story.md: color and light as narrative tools.

## detail-qc (the measurement discipline; this tool's heart)

- scopes-and-measurements.md: waveform/vectorscope/histogram and their numeric equivalents here.
- measurement-methodology.md: medians, frozen ROIs, per-region evidence, visual mask verification, structural confidence.
- qc-gates-reference.md: every gate with domain and value, hard vs soft, waivers, validation status (unvalidated defaults), run states.
- cross-shot-consistency.md: the per-shot normalization method and its traps; the humbling human-editor comparison.
- common-defects-catalog.md: symptom -> signature -> cause -> fix, from this project's own casebook.

## look-design (taste, structured)

- look-archetypes.md: archetypes as parameter recipes (teal-orange, bleach bypass, film print, noir, pastel, milky shadows).
- building-a-look-stack.md: corrections upstream, look downstream, view through the look; practitioner consensus and divergence.
- film-emulation-basics.md: halation, grain, density concepts (v1 emulates none; know the vocabulary).
- taste-and-references.md: deconstructing reference stills; inspiration, not pixel matching.
- look-intent-and-waivers.md: how creative intent overrides soft gates on the record.
