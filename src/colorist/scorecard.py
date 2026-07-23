# SPDX-License-Identifier: MIT
"""The evaluation harness: score a delivery, and refuse where it cannot.

This implements `docs/evaluation-harness.md` v3. Read that first; this module is
the contract in code, not a restatement of it.

WHAT TO EXPECT FROM RUNNING THIS TODAY

Almost nothing scores. That is the designed and honest outcome, not a shortfall.

A dimension gets a score only when its target has a basis that can be named under
section 3.1. Most do not yet:

- **Technical conform** does. Colour tags and legal sample range are delivery
  standards, and its scoring rule is a table rather than a tolerance.
- **Skin hue** has a measured target CENTRE, 42.157 degrees in Oklab, from this
  repository's own measurement of published reflectances. It has no BAND. The
  measured illuminant-driven spread of -5.89 to +3.40 degrees is a spread of
  CORRECT values, not a tolerance for incorrect ones, and using it as a
  tolerance would be a category error that quietly invents the number the whole
  exercise is trying to avoid inventing.
- **Skin chroma** has neither. The tolerance source, Zeng and Luo 2011, is behind
  a paywall; its abstract confirms it contains hue and chroma tolerances, which
  is why it is named rather than replaced.
- **Skin luma** has no absolute target at all. Surface reflectance does not
  determine rendered display luma: the same person is legitimately at 35 IRE in a
  low-key scene and 65 IRE in a high-key one.
- **Neutral consistency** needs the operator to declare that two regions are one
  object that should match, because two whites under different motivated
  illuminants need not.
- **Tonal shaping** needs a declared look intent for black placement and an
  authenticated source for the two relative sub-measures.

So a run reports six measured values and, typically, one score. The composite
refuses. That refusal is the deliverable: it says exactly which targets this
project has grounded and which it has not, in a form that changes automatically
as evidence arrives, rather than in prose that has to be remembered and updated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

import numpy as np


#: Where a target's authority comes from. Section 3.1.
TargetBasis = Literal[
    "delivery_standard",
    "source_reference",
    "measured_reflectance",
    "perceptual_population",
    "declared_intent",
]

#: Section 3.3. TARGET_UNAVAILABLE is distinct from EVIDENCE_ABSENT on purpose:
#: "we could not measure it" and "we measured it and have nothing defensible to
#: compare it to" are different facts with different remedies, the first needing
#: better footage and the second needing a citation.
DimensionState = Literal[
    "MEASURED",
    "NOT_APPLICABLE",
    "EVIDENCE_ABSENT",
    "MEASUREMENT_INVALID",
    "TARGET_UNAVAILABLE",
]

#: Below this Oklab chroma a hue angle is not a meaningful quantity. Section 5.4.
MIN_CHROMA_FOR_HUE: Final[float] = 0.01

#: The measured skin hue centre, from references/color-theory/skin-targets-measured.md.
#: A centre WITHOUT a band, which is why it does not produce a score.
SKIN_HUE_CENTRE_DEGREES: Final[float] = 42.157


class ScorecardError(ValueError):
    """Raised when a scorecard cannot be assembled as asked."""


@dataclass(frozen=True)
class Target:
    """What a measured value is compared against, and on whose authority.

    ``band`` is the deviation at which the score is 9, the edge of the interval
    within which a difference is held to be visually indistinguishable.
    ``gross`` is the deviation at which the score is 0. Both must have a basis.
    A target with a centre but no band cannot produce a score and says so.
    """

    basis: TargetBasis
    centre: float | None = None
    interval: tuple[float, float] | None = None
    band: float | None = None
    gross: float | None = None
    citation: str | None = None
    conditioning: dict[str, Any] = field(default_factory=dict)

    @property
    def scoreable(self) -> bool:
        return self.band is not None and self.gross is not None and (
            self.centre is not None or self.interval is not None
        )


@dataclass(frozen=True)
class DimensionResult:
    """One dimension's measurement, and its score or the reason there is none."""

    name: str
    statistic: str
    value: float | None
    state: DimensionState
    reason: str | None = None
    target: Target | None = None
    score: float | None = None


@dataclass(frozen=True)
class Scorecard:
    """The full result. A vector always; a composite only when one is defined."""

    dimensions: tuple[DimensionResult, ...]
    composite: float | None
    composite_name: str | None
    coverage_signature: tuple[str, ...]
    refusal: str | None

    def by_name(self, name: str) -> DimensionResult:
        for dimension in self.dimensions:
            if dimension.name == name:
                return dimension
        raise ScorecardError(f"no dimension named {name!r}")


def deviation_score(value: float, target: Target) -> float:
    """Map a measured value to 0 to 10 through the section 6 piecewise function.

    10 anywhere inside the target interval, 9 at the tolerance edge outside it,
    0 at or beyond the gross-error bound, linear between. Tolerances may be
    asymmetric only by supplying an interval rather than a centre.
    """
    if not target.scoreable:
        raise ScorecardError("this target has no band or no gross bound, so it cannot score")

    if target.interval is not None:
        low, high = target.interval
        deviation = 0.0 if low <= value <= high else min(abs(value - low), abs(value - high))
    else:
        deviation = abs(value - float(target.centre))

    band = float(target.band)
    gross = float(target.gross)
    if gross <= band:
        raise ScorecardError("the gross bound must exceed the tolerance band")

    if deviation <= 0.0:
        return 10.0
    if deviation <= band:
        return 10.0 - deviation / band
    if deviation >= gross:
        return 0.0
    return 9.0 * (gross - deviation) / (gross - band)


def _oklab(display_rgb: np.ndarray) -> np.ndarray:
    import colour

    from colorist.corpus import _display_to_xyz

    return colour.XYZ_to_Oklab(_display_to_xyz(display_rgb))


def skin_hue_and_chroma(image: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    """Median per-pixel Oklab hue (by mean direction) and chroma over a mask.

    Per-pixel, not the chroma of a pooled median RGB. The two differ on
    heterogeneous skin, and `measure.MaskStat` already keeps that distinction
    deliberately, so the harness must not blur it.
    """
    sampled = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)[np.asarray(mask, dtype=bool)]
    if not sampled.size:
        return float("nan"), float("nan")
    lab = _oklab(sampled)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    angles = np.arctan2(lab[..., 2], lab[..., 1])
    mean_direction = np.degrees(
        np.arctan2(np.sin(angles).mean(), np.cos(angles).mean())
    ) % 360.0
    return float(mean_direction), float(np.median(chroma))


def _technical_dimension(technical: dict[str, Any] | None) -> DimensionResult:
    """Section 5.1. Scored by a table, because its inputs are pass or fail."""
    name, statistic = "technical_conform", "tags, range, introduced clipping"
    if technical is None:
        return DimensionResult(
            name, statistic, None, "EVIDENCE_ABSENT",
            "no technical evidence was supplied",
        )
    target = Target(
        basis="delivery_standard",
        citation="itu-bt709 plus the declared delivery profile",
    )
    tags = technical.get("tags_match")
    legal = technical.get("range_legal")
    clipping = technical.get("introduced_clipping_percent")

    if tags is False or legal is False:
        return DimensionResult(name, statistic, 0.0, "MEASURED",
                               "colour tags or sample range are non-conformant",
                               target, 0.0)
    if tags is None or legal is None:
        return DimensionResult(name, statistic, None, "EVIDENCE_ABSENT",
                               "tag or range evidence is missing", target)
    if clipping is None:
        return DimensionResult(
            name, statistic, None, "EVIDENCE_ABSENT",
            "introduced clipping needs an authenticated source reference", target,
        )
    if clipping > technical.get("clipping_threshold_percent", 0.5):
        return DimensionResult(name, statistic, 0.0, "MEASURED",
                               "grade-introduced clipping exceeds the threshold",
                               target, 0.0)
    return DimensionResult(name, statistic, 10.0, "MEASURED", None, target, 10.0)


def score_delivery(
    image: np.ndarray,
    *,
    skin_mask: np.ndarray | None = None,
    neutral_regions: tuple[np.ndarray, ...] = (),
    technical: dict[str, Any] | None = None,
    declarations: dict[str, Any] | None = None,
) -> Scorecard:
    """Measure every dimension, score the ones with a defensible target, refuse the rest.

    ``skin_mask`` and ``neutral_regions`` must be PINNED, that is derived once
    from the authenticated source and applied here, not re-derived from this
    image. Section 5.3 explains why: `measure._skin_mask` selects by HSV hue, so
    a delivery whose skin hue is badly wrong drops out of its own evidence set
    while orange wood joins it, and any hue score computed that way flatters the
    error that caused it.

    This function cannot verify that the masks were pinned. It records the
    obligation in the report and leaves the attestation to the caller, which is
    the honest split: a claim nobody can check should be labelled, not implied.
    """
    declared = dict(declarations or {})
    results: list[DimensionResult] = [_technical_dimension(technical)]

    skin_applicable = declared.get("skin_applicable", True)
    if not skin_applicable:
        for name, statistic in (
            ("skin_luma", "median Rec.709 luma over the skin mask, IRE"),
            ("skin_hue", "Oklab hue angle of the skin mask, degrees"),
            ("skin_chroma", "median per-pixel Oklab chroma over the skin mask"),
        ):
            results.append(
                DimensionResult(name, statistic, None, "NOT_APPLICABLE",
                                "the operator declared this footage has no skin")
            )
    elif skin_mask is None or not np.asarray(skin_mask, dtype=bool).any():
        for name, statistic in (
            ("skin_luma", "median Rec.709 luma over the skin mask, IRE"),
            ("skin_hue", "Oklab hue angle of the skin mask, degrees"),
            ("skin_chroma", "median per-pixel Oklab chroma over the skin mask"),
        ):
            results.append(
                DimensionResult(name, statistic, None, "EVIDENCE_ABSENT",
                                "skin is expected here but no usable region was supplied")
            )
    else:
        results.extend(_skin_dimensions(image, np.asarray(skin_mask, dtype=bool), declared))

    results.append(_neutral_dimension(image, neutral_regions, declared))
    results.extend(_tonal_dimensions(image, declared))

    return _assemble(tuple(results), declared)


def _skin_dimensions(
    image: np.ndarray, mask: np.ndarray, declared: dict[str, Any]
) -> list[DimensionResult]:
    values = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)
    luma = float(np.median(values[mask] @ np.array([0.2126, 0.7152, 0.0722])) * 100.0)
    hue, chroma = skin_hue_and_chroma(values, mask)

    key_level = declared.get("skin_luma_target_ire")
    luma_target = (
        Target(basis="declared_intent", centre=float(key_level), band=3.0, gross=15.0,
               conditioning={"declared_by": "operator"})
        if key_level is not None
        else None
    )
    luma_result = (
        DimensionResult("skin_luma", "median Rec.709 luma over the skin mask, IRE",
                        luma, "MEASURED", None, luma_target,
                        deviation_score(luma, luma_target))
        if luma_target is not None
        else DimensionResult(
            "skin_luma", "median Rec.709 luma over the skin mask, IRE", luma,
            "TARGET_UNAVAILABLE",
            "surface reflectance does not determine rendered luma; the operator "
            "must declare a key level for this to be scoreable",
        )
    )

    if chroma < MIN_CHROMA_FOR_HUE:
        hue_result = DimensionResult(
            "skin_hue", "Oklab hue angle of the skin mask, degrees", hue,
            "MEASUREMENT_INVALID",
            f"Oklab chroma {chroma:.5f} is below the floor {MIN_CHROMA_FOR_HUE}, "
            "where a hue angle is not a meaningful quantity",
        )
    else:
        hue_result = DimensionResult(
            "skin_hue", "Oklab hue angle of the skin mask, degrees", hue,
            "TARGET_UNAVAILABLE",
            f"a measured centre of {SKIN_HUE_CENTRE_DEGREES} degrees exists but no "
            "band does; the measured illuminant spread is a range of CORRECT "
            "values, not a tolerance for incorrect ones",
            Target(basis="measured_reflectance", centre=SKIN_HUE_CENTRE_DEGREES,
                   citation="references/color-theory/skin-targets-measured.md"),
        )

    chroma_result = DimensionResult(
        "skin_chroma", "median per-pixel Oklab chroma over the skin mask", chroma,
        "TARGET_UNAVAILABLE",
        "the preferred-skin tolerance source is not readable; Unpaywall reports "
        "preferred-skin-zeng-luo-2011 closed",
        Target(basis="perceptual_population",
               citation="preferred-skin-zeng-luo-2011, content not verified"),
    )
    return [luma_result, hue_result, chroma_result]


def _neutral_dimension(
    image: np.ndarray, regions: tuple[np.ndarray, ...], declared: dict[str, Any]
) -> DimensionResult:
    name = "neutral_consistency"
    statistic = "maximum pairwise region disagreement, 8-bit R minus B"
    values = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)

    usable = [np.asarray(region, dtype=bool) for region in regions]
    usable = [region for region in usable if region.any()]
    if len(usable) < 2:
        return DimensionResult(
            name, statistic, None, "EVIDENCE_ABSENT",
            "at least two neutral regions are needed to measure disagreement",
        )

    medians = [
        float(np.median(values[region][:, 0] - values[region][:, 2]) * 255.0)
        for region in usable
    ]
    worst = max(
        abs(first - second)
        for index, first in enumerate(medians)
        for second in medians[index + 1 :]
    )

    if not declared.get("neutral_regions_are_one_object", False):
        return DimensionResult(
            name, statistic, worst, "TARGET_UNAVAILABLE",
            "two whites under different motivated illuminants need not match; "
            "the operator must declare these regions one object that should",
            Target(basis="declared_intent"),
        )
    target = Target(basis="declared_intent", centre=0.0, band=2.0, gross=20.0,
                    conditioning={"same_object": True})
    return DimensionResult(name, statistic, worst, "MEASURED", None, target,
                           deviation_score(worst, target))


def _tonal_dimensions(image: np.ndarray, declared: dict[str, Any]) -> list[DimensionResult]:
    values = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)
    aperture = declared.get("active_aperture")
    luma = values @ np.array([0.2126, 0.7152, 0.0722])
    if aperture is not None:
        luma = luma[np.asarray(aperture, dtype=bool)]
    black = float(np.percentile(luma, 1) * 100.0)

    black_target_ire = declared.get("black_target_ire")
    if black_target_ire is None:
        black_result = DimensionResult(
            "tonal_black", "p1 luma within the active aperture, IRE", black,
            "TARGET_UNAVAILABLE",
            "a high-key or faded look legitimately has no display black; the "
            "operator must declare the intended placement",
            Target(basis="declared_intent"),
        )
    else:
        target = Target(basis="declared_intent", centre=float(black_target_ire),
                        band=1.0, gross=10.0)
        black_result = DimensionResult(
            "tonal_black", "p1 luma within the active aperture, IRE", black,
            "MEASURED", None, target, deviation_score(black, target),
        )

    highlight = DimensionResult(
        "tonal_highlight", "retained highlight distinguishability", None,
        "EVIDENCE_ABSENT",
        "needs an authenticated source reference; this sub-measure is relative",
        Target(basis="source_reference"),
    )
    separation = DimensionResult(
        "tonal_separation", "mid-tone percentile spread against the source", None,
        "EVIDENCE_ABSENT",
        "needs an authenticated source reference; this sub-measure is relative",
        Target(basis="source_reference"),
    )
    return [black_result, highlight, separation]


#: Section 7. A composite has a FIXED denominator and a coverage signature, and
#: composites with different signatures are never compared.
COMPOSITES: Final[dict[str, tuple[str, ...]]] = {
    "full_interview": (
        "technical_conform", "skin_luma", "skin_hue", "skin_chroma",
        "neutral_consistency", "tonal_black",
    ),
    "no_skin": ("technical_conform", "neutral_consistency", "tonal_black"),
}


def _assemble(results: tuple[DimensionResult, ...], declared: dict[str, Any]) -> Scorecard:
    by_name = {result.name: result for result in results}
    technical = by_name["technical_conform"]

    if technical.state != "MEASURED":
        return Scorecard(results, None, None, (),
                         f"technical conform is {technical.state}, so no composite exists")
    if technical.score == 0.0:
        return Scorecard(results, None, None, (),
                         "technical conform failed, so this is not a deliverable")

    skin_states = {by_name[name].state for name in ("skin_luma", "skin_hue", "skin_chroma")}
    if skin_states == {"NOT_APPLICABLE"}:
        wanted = COMPOSITES["no_skin"]
        composite_name = "no_skin"
    else:
        wanted = COMPOSITES["full_interview"]
        composite_name = "full_interview"

    missing = [name for name in wanted if by_name[name].score is None]
    if missing:
        return Scorecard(
            results, None, None, tuple(wanted),
            f"{composite_name} needs all of {list(wanted)}; these have no score: {missing}",
        )
    scores = [float(by_name[name].score) for name in wanted]
    return Scorecard(results, sum(scores) / len(scores), composite_name, tuple(wanted), None)


# ---------------------------------------------------------------------------
# Expected statistics and effect-size floors, for validation properties 5 and 6.
#
# Property 5 asks for numeric agreement of the STATISTIC at every severity, not
# merely ordering of the score. Property 6 asks for a stated minimum effect size
# per severity step, with a documented saturation point.
#
# WHICH PREDICTIONS ARE ANALYTIC AND WHICH ARE MEASURED
#
# Two of the three are exact and content-independent, because the injector's
# declared parameter IS the effect:
#
#   chroma  the Oklab chroma scales by exactly the declared factor
#   hue     the Oklab hue rotates by exactly the declared angle
#
# Verified on the first validation run: chroma at severity 1.0 read 0.02998
# against a reference 0.05997, precisely the declared 0.5 scale, and hue rotated
# exactly 12.000 degrees.
#
# Tone is NOT analytic and this module refuses to pretend otherwise. Its effect on
# black placement depends on where the content's blacks already sit, and on the
# corpus chart they sit at 24.3 IRE with no true black for a lift to act on, so
# the statistic moves only 2.87 percent at full severity. A predicted value would
# be a fitted number wearing a derivation. `expected_statistic` returns None for
# it and the caller must measure.
# ---------------------------------------------------------------------------

#: Minimum fractional change in the primary statistic per 0.25 severity step,
#: below which a step is not resolvable and property 6 fails. Measured on the
#: reference chart: chroma 0.125 per step, hue 3 degrees on a 44.44 degree base
#: which is 0.0675 per step. No saturation is observed anywhere in 0 to 1; every
#: family is linear in severity across the whole range.
EFFECT_SIZE_FLOOR_PER_STEP: Final[float] = 0.05
SATURATION_SEVERITY: Final[float | None] = None


def expected_statistic(family: str, severity: float, reference_value: float) -> float | None:
    """The analytically expected statistic after a defect, or None if not analytic.

    ``reference_value`` is the undamaged measurement of the same statistic, since
    both analytic families are multiplicative or additive on it rather than
    absolute.
    """
    from colorist.corpus import CHROMA_SCALE_AT_FULL, FAMILIES, HUE_ROTATION_AT_FULL

    if family not in FAMILIES:
        raise ScorecardError(f"unknown defect family {family!r}, expected one of {FAMILIES}")
    if not 0.0 <= severity <= 1.0:
        raise ScorecardError("severity must lie between 0 and 1 inclusive")

    if family == "chroma":
        return reference_value * (1.0 + severity * (CHROMA_SCALE_AT_FULL - 1.0))
    if family == "hue":
        return (reference_value + severity * HUE_ROTATION_AT_FULL) % 360.0
    # Tone. Content dependent, so there is nothing honest to return.
    return None
