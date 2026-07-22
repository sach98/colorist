# Measurement methodology

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

How this tool measures is as important as what it measures. Every rule below was purchased with a specific failure.

## Medians over means, shots over frames

For shots of three or more frames, `sample_positions` selects integer indices `n//4`, `n//2`, and `(3*n)//4`; these are approximate quarter, half, and three-quarter positions [E: src/colorist/measure.py, sample_positions]. The current implementation does not perform transition quarantine or flash rejection. For shorter shots, the helper returns every available frame [E: src/colorist/measure.py, sample_positions].

## Frozen ROIs

Masks for neutral and skin candidates are computed on source frames and frozen for later measurement [E: src/colorist/measure.py, _measure_mask]. This avoids changing the sampled pixels simply because the grade changes. A separate validity check should be added only when its implementation and test are present; this file does not claim one exists.

## Per-region evidence, never only pooled

Neutral evidence is reported per connected region. The white-balance gate reads the per-pixel statistic within each region: the median of the per-pixel absolute R minus B and of the per-pixel absolute G minus the mean of R and B, taking the worst region. This is deliberately not the absolute difference of the channel medians, which a region carrying symmetric warm and cool casts would report as zero [E: src/colorist/measure.py, _region_stat and evidence_from_measurement]. A pooled median for the white-balance solver is additionally withheld when the per-region medians disagree on either the R minus B or the green axis beyond the implemented multimodal thresholds [E: src/colorist/measure.py, _measure_mask]. The v1 global correction path does not implement spatial secondaries [E: repository LIMITS.md].

## Verify masks visually

An unverified mask can measure the set instead of the intended subject. The tool can write a contact sheet of masked regions for human inspection [E: src/colorist/measure.py, write_mask_sheet]. Project guidance: treat disagreement between measurement methods as an investigation into masks, sampling, and domain, not a number to average away.

## Confidence is structural, not decorative

Absent evidence yields null, never a fabricated number. Mask measurements carry sample counts, in pixels, per mask and per connected region; luma percentiles do not, because they are pooled over whole sampled frames [E: src/colorist/measure.py, MaskStat and RegionStat]. Gates whose evidence is absent skip with a stated reason, and required-coverage gates that skip make the whole run INDETERMINATE. A landscape with no neutrals and no skin cannot PASS by vacuity [E: repository run states, spec 2].
