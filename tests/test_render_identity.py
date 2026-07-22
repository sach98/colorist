# SPDX-License-Identifier: MIT
import numpy as np
from pathlib import Path
from colorist.corrections import Correction, compile_shot_lut
from colorist.lut import write_cube
from colorist.render import render_segment, read_frame_rgb, ConvertParams

P709 = ConvertParams(range="full", matrix="bt709", transfer="bt709", primaries="bt709")


def test_identity_luts_preserve_pixels(tmp_path: Path):
    src = tmp_path / "src.mkv"
    # 8 frames of smooth gradient, full-range yuv444p10 source
    import subprocess, shutil
    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-y",
        "-f", "lavfi", "-i", "gradients=size=128x72:rate=25:duration=0.32",
        "-pix_fmt", "yuv444p10le", "-c:v", "ffv1", str(src)], check=True,
        capture_output=True)
    dst = tmp_path / "out.mkv"
    render_segment(src, dst, trim=None,
                   idt_cube=Path("tests/fixtures/identity17.cube"),
                   corr_cube=Path("tests/fixtures/identity17.cube"),
                   in_params=P709, out_params=P709)
    a = read_frame_rgb(src, 4, P709)
    b = read_frame_rgb(dst, 4, P709)
    assert a.shape == b.shape
    assert float(np.abs(a - b).max()) <= 2 / 1023


def test_compiled_default_correction_preserves_pixels(tmp_path: Path):
    src = tmp_path / "src.mkv"
    import subprocess, shutil
    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-y",
        "-f", "lavfi", "-i", "gradients=size=128x72:rate=25:duration=0.32",
        "-pix_fmt", "yuv444p10le", "-c:v", "ffv1", str(src)], check=True,
        capture_output=True)
    corr_cube = tmp_path / "compiled-default.cube"
    write_cube(
        corr_cube,
        compile_shot_lut(Correction(), look=None, curve_gamut=None),
        "compiled default correction",
    )
    dst = tmp_path / "out.mkv"
    render_segment(src, dst, trim=None, idt_cube=None, corr_cube=corr_cube,
                   in_params=P709, out_params=P709)
    a = read_frame_rgb(src, 4, P709)
    b = read_frame_rgb(dst, 4, P709)
    assert a.shape == b.shape
    assert float(np.abs(a - b).max()) <= 2 / 1023


def test_compiled_default_correction_keeps_exact_black(tmp_path: Path):
    """An all-black frame must stay black through the compiled default correction.

    The gradient fixtures above never reach exactly 0, so they cannot catch a
    shaper that lifts black. This does: the old black-floor shaper raised code 0
    to about 0.056, far above the tolerance below.
    """
    import subprocess, shutil
    src = tmp_path / "black.mkv"
    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-y",
        "-f", "lavfi", "-i", "color=c=black:size=64x48:rate=25:duration=0.2",
        "-frames:v", "3", "-pix_fmt", "yuv444p10le", "-color_range", "pc",
        "-colorspace", "bt709", "-color_trc", "bt709", "-color_primaries", "bt709",
        "-c:v", "ffv1", str(src)], check=True, capture_output=True)
    corr_cube = tmp_path / "compiled-default.cube"
    write_cube(
        corr_cube,
        compile_shot_lut(Correction(), look=None, curve_gamut=None),
        "compiled default correction",
    )
    dst = tmp_path / "out.mkv"
    render_segment(src, dst, trim=None, idt_cube=None, corr_cube=corr_cube,
                   in_params=P709, out_params=P709)
    rendered = read_frame_rgb(dst, 1, P709)
    assert float(rendered.max()) <= 2 / 1023
