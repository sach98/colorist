# SPDX-License-Identifier: MIT
import numpy as np
import subprocess, shutil
from pathlib import Path
from colorist.lut import write_cube, apply_lut
from colorist.render import render_segment, read_frame_rgb, ConvertParams

P709 = ConvertParams(range="full", matrix="bt709", transfer="bt709", primaries="bt709")


def smooth_random_lut(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    ax = np.linspace(0, 1, n)
    r, g, b = np.meshgrid(ax, ax, ax, indexing="ij")
    ident = np.stack([r, g, b], -1)
    # smooth perturbation: low-order polynomial per channel, bounded
    coeff = rng.uniform(-0.08, 0.08, size=(3, 3))
    pert = np.stack([coeff[c, 0] * r * (1 - r) + coeff[c, 1] * g * (1 - g)
                     + coeff[c, 2] * b * (1 - b) for c in range(3)], -1)
    return np.clip(ident + pert, 0.0, 1.0)


def test_python_and_ffmpeg_agree(tmp_path: Path):
    lut = smooth_random_lut(33, seed=7)
    cube = tmp_path / "rand.cube"
    write_cube(cube, lut, "rand")
    src = tmp_path / "src.mkv"
    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-y",
        "-f", "lavfi", "-i", "gradients=size=128x72:rate=25:duration=0.2:seed=11",
        "-pix_fmt", "yuv444p10le", "-c:v", "ffv1", str(src)],
        check=True, capture_output=True)
    dst = tmp_path / "out.mkv"
    render_segment(src, dst, trim=None, idt_cube=None, corr_cube=cube,
                   in_params=P709, out_params=P709)
    x = read_frame_rgb(src, 2, P709)
    want = apply_lut(lut, x)
    got = read_frame_rgb(dst, 2, P709)
    err = float(np.abs(want - got).max())
    assert err <= 2 / 1023, f"max channel error {err:.6f} exceeds 2/1023"
