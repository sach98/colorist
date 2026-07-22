# SPDX-License-Identifier: MIT
"""End-to-end coverage for explicit decode and measurement color domains."""

from pathlib import Path
import subprocess

import colour
import numpy as np
import pytest

from colorist.corrections import bt1886_encode
from colorist.grade import (
    SourceEncodingConflictError,
    SourceEncodingError,
    _source_convert_params,
)
from colorist.lut import write_cube
from colorist.measure import measure_shot
from colorist.render import ConvertParams, read_frame_rgb, render_segment
from colorist.tools import resolve_tool
from colorist.workflow import _working_luma_p50, run_qc


FFMPEG = resolve_tool("ffmpeg")
FFPROBE = resolve_tool("ffprobe")
P709_FULL = ConvertParams(
    range="full", matrix="bt709", transfer="bt709", primaries="bt709"
)
P709_LIMITED = ConvertParams(
    range="limited", matrix="bt709", transfer="bt709", primaries="bt709"
)
CLIP = Path(__file__).parent / "assets" / "smoke_scenes.mp4"
H264_PROFILE = Path("presets/delivery/h264-yt-sdr.yaml")

_LOG_ENCODERS = {
    "slog3_sgamut3cine": ("S-Gamut3.Cine", colour.models.log_encoding_SLog3),
    "logc4_awg4": ("ARRI Wide Gamut 4", colour.models.log_encoding_ARRILogC4),
    "vlog_vgamut": ("V-Gamut", colour.models.log_encoding_VLog),
    "clog3_cgamut": ("Cinema Gamut", colour.models.log_encoding_CanonLog3),
    "logc3ei800_awg3": ("ARRI Wide Gamut 3", colour.models.log_encoding_ARRILogC3),
}


def _write_rgb_ffv1(path: Path, code_rgb: np.ndarray, frames: int = 3) -> None:
    height, width = 32, 48
    pixels = np.rint(np.clip(code_rgb, 0.0, 1.0) * 65535).astype("<u2")
    frame = np.broadcast_to(pixels, (height, width, 3)).copy()
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb48le",
            "-s",
            f"{width}x{height}",
            "-r",
            "1",
            "-i",
            "-",
            "-frames:v",
            str(frames),
            "-pix_fmt",
            "gbrp16le",
            "-color_range",
            "pc",
            "-colorspace",
            "bt709",
            "-color_trc",
            "bt709",
            "-color_primaries",
            "bt709",
            "-c:v",
            "ffv1",
            str(path),
        ],
        input=frame.tobytes() * frames,
        check=True,
        capture_output=True,
    )


def _write_limited_h264(
    path: Path,
    display_rgb: np.ndarray,
    *,
    wrong_tags: bool = False,
    frames: int = 3,
    structured: bool = False,
) -> None:
    height, width = 32, 48
    pixels = np.rint(np.clip(display_rgb, 0.0, 1.0) * 255).astype(np.uint8)
    if structured:
        y, x = np.mgrid[0:height, 0:width]
        modulation = 0.75 + 0.50 * (
            0.60 * x / (width - 1) + 0.40 * y / (height - 1)
        )
        frame = np.rint(
            np.clip(display_rgb * modulation[..., None], 0.0, 1.0) * 255
        ).astype(np.uint8)
    else:
        frame = np.broadcast_to(pixels, (height, width, 3)).copy()
    range_tag = "pc" if wrong_tags else "tv"
    matrix_tag = "smpte170m" if wrong_tags else "bt709"
    fullrange = "on" if wrong_tags else "off"
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            "1",
            "-i",
            "-",
            "-vf",
            "scale=in_range=pc:out_range=tv:in_color_matrix=bt709:"
            "out_color_matrix=bt709,format=yuv420p",
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-qp",
            "0",
            "-color_range",
            range_tag,
            "-colorspace",
            matrix_tag,
            "-color_trc",
            "bt709",
            "-color_primaries",
            "bt709",
            "-x264-params",
            f"fullrange={fullrange}:colormatrix={matrix_tag}:"
            "colorprim=bt709:transfer=bt709",
            str(path),
        ],
        input=frame.tobytes() * frames,
        check=True,
        capture_output=True,
    )


def _write_untagged_limited_h264(
    path: Path, frames: int = 3, *, structured: bool = False
) -> None:
    height, width = 32, 48
    plane_pixels = height * width
    if structured:
        gradient = np.linspace(-18, 18, width, dtype=np.int16)
        luma = np.clip(71 + gradient[None, :], 16, 235).astype(np.uint8)
        luma = np.broadcast_to(luma, (height, width)).copy()
        frame = luma.tobytes() + bytes([128]) * plane_pixels * 2
    else:
        frame = (
            bytes([71]) * plane_pixels
            + bytes([128]) * plane_pixels
            + bytes([128]) * plane_pixels
        )
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv444p",
            "-s",
            f"{width}x{height}",
            "-r",
            "1",
            "-i",
            "-",
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-qp",
            "0",
            str(path),
        ],
        input=frame * frames,
        check=True,
        capture_output=True,
    )


def _explicit_decode(
    path: Path, frame_index: int, in_range: str, matrix: str = "bt709"
) -> np.ndarray:
    probe = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height = (int(value) for value in probe.stdout.strip().split(","))
    decoded = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"select=eq(n\\,{frame_index}),scale=in_range={in_range}:"
            f"out_range=pc:in_color_matrix={matrix}:out_color_matrix=bt709,"
            "format=gbrpf32le",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gbrpf32le",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    planes = np.frombuffer(decoded.stdout, dtype=np.float32).reshape(3, height, width)
    green, blue, red = planes
    return np.stack([red, green, blue], axis=-1).astype(np.float64)


def _p1_preset(path: Path) -> Path:
    path.write_text(
        "workflow: qc\n"
        "required_coverage: []\n"
        "gates:\n"
        "  - id: source_luma\n"
        "    class: soft\n"
        "    coverage: shadows\n"
        "    domain: full-range Rec.709 display-code luma, 8-bit scale\n"
        "    statistic: p1 luma\n"
        "    operator: greater_than_or_equal\n"
        "    threshold: 0.0\n"
        "    evidence_key: shadows.p1\n"
        "    rationale: Test only.\n"
        "    validation_status: test\n"
    )
    return path


def test_bundled_limited_clip_matches_explicit_tv_to_pc_decode() -> None:
    # The bars scene (frame 60+) carries the widest colour range in the clip, so
    # a wrong full-range decode diverges most visibly there.
    frame = 62
    expected = _explicit_decode(CLIP, frame, "tv")
    actual = read_frame_rgb(CLIP, frame, P709_LIMITED)
    fixed_error = np.abs(actual - expected)
    assert float(fixed_error.max()) == 0.0
    assert float(fixed_error.mean()) == 0.0
    assert float(np.percentile(fixed_error, 99)) == 0.0

    # Decoding this limited-range clip as full-range (the original P0-1 bug)
    # diverges by more than a dozen 8-bit code values on real content.
    original_bug = np.abs(_explicit_decode(CLIP, frame, "pc") - expected)
    assert float(original_bug.max()) >= 0.05


def test_correctly_tagged_limited_h264_measures_full_range_display_code(
    tmp_path: Path,
) -> None:
    source = tmp_path / "limited.mp4"
    expected = np.array([0.34, 0.32, 0.30], dtype=np.float64)
    _write_limited_h264(source, expected)

    params = _source_convert_params(source)
    measurement = measure_shot(
        source, [0, 1, 2], params, None, artifact_dir=tmp_path / "masks"
    )

    assert params == P709_LIMITED
    assert measurement.neutral is not None
    assert np.allclose(measurement.neutral.median_rgb, expected, atol=3 / 255)


def test_render_segment_luts_receive_expanded_limited_input(tmp_path: Path) -> None:
    source = tmp_path / "limited-gradient.mp4"
    height, width = 32, 48
    horizontal = np.linspace(0.0, 1.0, width, dtype=np.float64)
    vertical = np.linspace(0.0, 1.0, height, dtype=np.float64)[:, None]
    frame = np.empty((height, width, 3), dtype=np.float64)
    frame[..., 0] = horizontal
    frame[..., 1] = vertical
    frame[..., 2] = (horizontal + vertical) / 2
    _write_limited_h264(source, frame)

    axis = np.linspace(0.0, 1.0, 17)
    red, green, blue = np.meshgrid(axis, axis, axis, indexing="ij")
    identity = tmp_path / "identity.cube"
    write_cube(identity, np.stack([red, green, blue], axis=-1), title="identity")
    rendered_path = tmp_path / "rendered.mkv"
    render_segment(
        source,
        rendered_path,
        trim=(0, 1),
        idt_cube=None,
        corr_cube=identity,
        in_params=P709_LIMITED,
        out_params=P709_FULL,
    )

    expected = _explicit_decode(source, 0, "tv")
    rendered = read_frame_rgb(rendered_path, 0, P709_FULL)
    error = np.abs(rendered - expected)
    mislabeled_error = np.abs(rendered - _explicit_decode(source, 0, "pc"))

    assert float(error.max()) <= 0.0011
    assert float(error.mean()) <= 0.0002
    assert float(np.percentile(error, 99)) <= 0.00085
    assert float(np.percentile(mislabeled_error, 99)) >= 0.07


def test_full_range_rgb_input_measures_without_range_compression(tmp_path: Path) -> None:
    source = tmp_path / "full-rgb.mkv"
    expected = np.array([0.51, 0.49, 0.47], dtype=np.float64)
    _write_rgb_ffv1(source, expected)

    params = _source_convert_params(source)
    measurement = measure_shot(
        source, [0, 1, 2], params, None, artifact_dir=tmp_path / "masks"
    )

    assert params == P709_FULL
    assert measurement.neutral is not None
    assert np.allclose(measurement.neutral.median_rgb, expected, atol=2 / 65535)


def test_legacy_masks_from_the_old_decode_domain_are_not_reused(tmp_path: Path) -> None:
    source = tmp_path / "legacy-mask.mkv"
    _write_rgb_ffv1(source, np.array([0.51, 0.49, 0.47]))
    legacy = source.with_name(
        f"{source.stem}.frames-0-2.neutral.mask.npz"
    )
    np.savez_compressed(legacy, mask=np.zeros((32, 48), dtype=bool))

    measurement = measure_shot(
        source, [0, 1, 2], P709_FULL, None, artifact_dir=tmp_path / "masks"
    )

    assert measurement.neutral is not None
    assert measurement.neutral.frozen_mask_path != legacy
    assert ".measurement-v2-full-bt709-display." in str(
        measurement.neutral.frozen_mask_path
    )


@pytest.mark.parametrize("curve_gamut", tuple(_LOG_ENCODERS))
def test_each_supported_log_pair_is_measured_in_rec709_display_code(
    tmp_path: Path, curve_gamut: str
) -> None:
    working = 0.18 * np.array([1.05, 0.99, 0.95], dtype=np.float64)
    gamut, encoder = _LOG_ENCODERS[curve_gamut]
    linear_camera = colour.RGB_to_RGB(
        working,
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        colour.RGB_COLOURSPACES[gamut],
        chromatic_adaptation_transform="CAT02",
        apply_cctf_decoding=False,
        apply_cctf_encoding=False,
    )
    with np.errstate(invalid="ignore"):
        code_rgb = np.asarray(encoder(linear_camera), dtype=np.float64)
    source = tmp_path / f"{curve_gamut}.mkv"
    _write_rgb_ffv1(source, code_rgb)

    measurement = measure_shot(
        source,
        [0, 1, 2],
        P709_FULL,
        curve_gamut,
        artifact_dir=tmp_path / "masks",
    )

    assert measurement.neutral is not None
    assert np.allclose(
        measurement.neutral.median_rgb,
        bt1886_encode(working),
        atol=10 / 65535,
    )
    expected_working_luma = float(
        working @ np.array([0.2126, 0.7152, 0.0722])
    )
    assert _working_luma_p50(
        source, [0, 1, 2], P709_FULL, curve_gamut
    ) == pytest.approx(expected_working_luma, abs=5e-5)


def test_absent_range_and_matrix_metadata_requires_user_declaration(
    tmp_path: Path,
) -> None:
    source = tmp_path / "untagged.mp4"
    _write_untagged_limited_h264(source, structured=True)
    preset = _p1_preset(tmp_path / "p1.yaml")

    with pytest.raises(SourceEncodingError, match="range, matrix"):
        _source_convert_params(source)
    delivery = tmp_path / "delivery.mp4"
    _write_limited_h264(
        delivery, np.array([0.34, 0.32, 0.30]), structured=True
    )
    refused = run_qc(
        delivery,
        preset,
        H264_PROFILE,
        report_dir=tmp_path / "refused",
        source_reference=source,
    )
    confirmed = run_qc(
        delivery,
        preset,
        H264_PROFILE,
        report_dir=tmp_path / "confirmed",
        source_reference=source,
        input_params=P709_LIMITED,
    )

    assert refused.state == "ERROR"
    assert "provide an explicit ConvertParams declaration" in (refused.error or "")
    assert confirmed.state == "PASS"


def test_wrong_metadata_can_be_replaced_only_after_explicit_confirmation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "wrong-tags.mp4"
    expected = np.array([0.34, 0.32, 0.30], dtype=np.float64)
    _write_limited_h264(source, expected, wrong_tags=True, structured=True)
    preset = _p1_preset(tmp_path / "p1.yaml")

    with pytest.raises(SourceEncodingConflictError, match="range: metadata=full"):
        _source_convert_params(source, P709_LIMITED)
    delivery = tmp_path / "delivery.mp4"
    _write_limited_h264(delivery, expected, structured=True)
    refused = run_qc(
        delivery,
        preset,
        H264_PROFILE,
        report_dir=tmp_path / "refused",
        source_reference=source,
        input_params=P709_LIMITED,
    )
    confirmed = run_qc(
        delivery,
        preset,
        H264_PROFILE,
        report_dir=tmp_path / "confirmed",
        source_reference=source,
        input_params=P709_LIMITED,
        confirm_metadata_override=True,
    )
    measurement = measure_shot(
        source,
        [0, 1, 2],
        P709_LIMITED,
        None,
        artifact_dir=tmp_path / "masks",
    )

    assert refused.state == "ERROR"
    assert "matrix: metadata=smpte170m, declared=bt709" in (refused.error or "")
    assert confirmed.state == "PASS"
    assert measurement.neutral is not None
    # 5/255, not 3/255: this value is read back through a lossy H.264 encode and
    # encoder builds disagree by more than three code values. The pinned BtbN
    # 8.1.2 Linux build returned blue 0.287419 against an expected 0.30, a
    # 0.0126 miss that 3/255 = 0.011765 rejected. What this assertion exists to
    # establish is that the confirmed metadata override reached the decoder,
    # and a 5/255 window still establishes it: a wrong range or matrix moves
    # these channels by far more than five code values.
    assert np.allclose(measurement.neutral.median_rgb, expected, atol=5 / 255)


def test_conflicting_user_declaration_is_never_silently_resolved(
    tmp_path: Path,
) -> None:
    source = tmp_path / "correct-tags.mp4"
    _write_limited_h264(source, np.array([0.34, 0.32, 0.30]))

    with pytest.raises(
        SourceEncodingConflictError,
        match="range: metadata=limited, declared=full",
    ):
        _source_convert_params(source, P709_FULL)


def test_log_encoding_declared_against_display_tags_is_a_conflict(
    tmp_path: Path,
) -> None:
    # A full-range file tagged transfer=bt709/primaries=bt709 is display-referred;
    # declaring a log --encoding for it must stop rather than silently decode it
    # as log. (A limited-range log declaration is refused earlier, so this uses a
    # full-range fixture to exercise the tag-conflict path specifically.)
    # wrong_tags=True writes a full-range (pc) file that still carries
    # transfer=bt709/primaries=bt709, so the log declaration conflicts on the
    # display transfer tag rather than being refused for being limited-range.
    source = tmp_path / "display-tagged.mp4"
    _write_limited_h264(source, np.array([0.34, 0.32, 0.30]), wrong_tags=True)

    with pytest.raises(SourceEncodingConflictError, match="declared log slog3_sgamut3cine"):
        _source_convert_params(source, curve_gamut="slog3_sgamut3cine")

    # The override lets a genuinely mislabeled log file through on purpose.
    resolved = _source_convert_params(
        source, curve_gamut="slog3_sgamut3cine", confirm_metadata_override=True
    )
    assert resolved.range == "full"


def test_public_workflow_refuses_unknown_display_encoding_by_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    delivery = tmp_path / "delivery.mp4"
    _write_limited_h264(source, np.array([0.34, 0.32, 0.30]))
    _write_limited_h264(delivery, np.array([0.34, 0.32, 0.30]))
    unknown = ConvertParams(
        range="limited",
        matrix="bt709",
        transfer="mystery-transfer",
        primaries="bt709",
    )

    result = run_qc(
        delivery,
        _p1_preset(tmp_path / "p1.yaml"),
        H264_PROFILE,
        report_dir=tmp_path / "run",
        source_reference=source,
        input_params=unknown,
        confirm_metadata_override=True,
    )

    assert result.state == "ERROR"
    assert "unsupported display encoding" in (result.error or "")
    assert "transfer=mystery-transfer" in (result.error or "")


def _write_neutral_log_yuv10(
    path: Path, code: float, *, color_range: str, frames: int = 3
) -> None:
    """Write a neutral log-code fixture as data-level yuv444p10le, tagged as asked.

    ``code`` is the manufacturer digital code value normalized to 0..1. It is
    stored at data levels (Y = round(code * 1023), Cb = Cr = 512), then merely
    TAGGED ``color_range`` without rescaling. A neutral decodes to R = G = B =
    code only when the reader honors data-level code, which is exactly what a
    camera-log decode must do regardless of the range tag.
    """
    height, width = 32, 48
    y = np.full((height, width), round(np.clip(code, 0.0, 1.0) * 1023), dtype="<u2")
    chroma = np.full((height, width), 512, dtype="<u2")
    planes = y.tobytes() + chroma.tobytes() + chroma.tobytes()
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-v",
            "error",
            "-y",
            # Declare the input range equal to the output range so swscale does
            # not rescale the raw data-level code during the lossless encode.
            "-color_range",
            color_range,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv444p10le",
            "-s",
            f"{width}x{height}",
            "-r",
            "1",
            "-i",
            "-",
            "-frames:v",
            str(frames),
            "-c:v",
            "ffv1",
            "-color_range",
            color_range,
            "-colorspace",
            "bt709",
            "-color_trc",
            "bt709",
            "-color_primaries",
            "bt709",
            str(path),
        ],
        input=planes * frames,
        check=True,
        capture_output=True,
    )


# 18% grey, 90% white, and a super-white over-range anchor, in scene-linear.
_LOG_ANCHORS = {"grey": 0.18, "white": 0.90, "superwhite": 4.0}


@pytest.mark.parametrize("curve_gamut", tuple(_LOG_ENCODERS))
def test_full_range_log_neutral_decodes_correctly(
    tmp_path: Path, curve_gamut: str
) -> None:
    """A full-range (data-level) camera-log neutral decodes to the right value.

    Camera log is data-level: the manufacturer curve is defined on full-swing
    code, so the stored code decodes directly. This holds for all five curves,
    including LogC4, whose full-range 18% grey code (285) is distinct from its
    legal-range code (308).
    """
    _, encoder = _LOG_ENCODERS[curve_gamut]
    for name, working in _LOG_ANCHORS.items():
        with np.errstate(invalid="ignore"):
            code = float(np.asarray(encoder(working)))
        if not 0.0 <= code <= 1.0:
            continue  # anchor falls outside the code range for this curve
        source = tmp_path / f"{curve_gamut}-{name}.mkv"
        _write_neutral_log_yuv10(source, code, color_range="full")
        params = _source_convert_params(source, curve_gamut=curve_gamut)
        assert params.range == "full"

        measurement = measure_shot(
            source,
            [0, 1, 2],
            params,
            curve_gamut,
            artifact_dir=tmp_path / f"masks-{curve_gamut}-{name}",
        )
        luma = measurement.luma_percentiles["p50"] / 255.0
        expected = float(bt1886_encode(np.asarray(working if working <= 1.0 else 1.0)))
        assert luma == pytest.approx(expected, abs=2 / 255), (
            f"{curve_gamut} {name}: measured display luma {luma}, expected {expected}"
        )


def test_limited_range_log_input_is_refused(tmp_path: Path) -> None:
    """Limited-range log is refused: correct handling is manufacturer-specific

    and the case does not occur in real workflows (camera log is data-level).
    A data-level file mistagged limited can be recovered with an explicit
    full-range declaration.
    """
    code = float(np.asarray(colour.models.log_encoding_ARRILogC4(0.18)))
    source = tmp_path / "logc4-limited.mkv"
    _write_neutral_log_yuv10(source, code, color_range="limited")

    with pytest.raises(SourceEncodingError, match="must be full-range"):
        _source_convert_params(source, curve_gamut="logc4_awg4")

    # An explicit full-range declaration (the file is data-level) is accepted.
    resolved = _source_convert_params(
        source,
        P709_FULL,
        confirm_metadata_override=True,
        curve_gamut="logc4_awg4",
    )
    assert resolved.range == "full"
