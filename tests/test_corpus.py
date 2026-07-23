# SPDX-License-Identifier: MIT
"""Tier A corpus: layout geometry, injected defects, and the oracle itself.

The corpus is only worth anything if its claimed ground truth is the ground
truth, and establishing that takes two different kinds of test.

Most tests here compare `render()` against `expected_patches()`. Both call
`patch_display_rgb`, so those tests check placement and gathering and nothing
more. An earlier version of this docstring called them independent derivations.
That was wrong: an error inside `patch_display_rgb` moves both sides together and
every one of those tests still passes.

The genuinely independent checks are the two at the end of the file, which
compare against data this module does not compute: BabelColor's published
chromaticities for the ColorChecker, and the BT.709 matrix as published rather
than as colour-science derives it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from colorist.corpus import (
    GRAIN_AMPLITUDE_CODES,
    ChartLayout,
    CorpusError,
    Material,
    Scene,
    SoftScene,
    active_aperture,
    add_grain,
    add_letterbox,
    clipping_report,
    delivery_interior_mask,
    equal_distance_pair,
    expected_patches,
    frame_distance,
    inject,
    inject_many,
    illuminant_map,
    invert,
    masked_statistic,
    measure_delivery_floor,
    patch_display_rgb,
    patch_map,
    predicted_quantisation_ceiling,
    recoverable_patches,
    patch_linear_rgb,
    reference_roi,
    render_soft,
    severity_for_distance,
    soft_coverage,
    soft_trimap,
    split_through_cell,
    write_delivery,
    write_scene,
    render,
)


def _grid(**overrides) -> ChartLayout:
    settings = {"rows": 4, "columns": 6, "patch_size": 16, "gutter": 4, "margin": 8}
    settings.update(overrides)
    return ChartLayout(**settings)


def test_layout_rectangles_do_not_overlap_and_fit_the_frame() -> None:
    layout = _grid()
    width, height = layout.resolution()
    covered = np.zeros((height, width), dtype=np.int32)
    for cell in range(layout.cells):
        x0, y0, x1, y1 = layout.rect(cell)
        assert 0 <= x0 < x1 <= width
        assert 0 <= y0 < y1 <= height
        covered[y0:y1, x0:x1] += 1
    assert covered.max() == 1, "patch rectangles overlap"
    assert covered.sum() == layout.cells * layout.patch_size**2


def test_layout_resolution_is_even_for_chroma_subsampled_delivery() -> None:
    """4:2:0 cannot represent an odd dimension, so the generator must not make one."""
    for patch_size, gutter, margin in ((15, 3, 7), (16, 4, 8), (9, 1, 1)):
        width, height = _grid(patch_size=patch_size, gutter=gutter, margin=margin).resolution()
        assert width % 2 == 0 and height % 2 == 0


def test_layout_order_moves_a_patch_somewhere_else() -> None:
    """Held-out layouts are only held out if the order actually relocates patches."""
    identity = _grid()
    shuffled = _grid(order=tuple(reversed(range(identity.cells))))
    assert identity.rect_for_patch(0) != shuffled.rect_for_patch(0)
    assert shuffled.rect_for_patch(0) == identity.rect(identity.cells - 1)


def test_layout_rejects_an_order_that_is_not_a_permutation() -> None:
    with pytest.raises(CorpusError, match="permutation"):
        _grid(order=(0, 0, 1, 2))


def test_rendered_patches_are_placed_where_the_layout_says() -> None:
    """Every patch lands in its cell, carrying the value the oracle computed.

    SCOPE, corrected after review. render() and expected_patches() both call
    patch_display_rgb, so this compares a function against itself and can only
    catch placement, gathering, and layout errors. It CANNOT catch a wrong
    observer, normalisation, matrix, transfer, or global gain, because such an
    error would move "truth" and "rendered" together.

    An earlier docstring here claimed the two derivations were independent. They
    are not. The independent checks are
    test_spectral_rendering_matches_independently_published_chromaticities and
    test_the_xyz_to_rec709_step_matches_the_published_matrix.

    Exact equality is still the right assertion for what this DOES test: a gather
    from a lookup table should reproduce the table bit for bit, so a tolerance
    would only hide a placement bug.
    """
    scene = Scene(layout=_grid(), illuminant="D65")
    image = render(scene)
    truth = expected_patches(scene)
    names = list(truth)

    for cell, patch_index in enumerate(scene.layout.placement):
        x0, y0, x1, y1 = scene.layout.rect(cell)
        block = image[y0:y1, x0:x1]
        assert np.all(block == block[0, 0]), "a patch is not uniform"
        assert np.array_equal(block[0, 0], truth[names[patch_index]])


def test_rendering_under_another_illuminant_on_a_daylight_balance_carries_a_cast() -> None:
    """Defect family D1 in its simplest form: the camera stayed on D65."""
    reference = Scene(layout=_grid(), illuminant="D65")
    defect = Scene(layout=_grid(), illuminant="A")

    neutral = "neutral 5 (.70 D)"
    balanced = patch_display_rgb("ISO 17321-1", neutral, "D65")
    cast = patch_display_rgb("ISO 17321-1", neutral, "A")

    # The chart's neutral is a real paint with a slightly tilted reflectance, not
    # a mathematical flat spectrum, so under D65 it lands at R minus B of about
    # 0.00036, which is under a tenth of an 8-bit code value. That is the corpus
    # floor for "neutral", and asserting anything tighter would be asserting
    # something untrue about the physical sample.
    assert abs(balanced[0] - balanced[2]) < 1 / 255
    assert cast[0] - cast[2] > 0.05, "tungsten should leave the neutral warm"
    assert not np.array_equal(render(reference), render(defect))


def test_balancing_the_camera_for_the_scene_light_removes_the_cast() -> None:
    """A correctly balanced camera is the reference case, not a defect."""
    neutral = "neutral 5 (.70 D)"
    balanced = patch_display_rgb("ISO 17321-1", neutral, "A", balanced_for="A")
    assert abs(balanced[0] - balanced[2]) < 0.02


def test_camera_balance_is_one_setting_for_the_whole_frame() -> None:
    """The bug this pins: balance must not be applied per pixel's own light.

    An earlier version adapted each pixel FROM its own illuminant, which on a
    split scene is a per-region correction and silently removed the very defect
    the split exists to create. Measured on the neutral patch, the warm-to-cool
    split collapsed from 97.6 of an 8-bit code value to 0.256.

    Balancing for A must therefore leave the D65 region cool, and balancing for
    D65 must leave the A region warm. Neither may come out neutral on both sides.
    """
    neutral = "neutral 5 (.70 D)"

    def warmth(illuminant: str, balanced_for: str) -> float:
        rgb = patch_display_rgb("ISO 17321-1", neutral, illuminant, balanced_for)
        return float(rgb[0] - rgb[2])

    assert warmth("D65", "D65") == pytest.approx(0.0, abs=0.005)
    assert warmth("A", "A") == pytest.approx(0.0, abs=0.02)
    # Camera on daylight, scene on tungsten: strongly warm, not corrected.
    assert warmth("A", "D65") > 0.3
    # Camera on tungsten, scene on daylight: strongly cool, not corrected.
    assert warmth("D65", "A") < -0.15


def test_a_split_scene_lights_one_patch_two_ways() -> None:
    """Defect family D2: the mixed-lighting case a global correction cannot fix.

    The split is per pixel, so a patch straddling the boundary carries both
    illuminants, which is the white shirt reading warm on one side and cool on
    the other.
    """
    layout = _grid()
    width, _ = layout.resolution()
    # A boundary at exactly half frame width lands in a gutter for this layout,
    # which would make the test pass vacuously. split_through_cell guarantees the
    # case the family exists to model.
    cut_cell = 8
    scene = Scene(
        layout=layout,
        illuminant="D65",
        second_illuminant="A",
        split_at=split_through_cell(layout, cut_cell),
    )
    image = render(scene)
    boundary = int(round(scene.split_at * width))

    x0, y0, x1, y1 = layout.rect(cut_cell)
    assert x0 < boundary < x1, "split_through_cell did not bisect the cell"
    left = image[y0:y1, x0:boundary]
    right = image[y0:y1, boundary:x1]
    left_warmth = float(np.median(left[..., 0] - left[..., 2]))
    right_warmth = float(np.median(right[..., 0] - right[..., 2]))
    assert right_warmth - left_warmth > 0.02, (
        "the tungsten side of a straddling patch should read warmer"
    )


def test_the_split_defect_is_large_on_a_neutral_patch() -> None:
    """The defect must be big where a colourist would actually see it.

    The previous version of this file tested the split only on a coloured patch,
    where illuminant metamerism leaves a residue even when the cast has been
    adapted away. That let a scene whose defect had been silently corrected pass:
    the neutral split was 0.256 of a code value while the test looked elsewhere
    and saw enough to be satisfied.

    A neutral patch is the honest place to measure a white-balance defect, so this
    puts the chart's mid grey in the cell the boundary cuts and requires the split
    to be unmistakable. For scale, the real interview clip that motivated this work
    measured a 51 code value R minus B split across one white shirt.
    """
    import colour

    names = list(colour.SDS_COLOURCHECKERS["ISO 17321-1"].keys())
    neutral_index = names.index("neutral 5 (.70 D)")
    cut_cell = 8
    order = list(range(24))
    order[cut_cell], order[neutral_index] = order[neutral_index], order[cut_cell]
    layout = _grid(order=tuple(order))

    scene = Scene(
        layout=layout,
        illuminant="D65",
        second_illuminant="A",
        split_at=split_through_cell(layout, cut_cell),
    )
    image = render(scene)
    width, _ = layout.resolution()
    boundary = int(round(scene.split_at * width))
    x0, y0, x1, y1 = layout.rect(cut_cell)

    left = image[y0:y1, x0:boundary]
    right = image[y0:y1, boundary:x1]
    split = abs(
        float(np.median(right[..., 0] - right[..., 2]))
        - float(np.median(left[..., 0] - left[..., 2]))
    )
    assert split * 255 > 40, (
        f"neutral split is only {split * 255:.3f} of a code value; the mixed "
        "lighting defect has been adapted away"
    )


def test_the_surround_responds_to_the_illuminant_split_too() -> None:
    """A constant surround would betray the boundary without any patch help."""
    scene = Scene(layout=_grid(), illuminant="D65", second_illuminant="A", split_at=0.5)
    image = render(scene)
    indices = patch_map(scene)
    side = illuminant_map(scene)
    names = list(expected_patches(Scene(layout=_grid())))
    surround = names.index(scene.surround_patch)

    lit_left = image[(indices == surround) & ~side]
    lit_right = image[(indices == surround) & side]
    assert lit_left.size and lit_right.size
    assert not np.allclose(np.median(lit_left, axis=0), np.median(lit_right, axis=0))


def test_a_split_scene_refuses_to_report_one_expected_value_per_patch() -> None:
    scene = Scene(layout=_grid(), illuminant="D65", second_illuminant="A", split_at=0.5)
    with pytest.raises(CorpusError, match="no single expected value"):
        expected_patches(scene)


def test_a_scene_needs_both_halves_of_a_split_or_neither() -> None:
    with pytest.raises(CorpusError, match="both second_illuminant and split_at"):
        Scene(second_illuminant="A")
    with pytest.raises(CorpusError, match="both second_illuminant and split_at"):
        Scene(split_at=0.5)


def test_a_layout_larger_than_its_chart_is_refused() -> None:
    with pytest.raises(CorpusError, match="24 patches"):
        render(Scene(layout=_grid(rows=5, columns=6)))


# ---------------------------------------------------------------------------
# Defect injection.
# ---------------------------------------------------------------------------


def _reference() -> np.ndarray:
    return render(Scene(layout=_grid(), illuminant="D65"))


def _skin_block(image: np.ndarray) -> np.ndarray:
    """Return the pixels of the chart's light skin patch, which is index 1."""
    x0, y0, x1, y1 = _grid().rect_for_patch(1)
    return image[y0:y1, x0:x1].reshape(-1, 3)


def _oklab_hue_chroma(rgb: np.ndarray) -> tuple[float, float]:
    import colour

    from colorist.corpus import _display_to_xyz

    lab = colour.XYZ_to_Oklab(_display_to_xyz(np.median(rgb, axis=0)))
    return float(np.degrees(np.arctan2(lab[2], lab[1])) % 360.0), float(
        np.hypot(lab[1], lab[2])
    )


@pytest.mark.parametrize("family", ["tone", "chroma", "hue"])
@pytest.mark.parametrize("injector", ["primary", "secondary"])
def test_severity_zero_is_the_identity(family: str, injector: str) -> None:
    reference = _reference()
    assert np.array_equal(inject(reference, family, 0.0, injector=injector), reference)


@pytest.mark.parametrize("injector", ["primary", "secondary"])
def test_chroma_injection_reduces_skin_chroma_monotonically(injector: str) -> None:
    reference = _reference()
    chromas = [
        _oklab_hue_chroma(_skin_block(inject(reference, "chroma", s, injector=injector)))[1]
        for s in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    assert all(later < earlier for earlier, later in zip(chromas, chromas[1:])), chromas
    assert chromas[-1] < 0.65 * chromas[0]


@pytest.mark.parametrize("injector", ["primary", "secondary"])
def test_hue_injection_rotates_skin_hue_monotonically(injector: str) -> None:
    reference = _reference()
    hues = [
        _oklab_hue_chroma(_skin_block(inject(reference, "hue", s, injector=injector)))[0]
        for s in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    assert all(later > earlier for earlier, later in zip(hues, hues[1:])), hues
    assert hues[-1] - hues[0] > 5.0


@pytest.mark.parametrize("injector", ["primary", "secondary"])
def test_tone_injection_lifts_black_and_lowers_white(injector: str) -> None:
    reference = _reference()
    damaged = inject(reference, "tone", 1.0, injector=injector)
    assert damaged.min() > reference.min() + 0.01
    assert damaged.max() < reference.max() - 0.01


@pytest.mark.parametrize("family", ["tone", "chroma", "hue"])
def test_the_two_injectors_are_genuinely_independent(family: str) -> None:
    """Held-out implementations only hold anything out if they differ.

    Harness validation property 10 requires a second defect implementation
    precisely so that a metric fitted to the first cannot interpolate its way
    through. If the two agreed pixel for pixel there would be nothing held out.

    SCOPE. This asserts non-identity, which is necessary and not sufficient.
    Review measured that fitting only primary severity reproduced the secondary
    tone and chroma defects at a residual RMS of roughly 8 to 17 percent of the
    defect RMS, so these are related transform families rather than genuinely
    unrelated ones. See the note in corpus.py. Held-out content, not just a second
    injector, is what carries the weight.
    """
    reference = _reference()
    primary = inject(reference, family, 0.75, injector="primary")
    secondary = inject(reference, family, 0.75, injector="secondary")
    difference = float(np.abs(primary - secondary).max())
    assert difference > 1 / 255, (
        f"{family} injectors differ by only {difference:.5f}, which is under one "
        "code value, so the second implementation holds nothing out"
    )


def test_chroma_injection_leaves_hue_roughly_alone() -> None:
    """Cross-dimension specificity: a chroma defect must not read as a hue defect.

    Harness validation property 8 requires each family to move its own dimension.
    The primary injector scales chroma in Oklab and measurement is also in Oklab,
    so this is close to definitional for it; the value of the assertion is on the
    secondary injector, which works in CIELAB and has no such guarantee.
    """
    reference = _reference()
    base_hue, _ = _oklab_hue_chroma(_skin_block(reference))
    for injector in ("primary", "secondary"):
        hue, _ = _oklab_hue_chroma(
            _skin_block(inject(reference, "chroma", 1.0, injector=injector))
        )
        assert abs(hue - base_hue) < 2.0, f"{injector} chroma injection moved hue to {hue}"


def test_unknown_families_and_injectors_are_refused() -> None:
    reference = _reference()
    with pytest.raises(CorpusError, match="unknown defect family"):
        inject(reference, "sharpness", 0.5)
    with pytest.raises(CorpusError, match="unknown injector"):
        inject(reference, "hue", 0.5, injector="tertiary")
    with pytest.raises(CorpusError, match="severity"):
        inject(reference, "hue", 1.5)


# ---------------------------------------------------------------------------
# Encoding, and the pipeline noise floor it lets us measure.
# ---------------------------------------------------------------------------


def test_a_written_scene_round_trips_through_ffmpeg(tmp_path) -> None:
    """The lossless carrier must return what was rendered, to 16-bit precision.

    If this drifts, every analytic ground truth in the corpus is quietly wrong,
    so the tolerance is deliberately tight: one 16-bit code value plus a margin
    for the RGB to GBR plane shuffle, which is far below one 8-bit code value.
    """
    from colorist.render import ConvertParams, read_frame_rgb

    reference = _reference()
    path = write_scene(reference, tmp_path / "reference.mkv")
    decoded = read_frame_rgb(
        path,
        0,
        ConvertParams(range="full", matrix="bt709", transfer="bt709", primaries="bt709"),
    )

    assert decoded.shape == reference.shape
    error = float(np.abs(decoded - reference).max())
    # The measured floor on this machine is 0.0187 of an 8-bit code value. The
    # bound is set at a twentieth of a code value, which is comfortably above the
    # floor and far below anything a grade could hide behind, and which would
    # still catch the 0.957 code value gain that writing a peak of 65535 causes.
    assert error < 0.05 / 255, f"lossless round trip drifted by {error * 255:.5f} 8-bit codes"


def test_the_written_scene_carries_the_tags_its_role_needs(tmp_path) -> None:
    import json
    import subprocess

    from colorist.tools import resolve_tool

    path = write_scene(_reference(), tmp_path / "tagged.mkv")
    probe = subprocess.run(
        [
            resolve_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "stream=color_range,color_space,color_primaries,color_transfer,pix_fmt",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["color_range"] == "pc"
    assert stream["color_space"] == "bt709"
    # FFV1 in Matroska stores range and matrix but NOT primaries or transfer,
    # measured on ffmpeg 8.1.2. FFV1 in MOV stores none of the four, so Matroska
    # is the better of the two, not a perfect carrier. This is recorded rather
    # than worked around because a corpus item is a SOURCE, and render.read_frame_rgb
    # decodes using the caller's declared ConvertParams range and matrix; it never
    # consults the transfer or primaries tags. The delivery-side tag gate is a
    # separate concern and applies to the graded output, which is tagged by the
    # delivery profile.
    assert "color_primaries" not in stream
    assert "color_transfer" not in stream


def test_write_scene_refuses_an_odd_dimension(tmp_path) -> None:
    with pytest.raises(CorpusError, match="must be even"):
        write_scene(np.zeros((7, 6, 3)), tmp_path / "odd.mkv")


def test_write_scene_refuses_a_non_image(tmp_path) -> None:
    with pytest.raises(CorpusError, match="height, width, 3"):
        write_scene(np.zeros((8, 8)), tmp_path / "flat.mkv")


# ---------------------------------------------------------------------------
# Held-out content.
#
# Harness validation property 10 requires content the metric has not seen, not
# just severities it has not seen. Varying the layout is one axis of that. Using
# a different chart entirely is the other, and it is stronger: different
# reflectances, a different patch count, and different names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chart", "rows", "columns"),
    [("ISO 17321-1", 4, 6), ("BabelColor Average", 4, 6), ("PMC", 5, 6)],
)
def test_the_generator_is_not_hardcoded_to_one_chart(chart, rows, columns) -> None:
    layout = _grid(rows=rows, columns=columns)
    scene = Scene(chart=chart, layout=layout, illuminant="D65")
    image = render(scene)
    truth = expected_patches(scene)
    names = list(truth)

    assert len(names) >= layout.cells
    for cell, patch_index in enumerate(layout.placement):
        x0, y0, x1, y1 = layout.rect(cell)
        assert np.array_equal(image[y0:y1, x0:x1][0, 0], truth[names[patch_index]])


def test_two_charts_that_share_patch_names_still_differ_in_pixels() -> None:
    """ISO 17321-1 and BabelColor Average name their patches identically.

    They are different measurements of the ColorChecker, so a corpus item built
    from one is genuinely held out from a metric tuned on the other. If they were
    pixel-identical the second chart would hold nothing out, which is the same
    trap the two defect injectors have to avoid.
    """
    layout = _grid()
    iso = render(Scene(chart="ISO 17321-1", layout=layout))
    babel = render(Scene(chart="BabelColor Average", layout=layout))
    assert iso.shape == babel.shape
    difference = float(np.abs(iso - babel).max())
    assert difference > 1 / 255, (
        f"the two ColorChecker datasets differ by only {difference:.5f}, under one "
        "code value, so swapping them holds nothing out"
    )


def test_an_unknown_chart_is_refused_by_name() -> None:
    with pytest.raises(CorpusError, match="unknown chart"):
        render(Scene(chart="not a chart", layout=_grid()))


# ---------------------------------------------------------------------------
# A non-circular oracle.
#
# test_rendered_patches_equal_the_analytic_ground_truth compares render() against
# expected_patches(), and BOTH call patch_display_rgb(). Review pointed out that
# this validates gathering, layout, and placement, and nothing else: a wrong
# observer, a wrong normalisation, a wrong matrix, or a global gain inside
# patch_display_rgb would change "truth" and "rendered" identically and the test
# would still pass. The docstring there claiming two independent derivations was
# wrong, and is corrected.
#
# These two tests supply the missing independence, using data this module does
# not compute: BabelColor's own published chromaticities, and the BT.709 matrix
# as published rather than as colour-science derives it.
# ---------------------------------------------------------------------------


def test_spectral_rendering_matches_independently_published_chromaticities() -> None:
    """Validate the spectral core against measurements this module never computes.

    colour-science ships BabelColor's published xyY values for the ColorChecker
    separately from its spectra. Integrating the spectra here and landing on those
    published chromaticities exercises the observer, the spectral integration, and
    the perfect-diffuser normalisation against an outside number.

    Measured agreement on this machine: median chromaticity distance 0.00010,
    worst 0.00082 over 24 patches. The bound is set just above the worst.
    """
    import colour

    from colorist.corpus import OBSERVER, _aligned, _perfect_diffuser_xyz

    published = colour.CCS_COLOURCHECKERS["BabelColor Average"]
    spectrum = _aligned("illuminant", None, "D50")
    cmfs = colour.MSDS_CMFS[OBSERVER]
    white_y = _perfect_diffuser_xyz("D50")[1]

    worst = 0.0
    for name, reference_xyY in published.data.items():
        reflectance = _aligned("reflectance", "BabelColor Average", name)
        mine = colour.XYZ_to_xyY(colour.sd_to_XYZ(reflectance, cmfs, spectrum) / white_y)
        worst = max(worst, float(np.hypot(*(mine[:2] - np.asarray(reference_xyY)[:2]))))
        assert abs(mine[2] - reference_xyY[2]) < 0.001, f"{name} luminance factor"
    assert worst < 0.001, f"worst chromaticity distance {worst:.5f}"


def test_the_xyz_to_rec709_step_matches_the_published_matrix() -> None:
    """Check the matrix conversion against published coefficients, not the library.

    These are the standard BT.709 D65 XYZ to linear RGB coefficients as published.
    Hardcoding them makes this a check on colour-science's colourspace definition
    and on the way this module calls it, rather than a restatement of either.
    """
    import colour

    from colorist.corpus import _display_to_linear_rgb

    published_xyz_to_rgb = np.array(
        [
            [3.2404542, -1.5371385, -0.4985314],
            [-0.9692660, 1.8760108, 0.0415560],
            [0.0556434, -0.2040259, 1.0572252],
        ]
    )
    rng = np.random.default_rng(20260723)
    xyz = rng.uniform(0.02, 0.9, size=(64, 3))

    library = colour.XYZ_to_RGB(
        xyz,
        colour.RGB_COLOURSPACES["ITU-R BT.709"],
        apply_cctf_encoding=False,
        chromatic_adaptation_transform=None,
    )
    hand = xyz @ published_xyz_to_rgb.T
    # Exact agreement is not expected and asserting it would be wrong. The
    # published coefficients are rounded to seven decimal places, while
    # colour-science derives the matrix from the BT.709 primaries and white point
    # at full float precision. The residual is that rounding: measured worst
    # absolute difference 3.6e-4 on a component of magnitude 2.29, so about 1.6e-4
    # relative. A tolerance tight enough to fail here would be testing the
    # rounding, not the matrix.
    assert np.abs(library - hand).max() < 1e-3

    # And the display encode this module uses really is the gamma 2.4 inverse,
    # which is the project convention and NOT the BT.709 OETF. See the note in
    # docs/evaluation-harness.md about that ambiguity.
    display = np.array([0.1, 0.5, 0.9])
    assert np.allclose(_display_to_linear_rgb(display), display**2.4)


# ---------------------------------------------------------------------------
# Gamut clipping, which the corpus reports rather than hides.
# ---------------------------------------------------------------------------


def test_the_reference_scene_itself_clips_and_says_so() -> None:
    """Clipping is not a property of damaged items only.

    Under D65 with a D65 balance, the ISO 17321-1 cyan patch sits at linear
    R = -0.0334. It is outside the Rec.709 gamut as a matter of colorimetry, with
    no defect involved. Any design that treated clipping as evidence of damage
    would be wrong on the reference itself, so the corpus reports clipping as a
    fact about a scene instead.
    """
    reference = Scene(layout=_grid(), illuminant="D65")
    report = clipping_report(reference)

    clipped = sorted(name for name, entry in report.items() if entry["clipped"])
    assert clipped == ["cyan"]
    assert report["cyan"]["clipped_low"] is True
    assert report["cyan"]["clipped_high"] is False
    assert report["cyan"]["linear_min"] == pytest.approx(-0.0334, abs=0.002)


def test_no_exposure_can_rescue_a_negative_excursion() -> None:
    """Headroom fixes the top of the range and can never fix the bottom.

    This is why "render with enough headroom to avoid clipping" is not available
    as a general answer. An earlier version of this test asserted that dimming
    made the negative worse, which is false: a gain below 1 shrinks it toward
    zero. The true and stronger invariant is that exposure is a multiplication, so
    it cannot change a sign. A negative linear value stays negative at every
    positive gain, and cyan is negative in every scene measured.
    """
    for exposure in (0.25, 0.5, 1.0, 2.0, 8.0):
        scene = Scene(layout=_grid(), illuminant="D65", exposure=exposure)
        entry = clipping_report(scene)["cyan"]
        assert entry["clipped_low"] is True, f"cyan escaped clipping at gain {exposure}"
        assert entry["linear_min"] < 0.0


def test_exposure_does_rescue_a_high_excursion() -> None:
    """The half that headroom can fix, so the parameter earns its place."""
    hot = Scene(layout=_grid(), illuminant="A")
    assert any(entry["clipped_high"] for entry in clipping_report(hot).values())

    cooled = Scene(layout=_grid(), illuminant="A", exposure=0.6)
    assert not any(entry["clipped_high"] for entry in clipping_report(cooled).values())


def test_recoverable_patches_excludes_what_clipping_destroyed() -> None:
    """Validation property 2 may only be applied where information survived.

    Under illuminant A on a daylight balance, six of 24 patches clip on top of
    the reference's own cyan, leaving 17 patches on which an analytic inverse
    could be held to exact recovery.
    """
    reference = Scene(layout=_grid(), illuminant="D65")
    defect = Scene(layout=_grid(), illuminant="A")

    recoverable = recoverable_patches(reference, defect)
    assert "cyan" not in recoverable, "clipped in the reference, so never recoverable"
    assert "white 9.5 (.05 D)" not in recoverable, "clipped by the defect"
    assert "dark skin" in recoverable
    assert len(recoverable) == 17


def test_a_scene_with_no_defect_recovers_everything_except_its_own_clipping() -> None:
    reference = Scene(layout=_grid(), illuminant="D65")
    assert len(recoverable_patches(reference, reference)) == 23


def test_the_project_encode_round_trips_through_a_bt1886_display() -> None:
    """The substantive claim behind the bt709 tag, pinned.

    These pixels are display referred: encoded with the inverse of the BT.1886
    EOTF, so a code value is what a gamma 2.4 display shows. That round trip is
    exact, and it is the reason the encode is right even though the files are
    tagged bt709 and the BT.709 OETF is a different function.

    The BT.709 OETF is scene referred and is NOT the inverse of BT.1886. Pairing
    it with a BT.1886 display is the deliberate end-to-end system gamma for
    camera light in a dim surround, which is not what a deliverable wants.
    Reproduced by tools/measure_transfer_convention.py.
    """
    from colorist.corrections import bt1886_decode, bt1886_encode

    linear = np.array([0.02, 0.18, 0.5, 0.9])
    assert np.allclose(bt1886_decode(bt1886_encode(linear)), linear)

    # The two transfers genuinely differ, so the ambiguity was worth resolving
    # rather than waving away.
    oetf_at_mid = 1.099 * 0.18**0.45 - 0.099
    assert oetf_at_mid == pytest.approx(0.40901, abs=1e-5)
    assert float(bt1886_encode(np.array(0.18))) == pytest.approx(0.48944, abs=1e-5)
    assert bt1886_decode(np.array(oetf_at_mid)) == pytest.approx(0.11699, abs=1e-5)


# ---------------------------------------------------------------------------
# Analytic inverses and recovery, for validation property 2.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", ["tone", "chroma", "hue"])
@pytest.mark.parametrize("injector", ["primary", "secondary"])
def test_the_analytic_inverse_undoes_the_injection_on_floats(family, injector) -> None:
    """Exact by construction, and weak for exactly that reason.

    inject then invert on a pre-encode float is the identity, so this only checks
    the arithmetic. It cannot tell whether a metric recovers, because the restored
    image simply IS the reference. The meaningful version runs through the
    pipeline, below.
    """
    reference = _reference()
    for severity in (0.25, 0.6, 1.0):
        restored = invert(
            inject(reference, family, severity, injector=injector),
            family,
            severity,
            injector=injector,
        )
        assert np.abs(restored - reference).max() * 255 < 0.001


@pytest.mark.parametrize("family", ["tone", "chroma", "hue"])
@pytest.mark.parametrize("injector", ["primary", "secondary"])
def test_recovery_through_the_real_pipeline_reaches_the_noise_floor(
    tmp_path, family, injector
) -> None:
    """Validation property 2, run the way it actually means something.

    Render, inject, encode to a real file, decode, apply the analytic inverse,
    and compare to the reference. This is not the identity: quantisation and the
    RGB to YCbCr round trip sit in the middle. The question is whether recovery
    lands at the pipeline's own noise floor rather than above it.

    Measured on this machine, over the recoverable patches: worst 0.069 of an
    8-bit code value, across all six family and injector combinations, against a
    defect-free pipeline floor of 0.019. The bound is set at 0.15, which is
    comfortably above the worst and far below the 1.206 that the excluded patch
    produces, so a regression in the exclusion mechanism still fails this.
    """
    from colorist.render import ConvertParams, read_frame_rgb

    params = ConvertParams(range="full", matrix="bt709", transfer="bt709", primaries="bt709")
    layout = _grid()
    scene = Scene(layout=layout)
    reference = render(scene)
    names = list(expected_patches(scene))
    keep = set(recoverable_patches(scene, scene))

    damaged = write_scene(
        inject(reference, family, 1.0, injector=injector), tmp_path / "damaged.mkv"
    )
    restored = invert(read_frame_rgb(damaged, 0, params), family, 1.0, injector=injector)
    error = np.abs(restored - reference).max(axis=-1)

    worst = max(
        float(error[slice(*(lambda r: (r[1], r[3]))(layout.rect(cell))),
                    slice(*(lambda r: (r[0], r[2]))(layout.rect(cell)))].max())
        for cell, patch_index in enumerate(layout.placement)
        if names[patch_index] in keep
    )
    assert worst * 255 < 0.15, f"recovery worst {worst * 255:.5f} 8-bit codes"


def test_the_clipped_patch_exclusion_is_load_bearing(tmp_path) -> None:
    """Without excluding cyan, recovery fails by a factor of 65.

    This pins the mechanism rather than the number. The reference scene clips the
    cyan patch, so its information is gone before any defect is applied and no
    inverse restores it. Measured for hue with the secondary injector: 1.206 of
    an 8-bit code value over all patches, 0.018 once cyan is excluded.

    If a future change stopped excluding clipped patches, this test fails and
    says why, instead of the recovery bound quietly being widened to accommodate
    an unrecoverable pixel.
    """
    from colorist.render import ConvertParams, read_frame_rgb

    params = ConvertParams(range="full", matrix="bt709", transfer="bt709", primaries="bt709")
    layout = _grid()
    scene = Scene(layout=layout)
    reference = render(scene)

    assert "cyan" not in recoverable_patches(scene, scene)

    damaged = write_scene(
        inject(reference, "hue", 1.0, injector="secondary"), tmp_path / "hue.mkv"
    )
    restored = invert(read_frame_rgb(damaged, 0, params), "hue", 1.0, injector="secondary")
    error = np.abs(restored - reference).max(axis=-1)

    names = list(expected_patches(scene))
    cyan_cell = layout.placement.index(names.index("cyan"))
    x0, y0, x1, y1 = layout.rect(cyan_cell)
    assert float(error[y0:y1, x0:x1].max()) * 255 > 0.5, (
        "cyan should be unrecoverable; if it is not, the reference stopped clipping"
    )


# ---------------------------------------------------------------------------
# Pinned regions of interest, for validation property 7.
# ---------------------------------------------------------------------------


def test_a_per_image_mask_breaks_the_statistic_it_is_supposed_to_measure() -> None:
    """The defect that makes an unpinned invariance property untestable.

    measure._skin_mask gates on absolute HSV value between 0.25 and 0.95, so
    exposure moves regions ACROSS the threshold and the statistic becomes a
    median over a different population. Measured: the skin mask holds 512 px at
    exposures 1.0 through 0.25 and only 256 px at 0.125, where the dark skin
    patch drops out, moving the saturation median by 0.044.
    """
    layout = _grid()
    sizes, values = [], []
    for exposure in (1.0, 0.25, 0.125):
        image = render(Scene(layout=layout, illuminant="D65", exposure=exposure))
        mask = reference_roi(image, "skin")
        sizes.append(int(mask.sum()))
        values.append(masked_statistic(image, mask, "hsv_saturation_median"))

    assert sizes == [512, 512, 256], f"mask sizes {sizes}"
    assert values[0] == pytest.approx(values[1], abs=1e-9)
    assert abs(values[2] - values[0]) > 0.04, "the per-image mask should break here"


def test_pinning_the_mask_makes_the_skin_statistic_exactly_invariant() -> None:
    """HSV saturation is a ratio, so a uniform gain cannot move it.

    That law only shows up once the mask stops moving. With the region derived
    once from the reference, the statistic is identical at every exposure,
    including the one where the per-image mask above lost a patch.
    """
    layout = _grid()
    reference = render(Scene(layout=layout, illuminant="D65"))
    pinned = reference_roi(reference, "skin")
    baseline = masked_statistic(reference, pinned, "hsv_saturation_median")

    for exposure in (1.0, 0.5, 0.25, 0.125):
        image = render(Scene(layout=layout, illuminant="D65", exposure=exposure))
        assert masked_statistic(image, pinned, "hsv_saturation_median") == pytest.approx(
            baseline, abs=1e-9
        )


def test_pinning_makes_the_neutral_statistic_follow_an_exact_stated_law() -> None:
    """Not invariance. A DIFFERENCE in display code scales, and by how much is exact.

    bt1886_encode is a per-channel power law, so scaling scene linear by k scales
    every display code by k**(1/2.4), and a difference of two codes scales with
    them. Measured under illuminant A with the mask pinned, the relative error
    against that prediction is at the 1e-16 level.

    This is why validation property 7 must be stated as "the statistic follows
    its declared law" rather than "the score must not move". Two statistics over
    the same pinned region obey different laws: HSV saturation is a ratio and is
    invariant, R minus B is a difference and scales.

    Without pinning the same statistic is not merely off this law, it is
    NON-MONOTONIC, reading 14.03 code values at full exposure, 11.19 at half and
    17.67 at a quarter, and undefined at an eighth because the mask empties.
    """
    layout = _grid()
    reference = render(Scene(layout=layout, illuminant="A"))
    pinned = reference_roi(reference, "neutral")
    baseline = masked_statistic(reference, pinned, "r_minus_b_median")

    for exposure in (1.0, 0.5, 0.25, 0.125):
        image = render(Scene(layout=layout, illuminant="A", exposure=exposure))
        measured = masked_statistic(image, pinned, "r_minus_b_median")
        assert measured == pytest.approx(baseline * exposure ** (1 / 2.4), rel=1e-9)


def test_the_unpinned_neutral_statistic_is_non_monotonic_and_then_undefined() -> None:
    """Pins the failure itself, so nobody re-derives masks per image by accident."""
    layout = _grid()
    readings = []
    for exposure in (1.0, 0.5, 0.25, 0.125):
        image = render(Scene(layout=layout, illuminant="A", exposure=exposure))
        readings.append(
            masked_statistic(image, reference_roi(image, "neutral"), "r_minus_b_median")
        )

    assert readings[2] > readings[1], "the quarter-exposure reading should RISE"
    assert np.isnan(readings[3]), "the mask should empty at an eighth exposure"


def test_an_empty_region_reports_nan_rather_than_a_number() -> None:
    """Absent evidence is not a measurement, and must not be returned as one."""
    layout = _grid()
    image = render(Scene(layout=layout))
    empty = np.zeros(image.shape[:2], dtype=bool)
    assert np.isnan(masked_statistic(image, empty, "luma_median"))


def test_unknown_roi_kinds_and_statistics_are_refused() -> None:
    image = render(Scene(layout=_grid()))
    with pytest.raises(CorpusError, match="unknown ROI kind"):
        reference_roi(image, "foliage")
    with pytest.raises(CorpusError, match="unknown statistic"):
        masked_statistic(image, reference_roi(image, "skin"), "vibes")


# ---------------------------------------------------------------------------
# The delivery leg's acceptance bound, derived rather than measured.
# ---------------------------------------------------------------------------


def test_the_quantisation_ceiling_comes_from_the_profile_not_from_a_file() -> None:
    """A bound measured from the artefact cannot check the artefact.

    An earlier proposal returned the analytic truth plus the MEASURED codec error
    as the acceptance allowance, so a consumer asserts residual <= residual and
    the check cannot fail. Drop -color_range from the encode, every measured
    error grows by the 255/219 expansion, the allowance grows with it, and a
    delivery wrong by 6 percent of range is certified.

    This ceiling is derived from bit depth, range, and the BT.709 matrix. Nothing
    about it can move when the file moves, which is the whole point.
    """
    eight_bit = predicted_quantisation_ceiling("yuv420p", "limited")
    ten_bit = predicted_quantisation_ceiling("yuv422p10le", "limited")

    assert eight_bit == pytest.approx(1.63839, abs=1e-4)
    assert ten_bit == pytest.approx(0.40960, abs=1e-4)
    # Four times the precision must buy roughly four times the accuracy.
    assert eight_bit / ten_bit == pytest.approx(4.0, rel=0.01)
    # Full range wastes no codes, so it must beat limited at the same depth.
    assert predicted_quantisation_ceiling("yuv420p", "full") < eight_bit


def test_the_ceiling_uses_the_blue_coefficient_because_it_is_the_largest() -> None:
    """The specific error that made an earlier model contradict its own data.

    Using the red coefficient 1.5748 rather than blue 1.8556 yields an 8-bit
    limited ceiling of 1.4786 and a 10-bit one of 0.3696. The measured ProRes
    patch median error is 0.4136, which EXCEEDS that, and a ceiling its own
    observation exceeds is not a ceiling.
    """
    from colorist.corpus import BT709_CB_TO_B, BT709_CR_TO_R

    observed_prores = 0.4136  # measured patch median error, 8-bit code units
    ten_bit = predicted_quantisation_ceiling("yuv422p10le", "limited")
    red_only = (0.5 / 876 + BT709_CR_TO_R * 0.5 / 896) * 255

    assert BT709_CB_TO_B > BT709_CR_TO_R
    assert ten_bit > red_only, "blue must set the bound"

    # The blue model lands within one percent of the observation. The red model
    # is eleven percent under it. Both are BELOW, because this ceiling covers
    # quantisation only and 4:2:2 chroma subsampling adds a term it does not
    # model, so this is a scale check and not a hard bound. Asserting the
    # observation sits under it would be asserting something false.
    assert observed_prores / ten_bit == pytest.approx(1.0, abs=0.02)
    assert observed_prores / red_only > 1.10


def test_a_range_mistake_is_an_order_of_magnitude_away_from_the_ceiling() -> None:
    """The failure the ceiling exists to catch, sized.

    Writing full-range codes into a file tagged limited expands every value by
    255/219, about 16 code values at mid grey. Against an 8-bit ceiling of 1.64
    that is ten times over, so it cannot be mistaken for codec noise however the
    tolerance is phrased.
    """
    ceiling = predicted_quantisation_ceiling("yuv420p", "limited")
    range_mistake = 0.5 * 255 * (255 / 219 - 1)
    assert range_mistake / ceiling > 10


def test_the_delivery_interior_mask_declines_to_expect_boundary_pixels() -> None:
    """No per-pixel expectation is offered where subsampling mixes two patches."""
    layout = _grid()
    interior = delivery_interior_mask(layout, edge_margin=2)
    width, height = layout.resolution()

    assert interior.shape == (height, width)
    for cell in range(layout.cells):
        x0, y0, x1, y1 = layout.rect(cell)
        assert not interior[y0, x0], "the patch corner must be excluded"
        assert interior[(y0 + y1) // 2, (x0 + x1) // 2], "the patch centre must be kept"
    # The surround has no defensible per-patch expectation at all.
    assert not interior[0, 0]
    # Eroding more keeps strictly less.
    assert delivery_interior_mask(layout, edge_margin=4).sum() < interior.sum()


def test_a_patch_too_small_to_erode_is_dropped_rather_than_measured_badly() -> None:
    layout = _grid(patch_size=4)
    assert delivery_interior_mask(layout, edge_margin=2).sum() == 0
    with pytest.raises(CorpusError, match="must not be negative"):
        delivery_interior_mask(layout, edge_margin=-1)


# ---------------------------------------------------------------------------
# Combined defects and equal-distance pairs, for properties 10 and 13.
# ---------------------------------------------------------------------------


def test_equal_distance_pairs_really_are_equal_distance() -> None:
    """Property 13 needs the premise to hold before the test means anything."""
    reference = _reference()
    first, second, severities = equal_distance_pair(reference, "chroma", "hue", 3.0)

    assert frame_distance(reference, first) == pytest.approx(3.0, abs=0.01)
    assert frame_distance(reference, second) == pytest.approx(3.0, abs=0.01)
    # Different families need different severities to reach the same distance,
    # which is the whole reason the pair is interesting.
    assert abs(severities[0] - severities[1]) > 0.1


def test_an_equal_distance_pair_damages_different_dimensions() -> None:
    """Equal overall distance, different per-dimension signature.

    This is what kills a metric that measures how different two images are
    without knowing what changed. The chroma member must move skin chroma and
    leave hue alone; the hue member must do the reverse.
    """
    reference = _reference()
    chroma_damaged, hue_damaged, _ = equal_distance_pair(reference, "chroma", "hue", 3.0)

    base_hue, base_chroma = _oklab_hue_chroma(_skin_block(reference))
    chroma_hue, chroma_chroma = _oklab_hue_chroma(_skin_block(chroma_damaged))
    hue_hue, hue_chroma = _oklab_hue_chroma(_skin_block(hue_damaged))

    # The chroma member moved chroma much more than hue, and vice versa.
    assert abs(chroma_chroma - base_chroma) / base_chroma > 0.02
    assert abs(chroma_hue - base_hue) < 1.0
    assert abs(hue_hue - base_hue) > 2.0
    assert abs(hue_chroma - base_chroma) / base_chroma < 0.02


def test_an_unreachable_target_distance_is_refused_not_clamped() -> None:
    """Silently returning the closest severity would break the pair's premise."""
    reference = _reference()
    with pytest.raises(CorpusError, match="reaches only"):
        severity_for_distance(reference, "hue", 500.0)


def test_combined_defects_do_not_commute_and_the_order_is_part_of_the_item() -> None:
    """Property 10 wants combined defects, and combining is not associative here.

    A chroma scale after a tone compression is not the same image as the reverse,
    because the tone curve is non-linear. Measured 1.08 code values apart. So the
    sequence is part of an item's identity and must be recorded rather than
    normalised into some canonical order.
    """
    reference = _reference()
    forward = inject_many(reference, [("tone", 0.5, "primary"), ("chroma", 0.5, "primary")])
    backward = inject_many(reference, [("chroma", 0.5, "primary"), ("tone", 0.5, "primary")])

    assert frame_distance(forward, backward) > 0.5
    # And a combination is further from the reference than either part alone.
    single = inject(reference, "chroma", 0.5, injector="primary")
    assert frame_distance(reference, forward) > frame_distance(reference, single)


def test_frame_distance_refuses_mismatched_shapes() -> None:
    with pytest.raises(CorpusError, match="same shape"):
        frame_distance(np.zeros((4, 4, 3)), np.zeros((5, 4, 3)))


# ---------------------------------------------------------------------------
# The delivery leg, end to end.
# ---------------------------------------------------------------------------

H264 = Path("presets/delivery/h264-yt-sdr.yaml")
PRORES = Path("presets/delivery/prores-422hq.yaml")


def _delivery_layout() -> ChartLayout:
    # Larger patches than the other tests use: a delivery is 4:2:0 or 4:2:2 and
    # a 16 pixel patch leaves too little interior once its edges are eroded.
    return ChartLayout(rows=4, columns=6, patch_size=48, gutter=8, margin=16)


@pytest.mark.parametrize(
    ("profile", "suffix", "pix_fmt"),
    [(H264, "mp4", "yuv420p"), (PRORES, "mov", "yuv422p10le")],
)
def test_a_corpus_delivery_is_encoded_by_the_shipping_encoder(
    tmp_path, profile, suffix, pix_fmt
) -> None:
    """It must be the real delivery, not the carrier with a new name."""
    import json
    import subprocess

    from colorist.tools import resolve_tool

    layout = _delivery_layout()
    reference = render(Scene(layout=layout))
    carrier = write_scene(reference, tmp_path / "carrier.mkv")
    delivery = write_delivery(carrier, tmp_path / f"delivery.{suffix}", profile)

    stream = json.loads(
        subprocess.run(
            [
                resolve_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=pix_fmt,color_range,color_space",
                "-of", "json", str(delivery),
            ],
            capture_output=True, text=True, check=True,
        ).stdout
    )["streams"][0]

    assert stream["pix_fmt"] == pix_fmt
    assert stream["color_range"] == "tv"
    assert stream["color_space"] == "bt709"


@pytest.mark.parametrize(("profile", "suffix"), [(H264, "mp4"), (PRORES, "mov")])
def test_the_delivery_floor_is_the_right_size_against_a_derived_ceiling(
    tmp_path, profile, suffix
) -> None:
    """Checked against a bound that did not come from the file.

    Measured: h264 1.7567 against a ceiling of 1.6384, ratio 1.07; prores 0.8057
    against 0.4096, ratio 1.97. The ceiling covers quantisation only and not each
    codec's own lossy DCT, so the band is wide and honest rather than a fitted
    multiplier. It still does its job: a range mistake costs about 16 code
    values, ten to forty times the ceiling, and cannot hide inside this band.
    """
    layout = _delivery_layout()
    reference = render(Scene(layout=layout))
    carrier = write_scene(reference, tmp_path / "carrier.mkv")
    delivery = write_delivery(carrier, tmp_path / f"delivery.{suffix}", profile)

    floor = measure_delivery_floor(reference, delivery, layout, profile)

    assert 0.5 < floor.patch_median_max / floor.ceiling < 2.5
    # The whole frame is far worse than the patch medians, which is why no
    # per-pixel expectation is offered for a subsampled delivery.
    assert floor.whole_frame_max > 20 * floor.patch_median_max
    assert 0.4 < floor.excluded_fraction < 0.6


def test_the_floor_is_measured_against_the_analytic_truth_not_against_a_file(
    tmp_path,
) -> None:
    """The check that catches validating a file against a file.

    The carrier round trip is about 0.019 of an 8-bit code value, one part in
    sixty of the delivery floor, so swapping the analytic array for a decode of
    the carrier would move every reported number below the third decimal and no
    other test would notice. Offsetting the analytic array by a known constant
    must move the floor by that constant; a function ignoring its analytic
    argument fails immediately.
    """
    layout = _delivery_layout()
    reference = render(Scene(layout=layout))
    carrier = write_scene(reference, tmp_path / "carrier.mkv")
    delivery = write_delivery(carrier, tmp_path / "delivery.mp4", H264)

    honest = measure_delivery_floor(reference, delivery, layout, H264)
    offset = 4.0 / 255.0
    shifted = measure_delivery_floor(
        np.clip(reference + offset, 0.0, 1.0), delivery, layout, H264
    )

    assert shifted.patch_median_max > honest.patch_median_max + 3.0


def test_the_delivery_floor_does_not_depend_on_edge_erosion(tmp_path) -> None:
    """A finding, pinned: this error is a per-patch bias, not a boundary effect.

    The design this replaced treated the patch median error as boundary
    contamination to be eroded away, and swept the margin to find where it
    plateaus. It does not plateau because it never varies: identical at margins
    of 0, 1, 2, 4, 8 and 12. Erosion is still right for declining to offer a
    per-pixel expectation, but it is not what sets this number.
    """
    layout = _delivery_layout()
    reference = render(Scene(layout=layout))
    carrier = write_scene(reference, tmp_path / "carrier.mkv")
    delivery = write_delivery(carrier, tmp_path / "delivery.mp4", H264)

    readings = {
        margin: measure_delivery_floor(
            reference, delivery, layout, H264, edge_margin=margin
        ).patch_median_max
        for margin in (0, 2, 4, 8)
    }
    assert max(readings.values()) - min(readings.values()) < 0.3, readings


# ---------------------------------------------------------------------------
# Null cases, for validation property 7.
# ---------------------------------------------------------------------------


def _p1_luma(image: np.ndarray, where: np.ndarray | None = None) -> float:
    luma = image @ np.array([0.2126, 0.7152, 0.0722])
    return float(np.percentile(luma if where is None else luma[where], 1) * 255)


def test_a_declared_aperture_restores_a_matted_frame_exactly() -> None:
    """Letterbox is only a null case if the bars are excluded, and exactly so.

    Bars are exactly zero, so on a matted frame they own the low percentiles.
    Measured on the reference chart with a twelve percent matte: p1 luma reads
    0.000 with the bars included and 61.976 within the declared aperture, which
    is the reference's own p1 luma to the digit. A black placement dimension
    computed over the bars measures the matte, not the grade.
    """
    reference = render(Scene(layout=_grid()))
    matted = add_letterbox(reference, 0.12)
    aperture = active_aperture(reference.shape[:2], 0.12)

    assert _p1_luma(matted) == pytest.approx(0.0, abs=1e-9)
    assert _p1_luma(matted, aperture) == pytest.approx(_p1_luma(reference), abs=1e-9)


def test_the_aperture_is_declared_and_not_detected() -> None:
    """A legitimately dark frame must not have its blacks mistaken for a matte."""
    reference = render(Scene(layout=_grid(), exposure=0.05))
    # Nothing is matted here, so the full frame is the aperture.
    full = active_aperture(reference.shape[:2], 0.0)
    assert full.all()
    with pytest.raises(CorpusError, match="bar_fraction"):
        active_aperture(reference.shape[:2], 0.6)


def test_grain_barely_moves_a_median_of_a_ratio() -> None:
    """Skin saturation is a rank statistic over a ratio, so noise mostly cancels."""
    reference = render(Scene(layout=_grid()))
    pinned = reference_roi(reference, "skin")
    baseline = masked_statistic(reference, pinned, "hsv_saturation_median")

    grained = add_grain(reference, GRAIN_AMPLITUDE_CODES, seed=7)
    assert abs(masked_statistic(grained, pinned, "hsv_saturation_median") - baseline) < 0.01


def test_grain_biases_the_neutral_statistic_up_by_a_derived_amount() -> None:
    """Not invariant, and the law is derived rather than fitted.

    median(|R - B|) is an ABSOLUTE difference, so zero-mean noise cannot cancel:
    it pushes the statistic UP. The difference of two independent channels has
    standard deviation a*sqrt(2), and the median of the absolute value of a
    zero-mean normal is 0.67449 of its standard deviation, so the statistic tends
    to 0.9539 * a as noise comes to dominate the residual signal.

    Measured, as the ratio of observed to predicted: 1.0569 at a = 0.5, 1.0162 at
    1.0, 1.0021 at 2.0, and within half a percent of unity through a = 16. That
    convergence is what distinguishes a confirmed mechanism from a fitted line.
    """
    from scipy.stats import norm

    reference = render(Scene(layout=_grid()))
    pinned = reference_roi(reference, "neutral")
    coefficient = float(np.sqrt(2) * norm.ppf(0.75))

    for amplitude in (2.0, 4.0, 8.0):
        measured = masked_statistic(
            add_grain(reference, amplitude, seed=7), pinned, "r_minus_b_median"
        ) * 255
        assert measured / (coefficient * amplitude) == pytest.approx(1.0, abs=0.02)


def test_grain_alone_consumes_half_the_shipped_neutral_gate() -> None:
    """The consequence of the above for real footage, not just the corpus.

    presets/gates/interview.yaml sets whites_rb_balance at 4.0 code values. Grain
    at the amplitude this corpus requires the statistics to survive contributes
    1.91 of that on its own, on a delivery with no white balance error at all.
    So a noisy but correctly balanced delivery spends nearly half the gate budget
    before any real defect is measured, and the gate cannot tell the two apart.
    """
    reference = render(Scene(layout=_grid()))
    pinned = reference_roi(reference, "neutral")
    spurious = masked_statistic(
        add_grain(reference, GRAIN_AMPLITUDE_CODES, seed=7), pinned, "r_minus_b_median"
    ) * 255

    assert masked_statistic(reference, pinned, "r_minus_b_median") * 255 < 0.1
    assert 1.5 < spurious < 2.5
    assert spurious > 0.4 * 4.0


def test_grain_is_seeded_so_a_null_case_is_reproducible() -> None:
    reference = render(Scene(layout=_grid()))
    assert np.array_equal(add_grain(reference, 2.0, seed=3), add_grain(reference, 2.0, seed=3))
    assert not np.array_equal(add_grain(reference, 2.0, seed=3), add_grain(reference, 2.0, seed=4))
    with pytest.raises(CorpusError, match="must not be negative"):
        add_grain(reference, -1.0)


# ---------------------------------------------------------------------------
# Non-chart content, for validation property 10.
# ---------------------------------------------------------------------------


def _soft_scene() -> SoftScene:
    return SoftScene(
        materials=(
            Material("light skin", "face", (96.0, 80.0), 34.0, ((3, 0.16, 0.4), (5, 0.07, 1.1))),
            Material("white 9.5 (.05 D)", "shirt", (170.0, 120.0), 40.0, ((2, 0.22, 2.0),)),
        )
    )


def test_soft_coverage_is_a_convex_mixture_everywhere() -> None:
    """The per-pixel colour is only defined if the weights sum to one."""
    weights = soft_coverage(_soft_scene())
    total = sum(weights.values())
    assert np.allclose(total, 1.0)
    assert all((weight >= 0).all() for weight in weights.values())


def test_a_core_pixel_is_exactly_the_pure_reflectance() -> None:
    """Core must mean fully covered, not nearly covered.

    At a 0.98 coverage threshold, core pixels deviated from the pure patch by up
    to 1.12 of an 8-bit code value, because two percent of a neighbouring
    material is easily a code value once the two differ in brightness. A region
    statistic over such a core is measuring a mixture and calling it a material.
    Fully covered interior pixels reach exactly 1.0, so requiring that costs a
    slightly smaller core and buys an exact claim.
    """
    scene = _soft_scene()
    image = render_soft(scene)
    trimap = soft_trimap(scene)

    for label, patch in (
        ("face", "light skin"),
        ("shirt", "white 9.5 (.05 D)"),
        ("backdrop", "neutral 5 (.70 D)"),
    ):
        core = trimap[label] == 2
        assert core.sum() > 1000, f"{label} core is too small to be useful"
        pure = patch_display_rgb("ISO 17321-1", patch, "D65")
        assert np.abs(image[core] - pure).max() == 0.0


def test_the_transition_band_is_small_and_explicitly_dont_care() -> None:
    """Soft boundaries make the LABEL ambiguous, never the colour.

    Those pixels are a don't-care band for a region metric, which is what
    validation property 9's precision and recall need in order to be scored
    fairly. Measured: 3.1 percent of the frame.
    """
    scene = _soft_scene()
    trimap = soft_trimap(scene)
    ambiguous = np.zeros(scene.resolution[::-1], dtype=bool)
    for band in trimap.values():
        ambiguous |= band == 1
    assert 0.005 < ambiguous.mean() < 0.10


def test_the_mixture_is_taken_in_linear_light_not_in_display_code() -> None:
    """The silent bug this avoids, sized.

    Spectral integration is linear in reflectance, so a coverage blend is the
    blend of linear RGB. bt1886_encode is a power law and does not commute with
    addition, so blending display code is a different and wrong picture. Measured
    for a fifty-fifty blend of light skin against black 2: 22.82 of an 8-bit code
    value. This test would pass by coincidence if the two agreed, so it asserts
    both that the render matches the linear blend AND that the two formulas
    genuinely differ.
    """
    from colorist.corrections import bt1886_encode

    first = patch_linear_rgb("ISO 17321-1", "light skin", "D65")
    second = patch_linear_rgb("ISO 17321-1", "black 2 (1.5 D)", "D65")
    linear_blend = bt1886_encode(np.clip(0.5 * first + 0.5 * second, 0.0, 1.0))
    display_blend = 0.5 * bt1886_encode(np.clip(first, 0.0, 1.0)) + 0.5 * bt1886_encode(
        np.clip(second, 0.0, 1.0)
    )
    assert np.abs(linear_blend - display_blend).max() * 255 > 20

    # And the renderer takes the linear one. Compared against the blend implied
    # by each pixel's OWN coverage, which is the actual claim, it is exact.
    # Comparing against an idealised fifty-fifty blend instead would be testing
    # how tight a coverage window was chosen: a plus or minus 0.01 window admits
    # a 1.6 percent coverage spread and so 1.07 code values of legitimate
    # variation.
    scene = SoftScene(
        materials=(Material("light skin", "blob", (128.0, 80.0), 40.0, (), softness=12.0),),
        backdrop="black 2 (1.5 D)",
    )
    weights = soft_coverage(scene)
    image = render_soft(scene)
    band = (weights["blob"] > 0.05) & (weights["blob"] < 0.95)
    assert band.sum() > 100, "no transition band to check"

    coverage = weights["blob"][band][:, None]
    per_pixel = bt1886_encode(np.clip(coverage * first + (1 - coverage) * second, 0.0, 1.0))
    assert np.abs(image[band] - per_pixel).max() == 0.0


def test_a_soft_scene_has_no_rectangles_to_find() -> None:
    """The property that makes this held-out CONTENT and not another chart."""
    scene = _soft_scene()
    trimap = soft_trimap(scene)
    core = trimap["face"] == 2
    rows = np.where(core.any(axis=1))[0]
    # An irregular outline means the covered width varies row to row. A rectangle
    # would give the same width on every row it occupies.
    widths = {int(core[row].sum()) for row in rows}
    assert len(widths) > 10, "the region looks suspiciously rectangular"


def test_soft_scenes_refuse_unknown_patches() -> None:
    with pytest.raises(CorpusError, match="is not in chart"):
        render_soft(SoftScene(materials=(Material("unicorn", "x", (10.0, 10.0), 5.0),)))
    with pytest.raises(CorpusError, match="backdrop"):
        render_soft(SoftScene(backdrop="unicorn"))
    with pytest.raises(CorpusError, match="duplicate material label"):
        soft_coverage(
            SoftScene(
                materials=(
                    Material("light skin", "same", (10.0, 10.0), 5.0),
                    Material("orange", "same", (20.0, 20.0), 5.0),
                )
            )
        )
