# SPDX-License-Identifier: MIT
from copy import deepcopy
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from colorist.measure import (
    FrozenMaskIdentityError,
    _load_frozen_mask,
    _save_frozen_mask,
    measure_shot,
    sample_positions,
    write_mask_sheet,
)
from colorist.render import ConvertParams, read_frame_rgb
from colorist.tools import resolve_tool
from colorist.workflow import _mask_payload


FFMPEG = resolve_tool("ffmpeg")
P709 = ConvertParams(range="full", matrix="bt709", transfer="bt709", primaries="bt709")


def write_ffv1(path: Path, frames: list[np.ndarray]) -> None:
    """Encode uint8 RGB frames as a lossless FFV1 fixture."""
    height, width, channels = frames[0].shape
    assert channels == 3
    assert all(frame.shape == (height, width, channels) for frame in frames)
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            "25",
            "-i",
            "-",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "rgb24",
            str(path),
        ],
        input=b"".join(frame.astype(np.uint8).tobytes() for frame in frames),
        check=True,
        capture_output=True,
    )


def rgb_frame(height: int = 48, width: int = 64) -> np.ndarray:
    """Return a saturated green frame that cannot pass the neutral mask."""
    return np.full((height, width, 3), (10, 220, 30), dtype=np.uint8)


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_measure_shot_reports_known_neutral_cast(tmp_path: Path):
    src = tmp_path / "cast.mkv"
    frame = rgb_frame()
    frame[8:28, 12:36] = (145, 135, 125)
    write_ffv1(src, [frame])

    decoded = read_frame_rgb(src, 0, P709)
    result = measure_shot(src, [0], P709, None, artifact_dir=tmp_path / "masks")

    assert result.neutral is not None
    assert np.allclose(result.neutral.median_rgb, decoded[12, 20], atol=1 / 255)


def test_measure_shot_returns_no_neutral_for_saturated_frame(tmp_path: Path):
    src = tmp_path / "no-neutral.mkv"
    write_ffv1(src, [rgb_frame()])

    result = measure_shot(src, [0], P709, None, artifact_dir=tmp_path / "masks")

    assert result.neutral is None


def test_sample_positions_returns_every_frame_for_short_shots():
    assert sample_positions(0) == []
    assert sample_positions(1) == [0]
    assert sample_positions(2) == [0, 1]


def test_measure_shot_rejects_cache_after_source_content_changes(tmp_path: Path):
    src = tmp_path / "frozen.mkv"
    original = rgb_frame()
    original[6:20, 6:20] = (145, 135, 125)
    write_ffv1(src, [original])
    initial = measure_shot(
        src, [0], P709, None, artifact_dir=tmp_path / "masks"
    )

    assert initial.neutral is not None
    assert initial.neutral.frozen_mask_path.is_file()

    modified = rgb_frame()
    modified[28:42, 38:52] = (170, 160, 150)
    write_ffv1(src, [modified])
    with pytest.raises(FrozenMaskIdentityError, match="source_digest"):
        measure_shot(src, [0], P709, None, artifact_dir=tmp_path / "masks")


def test_measure_shot_marks_opposed_regions_multimodal(tmp_path: Path):
    src = tmp_path / "opposed.mkv"
    frame = rgb_frame()
    frame[6:20, 6:20] = (150, 130, 140)
    frame[28:42, 38:52] = (140, 130, 150)
    write_ffv1(src, [frame])

    result = measure_shot(src, [0], P709, None, artifact_dir=tmp_path / "masks")

    assert result.neutral is not None
    assert result.neutral.multimodal is True
    assert result.neutral.multimodal_axes == ("r_minus_b",)
    assert result.neutral.median_rgb is None
    assert len(result.neutral.regions) == 2
    signs = [region.median_rgb[0] - region.median_rgb[2] for region in result.neutral.regions]
    assert max(signs) > 6 / 255
    assert min(signs) < -6 / 255


def test_measure_shot_marks_green_axis_disagreement_multimodal(tmp_path: Path):
    src = tmp_path / "green-opposed.mkv"
    frame = rgb_frame()
    frame[6:20, 6:20] = (140, 150, 140)
    frame[28:42, 38:52] = (150, 130, 150)
    write_ffv1(src, [frame])

    result = measure_shot(
        src, [0], P709, None, artifact_dir=tmp_path / "masks"
    )

    assert result.neutral is not None
    assert result.neutral.multimodal is True
    assert result.neutral.multimodal_axes == ("green_balance",)
    assert result.neutral.median_rgb is None
    payload = _mask_payload(result.neutral)
    assert payload is not None
    assert payload["multimodal_axes"] == ["green_balance"]
    assert {"median_rgb", "px", "bbox"} <= set(payload["regions"][0])


@pytest.mark.parametrize(
    "field",
    [
        "source_digest",
        "stream_identity",
        "declared_encoding",
        "convert_params",
        "frames",
        "mask_algorithm_version",
        "dimensions",
        "mask_type",
    ],
)
def test_frozen_mask_cache_rejects_each_identity_component(
    tmp_path: Path, field: str
) -> None:
    identity = {
        "source_digest": "sha256:abc",
        "stream_identity": {"index": 0, "codec_name": "ffv1"},
        "declared_encoding": "display-referred",
        "convert_params": {
            "range": "full",
            "matrix": "bt709",
            "transfer": "bt709",
            "primaries": "bt709",
        },
        "frames": [0, 1, 2],
        "mask_algorithm_version": "measurement-v3",
        "dimensions": {"width": 4, "height": 3},
        "mask_type": "neutral",
    }
    path = tmp_path / f"{field}.mask.npz"
    _save_frozen_mask(path, np.ones((3, 4), dtype=bool), identity)
    changed = deepcopy(identity)
    changed[field] = {"changed": True}

    with pytest.raises(FrozenMaskIdentityError, match=field):
        _load_frozen_mask(path, (3, 4), changed)


def test_write_mask_sheet_writes_expected_tile_grid(tmp_path: Path):
    src = tmp_path / "sheet.mkv"
    frame = rgb_frame()
    frame[4:10, 4:10] = (145, 135, 125)
    frame[18:25, 26:34] = (145, 135, 125)
    frame[35:43, 48:58] = (145, 135, 125)
    write_ffv1(src, [frame])
    mask = np.zeros(frame.shape[:2], dtype=bool)
    mask[4:10, 4:10] = True
    mask[18:25, 26:34] = True
    mask[35:43, 48:58] = True
    out_png = tmp_path / "mask-sheet.png"

    write_mask_sheet(src, 0, mask, out_png, P709, None)

    assert png_size(out_png) == (256, 256)


def test_region_stat_uses_per_pixel_r_minus_b_not_channel_medians(tmp_path: Path):
    """A neutral ROI with symmetric warm and cool pixels has equal channel

    medians (the old pooled statistic reads 0) but a large per-pixel median
    |R - B|. This exercises _region_stat end to end from real decoded pixels,
    which no other test does.
    """
    src = tmp_path / "symmetric.mkv"
    height, width = 24, 24
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[0::2] = (133, 128, 123)  # warm: R - B = +10
    frame[1::2] = (123, 128, 133)  # cool: R - B = -10
    write_ffv1(src, [frame, frame, frame])

    measurement = measure_shot(
        src, [0, 1, 2], P709, None, artifact_dir=tmp_path / "masks"
    )

    assert measurement.neutral is not None
    region = measurement.neutral.regions[0]
    # Per-pixel |R - B| median is about 10 code values; the channel medians are
    # equal, so the abandoned pooled statistic would have read about 0.
    assert region.r_minus_b_median == pytest.approx(10 / 255, abs=1.5 / 255)
    assert abs(region.median_rgb[0] - region.median_rgb[2]) <= 1.5 / 255


def test_skin_saturation_median_is_measured_from_real_pixels(tmp_path: Path):
    """The skin gate's saturation_median producer, otherwise only exercised via

    hand-built MaskStat objects, computed from decoded pixels at a known
    per-pixel HSV saturation.
    """
    src = tmp_path / "skin.mkv"
    # (200, 150, 120): hue about 22.5 deg, value 0.784, HSV saturation 0.40,
    # inside the skin candidate band.
    frame = np.full((24, 24, 3), (200, 150, 120), dtype=np.uint8)
    write_ffv1(src, [frame, frame, frame])

    measurement = measure_shot(
        src, [0, 1, 2], P709, None, artifact_dir=tmp_path / "masks"
    )

    assert measurement.skin is not None
    assert measurement.skin.saturation_median == pytest.approx(0.40, abs=2 / 255)
