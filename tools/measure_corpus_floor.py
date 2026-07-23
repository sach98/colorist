# SPDX-License-Identifier: MIT
"""Measure the corpus carrier's round-trip error, and the peak-convention trap.

WHY THIS MEASUREMENT EXISTS

The Tier A corpus claims its rendered scenes are analytic ground truth. That is
only true if writing a scene to a file and reading it back returns what was
rendered. This measures that, and it also records a trap that would silently
falsify every corpus expectation.

THE TRAP

ffmpeg's full-range 16 bit YUV carries the 8 bit full-range convention into 16
bits by shifting left 8, so its peak is 255 << 8 = 65280, not 65535. Writing
65535 as display white therefore overshoots by exactly 65535 / 65280 = 1.0039.

The dangerous part is what that looks like: not noise, not an obviously broken
image, but a clean picture with a gain on it. Every patch comes back slightly
too bright, consistently, and a corpus built on it would have a wrong ground
truth that no visual check would catch.

Run:

    .venv/bin/python tools/measure_corpus_floor.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import warnings

import numpy as np

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from colorist.corpus import ChartLayout, Scene, render  # noqa: E402
from colorist.render import ConvertParams, read_frame_rgb  # noqa: E402
from colorist.tools import resolve_tool  # noqa: E402


REC709_FULL = ConvertParams(range="full", matrix="bt709", transfer="bt709", primaries="bt709")
TRIALS = (
    (65535, "yuv444p16le", "peak 65535, lossless 4:4:4"),
    (255 << 8, "yuv444p16le", "peak 65280, lossless 4:4:4"),
    (65535, "gbrp16le", "peak 65535, lossless RGB"),
)


def write(image: np.ndarray, peak: int, pix_fmt: str, destination: Path) -> Path:
    height, width = image.shape[:2]
    payload = np.rint(np.clip(image, 0.0, 1.0) * peak).astype("<u2").tobytes() * 3
    result = subprocess.run(
        [
            resolve_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb48le",
            "-s", f"{width}x{height}", "-r", "25", "-i", "-", "-frames:v", "3",
            "-vf", f"scale=in_range=pc:out_range=pc:out_color_matrix=bt709,format={pix_fmt}",
            "-c:v", "ffv1", "-color_range", "pc", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-f", "matroska", str(destination),
        ],
        input=payload,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.decode("utf-8", "replace")[-2000:])
    return destination


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)

    scene = Scene(layout=ChartLayout(rows=4, columns=6, patch_size=16, gutter=4, margin=8))
    reference = render(scene)
    height, width = reference.shape[:2]
    flat = reference.reshape(-1, 3)

    print("Corpus carrier round trip: render, write, decode, compare")
    print(f"  scene       {width}x{height}, ISO 17321-1, D65, 24 patches")
    print(f"  decode      render.read_frame_rgb with full-range BT.709 params")
    print(f"  ffmpeg      {subprocess.run([resolve_tool('ffmpeg'), '-version'], capture_output=True, text=True).stdout.splitlines()[0]}")
    print()
    print(f"  {'carrier':<30} {'worst err':>10} {'in 8-bit':>10} {'fitted gain':>12}")
    print(f"  {'-' * 30} {'-' * 10} {'-' * 10} {'-' * 12}")

    with tempfile.TemporaryDirectory() as temporary:
        for peak, pix_fmt, label in TRIALS:
            path = write(reference, peak, pix_fmt, Path(temporary) / f"{peak}-{pix_fmt}.mkv")
            decoded = read_frame_rgb(path, 0, REC709_FULL)
            error = np.abs(decoded - reference)
            design = np.vstack([flat[:, 1], np.ones(len(flat))]).T
            (gain, _), *_ = np.linalg.lstsq(design, decoded.reshape(-1, 3)[:, 1], rcond=None)
            print(
                f"  {label:<30} {error.max():10.7f} {error.max() * 255:10.4f} {gain:12.6f}"
            )

    print()
    print(f"  65535 / 65280 = {65535 / 65280:.8f}, which is the gain the first row shows.")
    print("  The second row is the convention corpus.write_scene uses.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
