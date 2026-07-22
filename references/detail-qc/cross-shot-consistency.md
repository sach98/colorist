# Cross-shot consistency

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Cross-cut changes in white balance or exposure can be conspicuous even when an individual frame looks acceptable. Project guidance: inspect cuts as a sequence, not only as isolated stills.

## The method

1. Accept an authoritative cut list or generate and review scene-change proposals [E: src/colorist/cuts.py].
2. Measure each shot's frozen regions and record per-region evidence [E: src/colorist/measure.py].
3. Solve white-balance gains only when the neutral evidence is eligible and unimodal [E: src/colorist/corrections.py] [E: src/colorist/measure.py].
4. Choose and document the exposure reference for the sequence.
5. Apply the global look after the project correction order [E: src/colorist/corrections.py, compile_shot_lut].
6. Re-measure the rendered delivery per shot [E: src/colorist/verify.py].

## What to watch

- The project reports R minus B and a green axis because each is a different working-RGB measure [E: src/colorist/measure.py].
- Project guidance: choose stable, visually verified exposure references and document the target.
- Matching neutrals does not establish a match for saturated colors; v1 has no secondaries to repair camera-specific hue differences [E: repository LIMITS.md].
- Multimodal neutral evidence causes the tool to withhold a pooled white-balance solution and report regions [E: src/colorist/measure.py].
- Project guidance: compare the result against a reviewed reference grade when the job requires that standard.
