# Recorded output: tools/measure_transfer_convention.py

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Machine: arm64 Darwin 26.5.2
Python: Python 3.11.1
ffmpeg: ffmpeg version 8.1.2 Copyright (c) 2000-2026 the FFmpeg developers
Date: 2026-07-23

```
Encoding, and what a BT.1886 gamma 2.4 display then shows

  scene linear  project code     shown    BT.709 OETF     shown
  ------------ ------------- ---------   ------------ ---------
       0.02000       0.19593   0.02000        0.09000   0.00309
       0.18000       0.48944   0.18000        0.40901   0.11699
       0.50000       0.74915   0.50000        0.70552   0.43293
       0.90000       0.95705   0.90000        0.94911   0.88218
       1.00000       1.00000   1.00000        1.00000   1.00000

  The project's encode round trips exactly: what you encode is what is shown.
  The OETF path does not, and is not meant to. The difference is the
  end-to-end system gamma intended for camera light in a dim surround.

Available ffmpeg color_trc values, to show none of them means BT.1886:
  bt709, unknown, gamma22, bt470m, gamma28, bt470bg, smpte170m, smpte240m, linear, log100, log316, iec61966-2-4, bt1361e, iec61966-2-1, bt2020-10, bt2020-12, smpte2084, smpte428, arib-std-b67, unspecified, log, log_sqrt, iec61966_2_4, bt1361, iec61966_2_1, bt2020_10bit, bt2020_12bit, smpte428_1

  There is no bt1886 option. 'bt709' is the conventional signal for
  Rec.709 SDR and is what the shipped delivery profiles declare, so the
  corpus uses it too. Read it as 'this is Rec.709 SDR', which is true,
  not as 'these samples follow the BT.709 OETF', which is false.
```
