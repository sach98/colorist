# SPDX-License-Identifier: MIT
"""The evaluation harness: what it scores, and what it refuses to score.

The refusals are the substance here. A harness that scored every dimension today
would be inventing five of the six targets, which is the failure this whole
project exists to avoid, so most of these tests assert that a dimension declines
to produce a number and says why.
"""

from __future__ import annotations

import numpy as np
import pytest

from colorist.corpus import ChartLayout, Scene, reference_roi, render
from colorist.scorecard import (
    MIN_CHROMA_FOR_HUE,
    SKIN_HUE_CENTRE_DEGREES,
    ScorecardError,
    Target,
    deviation_score,
    score_delivery,
    skin_hue_and_chroma,
)


PASSING_TECHNICAL = {
    "tags_match": True,
    "range_legal": True,
    "introduced_clipping_percent": 0.0,
}


def _layout() -> ChartLayout:
    return ChartLayout(rows=4, columns=6, patch_size=48, gutter=8, margin=16)


def _reference() -> np.ndarray:
    return render(Scene(layout=_layout()))


def _two_neutral_regions(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    neutral = reference_roi(image, "neutral")
    middle = neutral.shape[0] // 2
    top, bottom = neutral.copy(), neutral.copy()
    top[middle:] = False
    bottom[:middle] = False
    return top, bottom


def _card(image: np.ndarray | None = None, **overrides):
    values = _reference() if image is None else image
    settings = {
        "skin_mask": reference_roi(values, "skin"),
        "neutral_regions": _two_neutral_regions(values),
        "technical": PASSING_TECHNICAL,
    }
    settings.update(overrides)
    return score_delivery(values, **settings)


# ---------------------------------------------------------------------------
# The scoring function.
# ---------------------------------------------------------------------------


def test_the_scoring_function_has_the_shape_the_specification_states() -> None:
    """10 at target, 9 at the band edge, 0 at the gross bound, linear between."""
    target = Target(basis="declared_intent", centre=50.0, band=2.0, gross=10.0)

    assert deviation_score(50.0, target) == pytest.approx(10.0)
    assert deviation_score(52.0, target) == pytest.approx(9.0)
    assert deviation_score(48.0, target) == pytest.approx(9.0)
    assert deviation_score(60.0, target) == pytest.approx(0.0)
    assert deviation_score(100.0, target) == pytest.approx(0.0)
    # Monotone, which is the property every validation sweep depends on.
    scores = [deviation_score(50.0 + step, target) for step in (0, 1, 2, 4, 6, 8, 10)]
    assert all(later <= earlier for earlier, later in zip(scores, scores[1:]))


def test_an_interval_target_scores_ten_anywhere_inside_it() -> None:
    target = Target(basis="declared_intent", interval=(40.0, 60.0), band=2.0, gross=10.0)
    assert deviation_score(40.0, target) == pytest.approx(10.0)
    assert deviation_score(55.0, target) == pytest.approx(10.0)
    assert deviation_score(62.0, target) == pytest.approx(9.0)


def test_a_target_without_a_band_cannot_score() -> None:
    """A centre is not a tolerance, and pretending otherwise invents the number."""
    centre_only = Target(basis="measured_reflectance", centre=SKIN_HUE_CENTRE_DEGREES)
    assert not centre_only.scoreable
    with pytest.raises(ScorecardError, match="no band"):
        deviation_score(42.0, centre_only)


def test_a_gross_bound_inside_the_band_is_refused() -> None:
    with pytest.raises(ScorecardError, match="gross bound must exceed"):
        deviation_score(1.0, Target(basis="declared_intent", centre=0.0, band=5.0, gross=2.0))


# ---------------------------------------------------------------------------
# What the harness measures, and what it declines to score.
# ---------------------------------------------------------------------------


def test_the_harness_measures_every_dimension_it_cannot_score() -> None:
    """TARGET_UNAVAILABLE reports a value. Absent evidence is a different state."""
    card = _card()
    for name in ("skin_luma", "skin_hue", "skin_chroma", "neutral_consistency", "tonal_black"):
        dimension = card.by_name(name)
        assert dimension.state == "TARGET_UNAVAILABLE", (name, dimension.state)
        assert dimension.value is not None, f"{name} reported no value"
        assert dimension.score is None
        assert dimension.reason


def test_the_measured_skin_values_agree_with_the_independent_measurement() -> None:
    """A cross-check between the harness and this repository's own colour science.

    references/color-theory/skin-targets-measured.md reports the ColorChecker
    skin patches at an Oklab hue of 44.433 degrees and a chroma of 0.05996 under
    D65, derived from spectra with no rendering involved. The harness measures
    the rendered chart through a mask and must land on the same numbers, or one
    of the two paths is wrong.
    """
    card = _card()
    assert card.by_name("skin_hue").value == pytest.approx(44.433, abs=0.2)
    assert card.by_name("skin_chroma").value == pytest.approx(0.05996, abs=0.002)


def test_the_composite_refuses_and_names_what_is_missing() -> None:
    """The refusal is the deliverable: it says which targets are ungrounded."""
    card = _card()
    assert card.composite is None
    assert card.refusal is not None
    for name in ("skin_luma", "skin_hue", "skin_chroma"):
        assert name in card.refusal


def test_declaring_the_missing_targets_produces_a_composite() -> None:
    """The refusal is not a dead end; supplying a basis unlocks the score.

    Only the dimensions whose basis is declared_intent can be unlocked this way.
    Skin hue and skin chroma cannot, because their basis is measurement and
    published preference respectively, and an operator declaring those would be
    inventing exactly what the project refuses to invent.
    """
    card = _card(
        declarations={
            "skin_luma_target_ire": 50.75,
            "neutral_regions_are_one_object": True,
            "black_target_ire": 24.3,
        }
    )
    assert card.by_name("skin_luma").state == "MEASURED"
    assert card.by_name("neutral_consistency").state == "MEASURED"
    assert card.by_name("tonal_black").state == "MEASURED"
    # Still refused, because skin hue and chroma remain ungrounded.
    assert card.composite is None
    assert "skin_hue" in card.refusal and "skin_chroma" in card.refusal


def test_declaring_no_skin_opens_the_smaller_composite() -> None:
    """A fixed denominator with its own coverage signature, never a shrunk one."""
    card = _card(
        declarations={
            "skin_applicable": False,
            "neutral_regions_are_one_object": True,
            "black_target_ire": 24.3,
        }
    )
    assert card.composite_name == "no_skin"
    assert card.composite is not None
    assert card.coverage_signature == (
        "technical_conform", "neutral_consistency", "tonal_black",
    )
    for name in ("skin_luma", "skin_hue", "skin_chroma"):
        assert card.by_name(name).state == "NOT_APPLICABLE"


def test_undetected_skin_is_absent_evidence_not_not_applicable() -> None:
    """The two are different facts and only one of them is good news."""
    reference = _reference()
    card = _card(reference, skin_mask=np.zeros(reference.shape[:2], dtype=bool))
    assert card.by_name("skin_hue").state == "EVIDENCE_ABSENT"
    assert card.composite is None


# ---------------------------------------------------------------------------
# Technical conform as a precondition.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("broken", ["tags_match", "range_legal"])
def test_a_non_conformant_delivery_gets_no_composite(broken: str) -> None:
    technical = dict(PASSING_TECHNICAL, **{broken: False})
    card = _card(technical=technical)
    assert card.by_name("technical_conform").score == 0.0
    assert card.composite is None
    assert "not a deliverable" in card.refusal


def test_unmeasurable_introduced_clipping_refuses_rather_than_passing() -> None:
    """Absent evidence for a hard check is not a pass. Section 5.1."""
    technical = dict(PASSING_TECHNICAL)
    technical["introduced_clipping_percent"] = None
    card = _card(technical=technical)
    assert card.by_name("technical_conform").state == "EVIDENCE_ABSENT"
    assert card.composite is None
    assert "technical conform" in card.refusal


def test_technical_conform_has_no_partial_credit() -> None:
    """A delivery with wrong tags is not seventy percent conformant."""
    passing = _card().by_name("technical_conform")
    failing = _card(technical=dict(PASSING_TECHNICAL, tags_match=False)).by_name(
        "technical_conform"
    )
    assert {passing.score, failing.score} == {10.0, 0.0}


# ---------------------------------------------------------------------------
# Statistic definitions.
# ---------------------------------------------------------------------------


def test_hue_is_refused_below_the_chroma_floor() -> None:
    """A hue angle on a near-neutral region is not a meaningful quantity."""
    reference = _reference()
    grey = np.full_like(reference, 0.5)
    mask = np.zeros(grey.shape[:2], dtype=bool)
    mask[10:40, 10:40] = True

    _, chroma = skin_hue_and_chroma(grey, mask)
    assert chroma < MIN_CHROMA_FOR_HUE

    card = _card(grey, skin_mask=mask)
    assert card.by_name("skin_hue").state == "MEASUREMENT_INVALID"
    assert "below the floor" in card.by_name("skin_hue").reason


def test_neutral_disagreement_needs_two_regions() -> None:
    reference = _reference()
    single = (reference_roi(reference, "neutral"),)
    card = _card(reference, neutral_regions=single)
    assert card.by_name("neutral_consistency").state == "EVIDENCE_ABSENT"


def test_the_active_aperture_changes_the_black_measurement() -> None:
    """Letterbox bars own the low percentiles unless the aperture excludes them."""
    from colorist.corpus import active_aperture, add_letterbox

    reference = _reference()
    matted = add_letterbox(reference, 0.12)

    with_bars = _card(matted).by_name("tonal_black").value
    within = _card(
        matted,
        declarations={"active_aperture": active_aperture(matted.shape[:2], 0.12)},
    ).by_name("tonal_black").value

    assert with_bars == pytest.approx(0.0, abs=1e-9)
    assert within == pytest.approx(_card().by_name("tonal_black").value, abs=1e-9)
