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

import numpy as np
import pytest

from colorist.corpus import (
    ChartLayout,
    CorpusError,
    Scene,
    clipping_report,
    expected_patches,
    inject,
    illuminant_map,
    invert,
    masked_statistic,
    patch_display_rgb,
    patch_map,
    recoverable_patches,
    reference_roi,
    split_through_cell,
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
