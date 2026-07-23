# Recorded output: tools/measure_saturation_hue_drift.py

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Machine: arm64 Darwin 26.5.2
Python: Python 3.11.1
Date: 2026-07-23

```
Skin hue drift under a saturation change
  patches   ISO 17321-1: dark skin, light skin, rendered under D65
  operator  corrections._saturate, in the log grading space, as v1 applies it
  measured  Oklab hue angle, the space measured most hue-linear where skin lives
  matched   the Oklab comparison uses the chroma ratio v1 actually delivered

  dark skin: Oklab hue 43.45 deg, chroma 0.05651
     v1 sat  chroma x  v1 hue drift  Oklab hue drift   at matched chroma
       0.75    0.7361        1.637            0.000
       1.25    1.2721       -1.508            0.000
       1.50    1.5514       -2.892            0.000
       2.00    2.1269       -5.322            0.000

  light skin: Oklab hue 45.41 deg, chroma 0.06340
     v1 sat  chroma x  v1 hue drift  Oklab hue drift   at matched chroma
       0.75    0.7395        1.300            0.000
       1.25    1.2672       -1.233            0.000
       1.50    1.5406       -2.396            0.000
       2.00    2.1042       -4.518            0.000

  A positive drift is a rotation toward yellow, negative toward magenta.
```
