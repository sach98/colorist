# Recorded output: tools/measure_corpus_floor.py

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Machine: arm64 Darwin 26.5.2
Python: Python 3.11.1
Date: 2026-07-23

```
Corpus carrier round trip: render, write, decode, compare
  scene       132x92, ISO 17321-1, D65, 24 patches
  decode      render.read_frame_rgb with full-range BT.709 params
  ffmpeg      ffmpeg version 8.1.2 Copyright (c) 2000-2026 the FFmpeg developers

  carrier                         worst err   in 8-bit  fitted gain
  ------------------------------ ---------- ---------- ------------
  peak 65535, lossless 4:4:4      0.0037527     0.9569     1.003888
  peak 65280, lossless 4:4:4      0.0000733     0.0187     0.999975
  peak 65535, lossless RGB        0.0002934     0.0748     1.000138

  65535 / 65280 = 1.00390625, which is the gain the first row shows.
  The second row is the convention corpus.write_scene uses.
```
