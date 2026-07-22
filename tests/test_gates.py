# SPDX-License-Identifier: MIT
"""Tests for declarative gates, explicit evidence, and run state rules."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from colorist.gates import (
    GateSchemaError,
    HardGateWaiverError,
    Waiver,
    evaluate,
    load_gates,
    require_workflow,
)
from colorist.measure import MaskStat, RegionStat, ShotMeasurement
from colorist.verify import _delivery_evidence


PRESET = Path("presets/gates/interview.yaml")


@pytest.fixture
def interview_gates():
    return load_gates(PRESET)


@pytest.fixture
def clean_evidence() -> dict:
    return {
        "whites": {"r_minus_b": 2.0, "green_balance": 1.0},
        "shadows": {"p1": 0.75},
        "highlights": {"p99": 200.0},
        "skin": {"saturation_percent": 30.0},
        "delivery": {
            "range_extrema_valid": True,
            "tags_match": True,
            "introduced_clipping_percent": 0.1,
        },
    }


def _outcome(result, gate_id: str):
    return next(outcome for outcome in result.gates if outcome.gate_id == gate_id)


def _region(
    rgb: tuple[float, float, float],
    px: int = 100,
    bbox: tuple[int, int, int, int] = (0, 0, 5, 5),
) -> RegionStat:
    """A uniform-colour region: per-pixel gate stats equal the single colour's."""
    red, green, blue = (channel / 255 for channel in rgb)
    return RegionStat(
        median_rgb=(red, green, blue),
        px=px,
        bbox=bbox,
        r_minus_b_median=abs(red - blue),
        green_balance_median=abs(green - (red + blue) / 2),
    )


@pytest.mark.parametrize("gate_id", [
    "whites_rb_balance",
    "whites_green_balance",
    "shadow_floor",
    "highlight_ceiling",
    "skin_saturation",
    "delivery_range_extrema",
    "delivery_tags_match",
    "introduced_clipping",
])
def test_each_gate_passes_clean_evidence(interview_gates, clean_evidence, gate_id: str) -> None:
    result = evaluate(interview_gates, clean_evidence)

    assert _outcome(result, gate_id).status == "PASS"
    assert result.state == "PASS"


@pytest.mark.parametrize(
    ("gate_id", "path", "value"),
    [
        ("whites_rb_balance", ("whites", "r_minus_b"), 4.01),
        ("whites_green_balance", ("whites", "green_balance"), 3.01),
        ("shadow_floor", ("shadows", "p1"), 0.49),
        ("highlight_ceiling", ("highlights", "p99"), 205.01),
        ("skin_saturation", ("skin", "saturation_percent"), 24.99),
        ("skin_saturation", ("skin", "saturation_percent"), 38.01),
        ("delivery_range_extrema", ("delivery", "range_extrema_valid"), False),
        ("delivery_tags_match", ("delivery", "tags_match"), False),
        ("introduced_clipping", ("delivery", "introduced_clipping_percent"), 0.51),
    ],
)
def test_each_gate_rejects_seeded_violation(
    interview_gates, clean_evidence, gate_id: str, path: tuple[str, str], value
) -> None:
    evidence = deepcopy(clean_evidence)
    evidence[path[0]][path[1]] = value

    result = evaluate(interview_gates, evidence)

    assert _outcome(result, gate_id).status == "FAIL"
    assert result.state == "FAIL"


def test_missing_required_white_evidence_is_indeterminate(
    interview_gates, clean_evidence
) -> None:
    evidence = deepcopy(clean_evidence)
    evidence.pop("whites")

    result = evaluate(interview_gates, evidence)

    assert _outcome(result, "whites_rb_balance").status == "SKIPPED_ABSENT_EVIDENCE"
    assert _outcome(result, "whites_green_balance").status == "SKIPPED_ABSENT_EVIDENCE"
    assert result.state == "INDETERMINATE"


def test_missing_optional_skin_evidence_does_not_make_run_indeterminate(
    interview_gates, clean_evidence
) -> None:
    evidence = deepcopy(clean_evidence)
    evidence.pop("skin")

    result = evaluate(interview_gates, evidence)

    assert _outcome(result, "skin_saturation").status == "SKIPPED_ABSENT_EVIDENCE"
    assert result.state == "PASS"


@pytest.mark.parametrize(
    ("gate_id", "regions"),
    [
        (
            "whites_rb_balance",
            [
                (130.0, 130.0, 125.5),
                (127.0, 127.0, 128.0),
            ],
        ),
        (
            "whites_green_balance",
            [
                (128.0, 131.5, 128.0),
                (128.0, 126.0, 128.0),
            ],
        ),
    ],
)
def test_white_gates_use_worst_region_not_pooled_median(
    interview_gates, clean_evidence, gate_id: str, regions: list[tuple[float, float, float]]
) -> None:
    neutral = MaskStat(
        median_rgb=(128 / 255, 128 / 255, 128 / 255),
        sample_px=200,
        frames_used=3,
        frozen_mask_path=Path("unused.mask.npz"),
        regions=[
            _region(rgb, bbox=(index * 10, 0, index * 10 + 5, 5))
            for index, rgb in enumerate(regions)
        ],
        multimodal=False,
        multimodal_axes=(),
        saturation_median=None,
    )
    measurement = ShotMeasurement(
        luma_percentiles={"p1": 1.0, "p50": 100.0, "p99": 200.0},
        neutral=neutral,
        skin=None,
        temporal_coverage_sufficient=True,
    )
    evidence = {"measurement": measurement, "delivery": clean_evidence["delivery"]}

    result = evaluate(interview_gates, evidence)

    assert _outcome(result, gate_id).status == "FAIL"
    assert result.state == "FAIL"


def test_symmetric_cast_region_fails_the_per_pixel_r_minus_b_statistic(
    interview_gates, clean_evidence
) -> None:
    """A region with symmetric warm and cool pixels has equal channel medians

    (|median(R) - median(B)| = 0, which the old statistic passed) but a large
    per-pixel median |R - B|. The gate must read the per-pixel statistic and
    fail. Threshold is 4.0.
    """
    region = RegionStat(
        median_rgb=(128 / 255, 128 / 255, 128 / 255),
        px=100,
        bbox=(0, 0, 5, 5),
        r_minus_b_median=10 / 255,
        green_balance_median=0.0,
    )
    neutral = MaskStat(
        median_rgb=(128 / 255, 128 / 255, 128 / 255),
        sample_px=100,
        frames_used=3,
        frozen_mask_path=Path("unused.mask.npz"),
        regions=[region],
        multimodal=False,
        multimodal_axes=(),
        saturation_median=None,
    )
    measurement = ShotMeasurement(
        luma_percentiles={"p1": 1.0, "p50": 100.0, "p99": 200.0},
        neutral=neutral,
        skin=None,
        temporal_coverage_sufficient=True,
    )

    result = evaluate(
        interview_gates,
        {"measurement": measurement, "delivery": clean_evidence["delivery"]},
    )

    outcome = _outcome(result, "whites_rb_balance")
    assert outcome.observed == pytest.approx(10.0, abs=1e-9)
    assert outcome.status == "FAIL"
    assert result.state == "FAIL"


def test_green_multimodal_regions_make_white_gates_indeterminate(
    interview_gates, clean_evidence
) -> None:
    neutral = MaskStat(
        median_rgb=None,
        sample_px=200,
        frames_used=3,
        frozen_mask_path=Path("unused.mask.npz"),
        regions=[
            _region((140, 150, 140), bbox=(0, 0, 5, 5)),
            _region((150, 130, 150), bbox=(10, 0, 15, 5)),
        ],
        multimodal=True,
        multimodal_axes=("green_balance",),
        saturation_median=None,
    )
    measurement = ShotMeasurement(
        luma_percentiles={"p1": 1.0, "p50": 100.0, "p99": 200.0},
        neutral=neutral,
        skin=None,
        temporal_coverage_sufficient=True,
    )

    result = evaluate(
        interview_gates,
        {"measurement": measurement, "delivery": clean_evidence["delivery"]},
    )

    outcome = _outcome(result, "whites_green_balance")
    assert outcome.status == "INDETERMINATE_ABSENT_EVIDENCE"
    assert outcome.reason == "multimodal neutral regions disagree on: green_balance"
    assert result.state == "INDETERMINATE"


def test_missing_hard_gate_evidence_is_indeterminate_without_required_coverage(
    interview_gates, clean_evidence
) -> None:
    evidence = deepcopy(clean_evidence)
    evidence["delivery"].pop("introduced_clipping_percent")

    result = evaluate(interview_gates, evidence)

    outcome = _outcome(result, "introduced_clipping")
    assert outcome.status == "INDETERMINATE_ABSENT_EVIDENCE"
    assert outcome.reason == "absent evidence: delivery.introduced_clipping_percent"
    assert result.state == "INDETERMINATE"


def test_waived_soft_gate_is_recorded_as_waived(interview_gates, clean_evidence) -> None:
    evidence = deepcopy(clean_evidence)
    evidence["shadows"]["p1"] = 0.1

    result = evaluate(
        interview_gates,
        evidence,
        waivers=[Waiver("shadow_floor", "Intentional low-key interview setup", "shot-4")],
    )

    assert _outcome(result, "shadow_floor").status == "WAIVED"
    assert result.state == "PASS"


def test_hard_gate_cannot_be_waived(interview_gates, clean_evidence) -> None:
    with pytest.raises(HardGateWaiverError, match="hard gate"):
        evaluate(
            interview_gates,
            clean_evidence,
            waivers=[Waiver("delivery_tags_match", "Metadata accepted", "delivery")],
        )


def test_absent_hard_gate_cannot_be_silenced_by_waiver(
    interview_gates, clean_evidence
) -> None:
    evidence = deepcopy(clean_evidence)
    evidence["delivery"].pop("tags_match")

    with pytest.raises(HardGateWaiverError, match="hard gate"):
        evaluate(
            interview_gates,
            evidence,
            waivers=[Waiver("delivery_tags_match", "Metadata accepted", "delivery")],
        )


def test_every_shipped_hard_gate_evidence_key_has_a_code_path_producer() -> None:
    evidence = _delivery_evidence(
        {"valid": True},
        {"valid": True},
        {"available": True, "introduced_clipping_percent": 0.0},
    )
    produced = {
        f"{section}.{key}"
        for section, values in evidence.items()
        for key in values
    }

    for preset in sorted(Path("presets/gates").glob("*.yaml")):
        hard_keys = {
            gate.evidence_key
            for gate in load_gates(preset).gates
            if gate.gate_class == "hard"
        }
        assert hard_keys <= produced, f"{preset}: {sorted(hard_keys - produced)}"


def test_gate_preset_workflow_mismatch_is_refused(interview_gates) -> None:
    qc_only = replace(interview_gates, workflow="qc")

    with pytest.raises(GateSchemaError, match="not workflow consistency"):
        require_workflow(qc_only, "consistency")
