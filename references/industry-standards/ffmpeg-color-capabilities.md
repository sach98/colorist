# Ffmpeg Color Capabilities

<!-- SPDX-License-Identifier: CC-BY-4.0 -->

FFmpeg can execute the project's color pipeline, but its filtergraph behavior must be inspected and tested for the build in use. Project guidance: make color metadata, range, and pixel-format intent explicit at graph boundaries.

On FFmpeg 8.1.2, `lut3d` already reports `tetrahedral` as its default interpolation (`ffmpeg -h filter=lut3d`). This project still sets `interp=tetrahedral` explicitly for determinism across builds; it does not claim the explicit option changes the default on 8.1.2 [E: src/colorist/render.py, _vf].

The repository verified one FFmpeg 8.1.2 graph containing `eq` and `curves`: it negotiated through yuv444p and rgb24 [E: docs/spike-verdict.md]. That observation does not establish behavior for every graph or build. The project bans those filters from its core path and checks negotiated formats, because an unintended conversion can reduce precision or change interpretation [E: src/colorist/render.py, render_segment negotiated-format assertion].

Video may be full-range or limited-range. This project explicitly declares input and output range, primaries, transfer, and matrix parameters at conversion edges [E: src/colorist/render.py, ConvertParams and read_frame_rgb]. Omitting `out_range=tv` is not by itself guaranteed to crush or clip an image; the result depends on source range, destination range, and the rest of the graph.

This project uses FFV1 with gbrp16le RGB for temporary shot mezzanines and verifies the result it renders [E: src/colorist/render.py, _vf] [E: docs/spike-verdict.md]. FFmpeg's `scdet` reports scene-change candidates; it does not itself place encoder keyframes. The project maps proposals through frame PTS and validates cut lists before segment rendering [E: src/colorist/cuts.py].
