# SPDX-License-Identifier: MIT
"""Generate the self-authored, CC0 multi-scene smoke-test clip.

This replaces the previously bundled third-party excerpt. Everything here is
synthetic and authored by this project, so the output carries no third-party
rights. The clip is deliberately small and has several visibly distinct scenes
so scene detection finds cuts, including one neutral grey scene so the neutral
mask has evidence. It is encoded in the h264-yt-sdr delivery SHAPE: yuv420p,
limited range, BT.709 matrix/primaries/transfer, all four tags set. The bars
scene carries a below-legal pluge on purpose, so the clip conforms in codec,
pixel format, container, and tags but deliberately fails the sample-range gate.

Run: python tools/make_test_clip.py tests/assets/smoke_scenes.mp4
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from colorist.tools import resolve_tool

FFMPEG = resolve_tool("ffmpeg")

WIDTH, HEIGHT, FPS, SCENE_FRAMES = 320, 180, 25, 15

# Each scene is a full-frame lavfi source. Distinct luma and hue per scene make
# the cuts unambiguous; the neutral grey scene gives the white-balance gate
# real evidence. Values are chosen to sit inside legal Rec.709 after encode.
SCENES = [
    "color=c=0x7F7F7F",                         # neutral mid grey
    "color=c=0x1C1C1C",                         # near-black
    "color=c=0xCFC7B8",                         # warm light
    "color=c=0x2E3F55",                         # cool shadow
    "smptehdbars",                              # color bars
    "color=c=0xB8C4CF",                         # cool light
]


def main(out: Path) -> int:
    inputs: list[str] = []
    for scene in SCENES:
        # color=c=... already carries an '=', so its options join with ':';
        # bare sources like smptehdbars take their first option with '='.
        sep = ":" if "=" in scene else "="
        inputs += [
            "-f", "lavfi",
            "-t", f"{SCENE_FRAMES / FPS}",
            "-i", f"{scene}{sep}size={WIDTH}x{HEIGHT}:rate={FPS}",
        ]
    concat = (
        "".join(f"[{i}:v]" for i in range(len(SCENES)))
        + f"concat=n={len(SCENES)}:v=1:a=0,"
        "scale=in_range=pc:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,"
        "format=yuv420p[v]"
    )
    args = [
        FFMPEG, "-hide_banner", "-v", "error", "-y",
        *inputs,
        "-filter_complex", concat,
        "-map", "[v]",
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        "-x264-params", "fullrange=off:colormatrix=bt709:colorprim=bt709:transfer=bt709",
        str(out),
    ]
    subprocess.run(args, check=True)
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/assets/smoke_scenes.mp4")
    raise SystemExit(main(target))
