# Recorded output: tools/run_validation.py

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

The first validation run of the evaluation harness against its own Tier A corpus.

Machine: arm64 Darwin 26.5.2
Python: Python 3.11.1  ffmpeg: ffmpeg version 8.1.2
Date: 2026-07-23

```
Reference statistics, pinned masks, no defect
  technical_conform        10.00000
  skin_luma                50.75186
  skin_hue                 44.43993
  skin_chroma               0.05997
  neutral_consistency       0.00000
  tonal_black              24.30423
  tonal_highlight        -
  tonal_separation       -

Property 1 and 5: monotonicity and numeric agreement of the statistic

  chroma  -> skin_chroma            0.05997   0.05247   0.04498   0.03748   0.02998
             deviation from reference   0.00000   0.00750   0.01499   0.02249   0.02998
             monotonic in severity: True

  hue     -> skin_hue              44.43993  47.43993  50.43993  53.43993  56.43993
             deviation from reference   0.00000   3.00000   6.00000   9.00000  12.00000
             monotonic in severity: True

  tone    -> tonal_black           24.30423  24.12893  23.95421  23.78004  23.60641
             deviation from reference   0.00000   0.17529   0.35002   0.52419   0.69781
             monotonic in severity: True

Property 8: cross-dimension specificity
  A family must move its OWN dimension and not masquerade as another.

  family              skin_hue         skin_chroma         tonal_black neutral_consistency
  chroma                +0.00%             -50.00%              -0.00%              +0.00%
  hue                  +27.00%              -0.00%              -0.03%              +0.00%
  tone                  +4.38%             -45.98%              -2.87%              +0.00%

Property 13: equal whole-image distance, different per-dimension damage

  chroma  severity 0.0515   skin hue  +0.000 deg   skin chroma   -2.57%
  hue     severity 0.2341   skin hue  +2.810 deg   skin chroma   -0.00%

Property 12: reference-free statistic correctness
  Every statistic above was computed from the delivery alone. The
  reference was used only to pin the masks, never to fit a transform,
  so a metric that works by estimating the residual has nothing to fit.

All checked properties hold.
```
