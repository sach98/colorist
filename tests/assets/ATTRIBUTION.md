<!-- SPDX-License-Identifier: MIT -->
# Test asset attribution

## smoke_scenes.mp4

Self-authored by this project. Not a third-party work.

- Generator: `tools/make_test_clip.py` (tracked). Reproduce with
  `python tools/make_test_clip.py tests/assets/smoke_scenes.mp4`.
- Content: six synthetic lavfi scenes (a neutral grey, a near-black, a warm
  light, a cool shadow, an SMPTE HD bars pattern, and a cool light), concatenated
  and encoded in the h264-yt-sdr delivery SHAPE: yuv420p, limited range, BT.709
  matrix, primaries, and transfer, all four color tags set. Its samples are
  deliberately not legal; see Purpose below.
- Purpose: a small, rights-clean smoke fixture with several visibly distinct
  scenes so scene detection finds cuts, one neutral scene so the neutral mask
  has evidence, and a bars scene whose below-legal pluge (Y = 14) gives the
  delivery range gate a genuine violation to catch.
- License: released to the public domain under
  [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). No attribution
  is required. Because it is fully synthetic and CC0, it may be redistributed
  with this repository without condition.
