# SPDX-License-Identifier: MIT
"""The design.md 4.3 render graph. The ONLY pixel-touching path in the project."""
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import numpy as np

from colorist.ffgraph import UnexpectedNegotiation
from colorist.tools import resolve_tool

FFMPEG = resolve_tool("ffmpeg")
FFPROBE = resolve_tool("ffprobe")


@dataclass(frozen=True)
class ConvertParams:
    range: str      # "full" | "limited" (sws names: "full"->"pc"/"jpeg", "limited"->"tv"/"mpeg")
    matrix: str     # e.g. "bt709"
    transfer: str   # e.g. "bt709" (metadata + LUT concern, not sws)
    primaries: str  # e.g. "bt709" (metadata + LUT concern, not sws)

    @property
    def sws_range(self) -> str:
        return {"full": "pc", "limited": "tv"}[self.range]

    def to_scale(self) -> str:
        # sws converts range and matrix explicitly; transfer/primaries are the
        # LUTs' job by design and are carried as encode metadata only.
        return (f"scale=in_range={self.sws_range}:out_range={self.sws_range}"
                f":in_color_matrix={self.matrix}:out_color_matrix={self.matrix}")


def _vf(idt_cube: Path | None, corr_cube: Path | None,
        in_params: ConvertParams, out_params: ConvertParams) -> str:
    # Mezzanine is RGB16 (gbrp16le): measured 2026-07-19, a YUV10 mezzanine leg
    # costs a 0.0608 max-error range bias on round-trip while RGB16 costs
    # 0.00056. RGB to YUV happens exactly once, at the delivery encode,
    # where verify.py's decoded-range fixtures police it. out_params carries
    # metadata for that later leg; the mezzanine itself stays matrix-free.
    steps = [in_params.to_scale(), "format=gbrpf32le"]
    if idt_cube is not None:
        steps.append(f"lut3d=interp=tetrahedral:file={idt_cube}")
    if corr_cube is not None:
        steps.append(f"lut3d=interp=tetrahedral:file={corr_cube}")
    steps.append("format=gbrp16le")
    return ",".join(steps)


def render_segment(src: Path, dst: Path, *, trim, idt_cube, corr_cube,
                   in_params: ConvertParams, out_params: ConvertParams) -> None:
    args = [FFMPEG, "-hide_banner", "-v", "verbose", "-y", "-i", str(src)]
    if trim is not None:
        start, end = trim  # frame indices, inclusive/exclusive
        args += ["-vf", f"trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS,"
                 + _vf(idt_cube, corr_cube, in_params, out_params)]
    else:
        args += ["-vf", _vf(idt_cube, corr_cube, in_params, out_params)]
    # RGB mezzanine: full-range by construction; matrix/transfer/primaries tags
    # belong to the single delivery-encode leg, not here.
    args += ["-color_range", "pc", "-c:v", "ffv1", "-an", str(dst)]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"render failed: {proc.stderr[-2000:]}")
    fmts = set(re.findall(r"fmt:([a-z0-9]+)", proc.stderr))
    allowed = {"gbrpf32le", "gbrp16le"}
    # source decode format appears before our first explicit conversion; allow it
    src_fmt = probe_pix_fmt(src)
    allowed.add(src_fmt)
    bad = fmts - allowed
    if bad:
        raise UnexpectedNegotiation(f"render graph negotiated {sorted(bad)}")


def probe_pix_fmt(path: Path) -> str:
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=pix_fmt", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def read_frame_rgb(
    path: Path, frame_index: int, in_params: ConvertParams
) -> np.ndarray:
    """Decode one frame to full-range BT.709 float RGB in the 0 to 1 range."""
    if not isinstance(in_params, ConvertParams):
        raise TypeError("in_params must be a ConvertParams instance")
    out = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-i", str(path),
        "-vf", f"select=eq(n\\,{frame_index}),"
               f"scale=in_range={in_params.sws_range}:out_range=pc:"
               f"in_color_matrix={in_params.matrix}:out_color_matrix=bt709,"
               "format=gbrpf32le", "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "gbrpf32le", "-"],
        capture_output=True, check=True)
    probe = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    w, h = (int(x) for x in probe.stdout.strip().split(","))
    planes = np.frombuffer(out.stdout, dtype=np.float32).reshape(3, h, w)
    g, b, r = planes  # gbrp plane order
    return np.stack([r, g, b], axis=-1).astype(np.float64)
