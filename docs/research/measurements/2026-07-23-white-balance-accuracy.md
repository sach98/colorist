# Recorded output: tools/measure_white_balance.py

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

Machine: arm64 Darwin 26.5.2
Python: Python 3.11.1
colour-science: 0.4.7
Date: 2026-07-23

```
White balance accuracy against an analytically known reference
  chart            ISO 17321-1 spectral reflectances, 24 patches
  observer         CIE 1931 2 Degree Standard Observer
  reference        the same chart rendered under D65
  neutral sample   'white 9.5 (.05 D)', given to the channel-gain solver exactly
  score            CIEDE2000 against the reference, lower is better

  illuminant A
    uncorrected            median  18.670   max  28.956   skin  14.166
    channel-gain (v1)      median   3.654   max  27.752   skin   5.102   worst on orange
    Von Kries              median   4.454   max   9.081   skin   2.741   worst on cyan
    Bradford               median   1.940   max   4.894   skin   2.820   worst on cyan
    CAT02                  median   2.457   max   5.373   skin   3.067   worst on magenta
    CAT16                  median   3.268   max   6.765   skin   3.003   worst on red

  illuminant FL2
    uncorrected            median   9.544   max  17.755   skin   8.632
    channel-gain (v1)      median   4.964   max  14.851   skin   6.892   worst on orange
    Von Kries              median   3.775   max  12.054   skin   5.975   worst on orange
    Bradford               median   3.091   max  10.101   skin   4.699   worst on orange
    CAT02                  median   2.951   max   9.338   skin   4.442   worst on orange
    CAT16                  median   3.656   max   9.900   skin   4.728   worst on orange

  illuminant FL11
    uncorrected            median  10.274   max  19.078   skin   8.555
    channel-gain (v1)      median   3.117   max  11.184   skin   2.782   worst on orange yellow
    Von Kries              median   4.143   max   9.019   skin   2.068   worst on orange yellow
    Bradford               median   2.272   max   6.792   skin   1.342   worst on orange yellow
    CAT02                  median   2.167   max   6.333   skin   1.246   worst on cyan
    CAT16                  median   3.107   max   6.995   skin   1.548   worst on cyan

  illuminant D50
    uncorrected            median   5.757   max  12.203   skin   4.974
    channel-gain (v1)      median   0.674   max   3.208   skin   0.537   worst on cyan
    Von Kries              median   1.168   max   2.091   skin   0.712   worst on cyan
    Bradford               median   0.563   max   1.244   skin   0.907   worst on light skin
    CAT02                  median   0.715   max   1.453   skin   0.960   worst on magenta
    CAT16                  median   0.817   max   1.711   skin   0.986   worst on red

  illuminant D75
    uncorrected            median   2.390   max   6.825   skin   2.710
    channel-gain (v1)      median   0.483   max   1.176   skin   0.526   worst on orange
    Von Kries              median   0.520   max   0.939   skin   0.304   worst on cyan
    Bradford               median   0.269   max   0.562   skin   0.398   worst on light skin
    CAT02                  median   0.316   max   0.599   skin   0.413   worst on light skin
    CAT16                  median   0.358   max   0.709   skin   0.441   worst on red

  pooled over all tested illuminants
    method                   median      p90      max   skin median
    ---------------------- -------- -------- -------- -------------
    Bradford                  0.727    4.352   10.101         1.444
    CAT02                     0.822    4.298    9.338         1.504
    CAT16                     1.028    4.852    9.900         1.549
    channel-gain (v1)         1.132    7.951   27.752         2.782
    Von Kries                 1.349    6.438   12.054         2.068

  best method: Bradford
  v1's channel-gain white balance leaves 1.132 dE2000 median where Bradford leaves 0.727, a factor of 1.56
```
