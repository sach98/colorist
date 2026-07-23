# Recorded output: tools/measure_hue_linearity.py

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Machine: arm64 Darwin 26.5.2
Python: Python 3.11.1
colour-science: 0.4.7
numpy: 2.4.6
Date: 2026-07-23

## Default run (CAT02)

```
Hue linearity against the Munsell renotation 'real' set
  loci                  304 (constant hue and value, >= 4 chromas)
  samples               2602
  adaptation C to D65   Von Kries / CAT02
  Jzazbz diffuse white  100 cd/m2
  CAM16 viewing         L_A 20, Y_b 20, average surround

Per-locus hue angle wander in degrees. Lower is better.

  space          median      p90    worst   worst locus
  ------------ -------- -------- --------   --------------------
  Oklab           3.796    9.076   32.539   5PB 3/
  CAM16-UCS       3.993   11.113   37.649   7.5PB 1/
  Jzazbz          4.329    8.891   19.783   5PB 4/
  ICtCp           4.785    9.559   16.282   5PB 4/
  IPT             4.895   11.627   18.870   5PB 3/
  CIELAB          5.160   10.370   27.723   7.5PB 1/

Best median hue linearity, all hues: Oklab

Median wander in degrees by Munsell hue family. R YR Y carry skin.

  space              B      BG       G      GY       P      PB       R      RP       Y      YR
  ------------  ------  ------  ------  ------  ------  ------  ------  ------  ------  ------
  Oklab           8.60    2.46    6.05    3.45    2.41    9.56    3.43    2.48    3.07    6.14
  CAM16-UCS       4.30    2.56    3.18    4.86   12.41    8.76    3.67    2.93    2.65    7.90
  Jzazbz          6.07    2.73    7.69    3.97    2.21    7.84    3.77    2.78    4.63    6.74
  ICtCp           3.84    5.02    6.28    1.30    5.11    7.53    6.34    3.63    4.10    8.52
  IPT             3.22    3.65    5.96    2.30    5.42    8.02    3.73    3.01    8.53   12.30
  CIELAB          6.65    2.59    6.69    8.05    4.16    9.45    3.50    3.09    6.51    6.09

Skin-carrying families only (R, YR, Y):
  Oklab         3.618
  CAM16-UCS     4.064
  Jzazbz        4.694
  CIELAB        5.250
  ICtCp         5.871
  IPT           7.359

Best hue linearity where skin lives: Oklab
```

## --cat "Bradford"

```
Hue linearity against the Munsell renotation 'real' set
  loci                  304 (constant hue and value, >= 4 chromas)
  samples               2602
  adaptation C to D65   Von Kries / Bradford
  Jzazbz diffuse white  100 cd/m2
  CAM16 viewing         L_A 20, Y_b 20, average surround

Per-locus hue angle wander in degrees. Lower is better.

  space          median      p90    worst   worst locus
  ------------ -------- -------- --------   --------------------
  Oklab           3.785    8.987   32.002   5PB 3/
  CAM16-UCS       3.967   10.962   36.824   7.5PB 1/
  Jzazbz          4.309    8.855   19.616   5PB 4/
  ICtCp           4.766    9.505   16.138   5PB 4/
  IPT             4.882   11.253   18.605   5PB 3/
  CIELAB          5.160   10.370   27.723   7.5PB 1/

Best median hue linearity, all hues: Oklab

Median wander in degrees by Munsell hue family. R YR Y carry skin.

  space              B      BG       G      GY       P      PB       R      RP       Y      YR
  ------------  ------  ------  ------  ------  ------  ------  ------  ------  ------  ------
  Oklab           8.39    2.46    6.04    3.50    2.39    9.50    3.42    2.47    3.05    6.10
  CAM16-UCS       4.31    2.58    3.20    4.66   12.46    8.65    3.63    2.92    2.65    7.74
  Jzazbz          5.94    2.75    7.68    4.04    2.19    7.75    3.75    2.77    4.59    6.69
  ICtCp           3.85    5.05    6.32    1.28    5.07    7.51    6.34    3.62    4.07    8.43
  IPT             3.23    3.67    6.01    2.31    5.38    7.94    3.73    3.00    8.18   11.90
  CIELAB          6.65    2.59    6.69    8.05    4.16    9.45    3.50    3.09    6.51    6.09

Skin-carrying families only (R, YR, Y):
  Oklab         3.622
  CAM16-UCS     4.071
  Jzazbz        4.670
  CIELAB        5.250
  ICtCp         5.836
  IPT           7.105

Best hue linearity where skin lives: Oklab
```

## --cat "CAT16"

```
Hue linearity against the Munsell renotation 'real' set
  loci                  304 (constant hue and value, >= 4 chromas)
  samples               2602
  adaptation C to D65   Von Kries / CAT16
  Jzazbz diffuse white  100 cd/m2
  CAM16 viewing         L_A 20, Y_b 20, average surround

Per-locus hue angle wander in degrees. Lower is better.

  space          median      p90    worst   worst locus
  ------------ -------- -------- --------   --------------------
  Oklab           3.857    8.963   31.626   5PB 3/
  CAM16-UCS       3.982   10.931   33.883   7.5PB 1/
  Jzazbz          4.357    9.038   19.579   5PB 4/
  ICtCp           4.711    9.383   16.128   5PB 4/
  IPT             4.939   11.827   21.263   5YR 6/
  CIELAB          5.160   10.370   27.723   7.5PB 1/

Best median hue linearity, all hues: Oklab

Median wander in degrees by Munsell hue family. R YR Y carry skin.

  space              B      BG       G      GY       P      PB       R      RP       Y      YR
  ------------  ------  ------  ------  ------  ------  ------  ------  ------  ------  ------
  Oklab           8.46    2.45    6.10    3.50    2.33    9.79    3.39    2.47    3.30    6.36
  CAM16-UCS       4.23    2.51    3.24    4.89   12.42    8.69    3.69    2.94    2.60    8.14
  Jzazbz          6.02    2.68    7.75    4.05    2.09    7.84    3.69    2.77    4.80    6.87
  ICtCp           3.75    4.94    6.39    1.34    4.86    7.15    6.18    3.61    4.31    8.72
  IPT             3.15    3.59    6.08    2.49    5.12    7.74    3.69    2.96    9.03   12.63
  CIELAB          6.65    2.59    6.69    8.05    4.16    9.45    3.50    3.09    6.51    6.09

Skin-carrying families only (R, YR, Y):
  Oklab         3.714
  CAM16-UCS     4.109
  Jzazbz        4.831
  CIELAB        5.250
  ICtCp         5.824
  IPT           7.682

Best hue linearity where skin lives: Oklab
```

## --cat "Von Kries"

```
Hue linearity against the Munsell renotation 'real' set
  loci                  304 (constant hue and value, >= 4 chromas)
  samples               2602
  adaptation C to D65   Von Kries / Von Kries
  Jzazbz diffuse white  100 cd/m2
  CAM16 viewing         L_A 20, Y_b 20, average surround

Per-locus hue angle wander in degrees. Lower is better.

  space          median      p90    worst   worst locus
  ------------ -------- -------- --------   --------------------
  Oklab           3.909    9.303   32.929   5PB 3/
  CAM16-UCS       3.920   11.025   33.627   7.5PB 1/
  Jzazbz          4.392    9.087   20.082   5PB 4/
  ICtCp           4.739    9.352   16.630   5PB 4/
  IPT             4.848   11.685   18.669   5PB 3/
  CIELAB          5.160   10.370   27.723   7.5PB 1/

Best median hue linearity, all hues: Oklab

Median wander in degrees by Munsell hue family. R YR Y carry skin.

  space              B      BG       G      GY       P      PB       R      RP       Y      YR
  ------------  ------  ------  ------  ------  ------  ------  ------  ------  ------  ------
  Oklab           8.64    2.42    6.11    3.58    2.32    9.54    3.37    2.45    3.46    6.42
  CAM16-UCS       4.14    2.44    3.28    4.72   12.42    9.43    3.67    2.93    2.47    8.05
  Jzazbz          6.20    2.67    7.77    4.18    2.05    8.05    3.63    2.75    4.89    6.90
  ICtCp           3.77    4.86    6.44    1.28    4.82    6.85    6.12    3.62    4.46    8.77
  IPT             3.11    3.54    6.18    2.39    5.07    8.18    3.67    2.96    8.95   12.44
  CIELAB          6.65    2.59    6.69    8.05    4.16    9.45    3.50    3.09    6.51    6.09

Skin-carrying families only (R, YR, Y):
  Oklab         3.874
  CAM16-UCS     4.075
  Jzazbz        4.937
  CIELAB        5.250
  ICtCp         5.889
  IPT           7.753

Best hue linearity where skin lives: Oklab
```
