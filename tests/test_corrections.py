# SPDX-License-Identifier: MIT
import colour
import numpy as np

from colorist.corrections import (
    Correction,
    SHAPER_BREAKPOINT,
    SHAPER_BREAKPOINT_GRADING,
    SHAPER_MAX,
    SHAPER_TOE_OFFSET,
    SHAPER_TOE_SLOPE,
    bt1886_decode,
    bt1886_encode,
    compile_shot_lut,
    from_manifest,
    inverse_shaper,
    manifest_dict,
    shaper,
    solve_exposure,
    solve_wb,
)
from colorist.lut import apply_lut


LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722])
SHAPER_ROUND_TRIP_ATOL = 2e-12
DEFAULT_COMPILED_IDENTITY_ATOL = 1e-12


def _code_lattice(n: int) -> np.ndarray:
    axis = np.linspace(0.0, 1.0, n)
    red, green, blue = np.meshgrid(axis, axis, axis, indexing="ij")
    return np.stack([red, green, blue], axis=-1)


def test_shaper_round_trip_is_invertible_from_zero_through_sixteen():
    values = np.unique(
        np.concatenate(
            [
                np.linspace(0.0, SHAPER_BREAKPOINT, 10_001),
                np.linspace(SHAPER_BREAKPOINT, 16.0, 200_001),
                np.array([0.0, SHAPER_BREAKPOINT, 16.0]),
            ]
        )
    )
    recovered = inverse_shaper(shaper(values))

    assert recovered[0] == 0.0
    np.testing.assert_allclose(
        recovered, values, atol=SHAPER_ROUND_TRIP_ATOL, rtol=0.0
    )


def test_shaper_is_monotonic_and_c1_at_breakpoint():
    values = np.linspace(
        SHAPER_BREAKPOINT * 0.5, SHAPER_BREAKPOINT * 1.5, 100_001
    )
    assert np.all(np.diff(shaper(values)) > 0.0)

    toe_at_breakpoint = (
        SHAPER_TOE_SLOPE * SHAPER_BREAKPOINT + SHAPER_TOE_OFFSET
    )
    np.testing.assert_allclose(
        toe_at_breakpoint, SHAPER_BREAKPOINT_GRADING, atol=1e-15, rtol=0.0
    )

    step = 1e-8
    shaped_breakpoint = float(shaper(np.array(SHAPER_BREAKPOINT)))
    left_slope = (
        shaped_breakpoint - float(shaper(np.array(SHAPER_BREAKPOINT - step)))
    ) / step
    right_slope = (
        float(shaper(np.array(SHAPER_BREAKPOINT + step))) - shaped_breakpoint
    ) / step
    np.testing.assert_allclose(
        [left_slope, right_slope], SHAPER_TOE_SLOPE, atol=1e-5, rtol=0.0
    )


def test_shaper_preserves_supported_camera_over_range_values_to_ceiling():
    values = np.array(
        [
            16.0,
            38.42093433720254,
            469.8,
            46.08552795674034,
            14.668301411196483,
            55.079576698813185,
            889.4055204847825,
            SHAPER_MAX,
        ]
    )
    np.testing.assert_allclose(
        inverse_shaper(shaper(values)), values, atol=2e-10, rtol=0.0
    )
    np.testing.assert_allclose(
        inverse_shaper(shaper(np.array([SHAPER_MAX, SHAPER_MAX * 2.0]))),
        SHAPER_MAX,
        atol=SHAPER_ROUND_TRIP_ATOL,
        rtol=0.0,
    )


def test_solve_wb_recovers_injected_diagonal_cast():
    cast = np.array([1.24, 0.91, 0.77])
    casted_neutral = np.full(3, 0.18) * cast
    recovered = np.array(solve_wb(casted_neutral))
    expected = np.dot(casted_neutral, LUMA_WEIGHTS) / casted_neutral
    np.testing.assert_allclose(recovered, expected, atol=1e-6, rtol=0.0)


def test_solve_wb_preserves_linear_rec709_luma():
    neutrals = (
        np.array([0.18, 0.18, 0.18]),
        np.array([0.3, 0.2, 0.1]),
        np.array([0.05, 0.08, 0.8]),
    )
    for neutral in neutrals:
        before = float(np.dot(neutral, LUMA_WEIGHTS))
        after = float(np.dot(neutral * solve_wb(neutral), LUMA_WEIGHTS))
        np.testing.assert_allclose(after, before, atol=1e-15, rtol=0.0)


def test_default_compiled_correction_is_code_lattice_identity():
    table = compile_shot_lut(Correction(), look=None, curve_gamut=None, n=65)
    lattice = _code_lattice(65)
    max_error = float(np.max(np.abs(table - lattice)))

    assert max_error <= DEFAULT_COMPILED_IDENTITY_ATOL
    np.testing.assert_array_equal(table[0, 0, 0], np.zeros(3))


def test_default_compiled_correction_preserves_black_and_near_black_ramps():
    table = compile_shot_lut(Correction(), look=None, curve_gamut=None, n=65)
    black_ramp = np.linspace(0.0, 1.0 / 255.0, 257)
    near_black_ramp = np.linspace(1.0 / 255.0, 0.08, 257)

    black = apply_lut(table, np.zeros((1, 3)))
    np.testing.assert_array_equal(black, np.zeros((1, 3)))
    for ramp in (black_ramp, near_black_ramp):
        neutral_ramp = np.repeat(ramp[:, None], 3, axis=1)
        corrected = apply_lut(table, neutral_ramp)
        assert np.all(np.diff(corrected, axis=0) > 0.0)
        np.testing.assert_allclose(
            corrected, neutral_ramp, atol=DEFAULT_COMPILED_IDENTITY_ATOL, rtol=0.0
        )


def test_default_compiled_correction_preserves_white():
    table = compile_shot_lut(Correction(), look=None, curve_gamut=None, n=65)
    white = apply_lut(table, np.ones((1, 3)))
    np.testing.assert_allclose(
        white, np.ones((1, 3)), atol=DEFAULT_COMPILED_IDENTITY_ATOL, rtol=0.0
    )


def test_injected_cast_is_neutral_after_compiled_lut():
    synthetic_code = np.array([20.0, 16.0, 12.0]) / 64.0
    synthetic_neutral = bt1886_decode(synthetic_code)
    grey = float(np.dot(synthetic_neutral, LUMA_WEIGHTS))
    corr = Correction(wb_gains=solve_wb(synthetic_neutral))
    table = compile_shot_lut(corr, look=None, curve_gamut=None, n=65)

    corrected = apply_lut(table, synthetic_code[None, :])[0]
    expected = bt1886_encode(np.full(3, grey))
    np.testing.assert_allclose(
        corrected, expected, atol=DEFAULT_COMPILED_IDENTITY_ATOL, rtol=0.0
    )


def test_solve_exposure_is_closed_form():
    assert solve_exposure(0.18, 0.36) == 1.0


def _compile_with_saturation_before_contrast(corr: Correction, n: int) -> np.ndarray:
    axis = np.linspace(0.0, 1.0, n)
    red, green, blue = np.meshgrid(axis, axis, axis, indexing="ij")
    display = np.stack([red, green, blue], axis=-1)
    linear = bt1886_decode(display)
    linear *= np.asarray(corr.wb_gains) * (2.0**corr.exposure_ev)
    grading = shaper(linear)
    luma = np.sum(grading * LUMA_WEIGHTS, axis=-1, keepdims=True)
    grading = luma + corr.saturation * (grading - luma)
    grading = corr.pivot * np.power(
        np.clip(grading, 0.0, None) / corr.pivot, corr.contrast
    )
    return bt1886_encode(inverse_shaper(grading))


def test_contrast_and_saturation_are_non_commutative():
    corr = Correction(contrast=1.6, saturation=0.35)
    standard = compile_shot_lut(corr, look=None, curve_gamut=None, n=17)
    swapped = _compile_with_saturation_before_contrast(corr, n=17)
    assert np.max(np.abs(standard - swapped)) > 1e-4


def test_manifest_round_trip_preserves_every_field():
    corr = Correction(
        wb_gains=(1.125, 0.9375, 1.03125),
        exposure_ev=-0.625,
        contrast=1.18,
        pivot=0.47,
        saturation=0.82,
    )
    encoded = manifest_dict(corr)
    assert encoded["schema"] == "colorist/correction/v1"
    assert from_manifest(encoded) == corr


def test_slog3_cast_neutralizes_to_bt1886_display_grey():
    base_cast = np.array([1.22, 0.91, 0.78])
    cast = base_cast * np.dot(1.0 / base_cast, LUMA_WEIGHTS)
    working_casted_grey = 0.18 * cast
    linear_camera = colour.RGB_to_RGB(
        working_casted_grey,
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        colour.RGB_COLOURSPACES["S-Gamut3.Cine"],
        chromatic_adaptation_transform="CAT02",
        apply_cctf_decoding=False,
        apply_cctf_encoding=False,
    )
    slog3_code = colour.models.log_encoding_SLog3(linear_camera)
    corr = Correction(wb_gains=solve_wb(working_casted_grey))

    table = compile_shot_lut(
        corr, look=None, curve_gamut="slog3_sgamut3cine", n=65
    )
    actual = apply_lut(table, slog3_code)
    grey = float(np.dot(working_casted_grey, LUMA_WEIGHTS))
    expected = bt1886_encode(inverse_shaper(shaper(np.full(3, grey))))
    np.testing.assert_allclose(actual, expected, atol=1 / 255, rtol=0.0)
