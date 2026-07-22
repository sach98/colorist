# SPDX-License-Identifier: MIT
"""The bounded, source-based consistency and local QC workflows.

Both public functions return a :class:`~colorist.gates.RunResult` subtype.
Consistency treats every rendered delivery as a candidate until it verifies:
each iteration starts from the original source, frozen source ROI masks are
passed to decoded-delivery verification, and a failed final candidate is
removed rather than published.  Its reproducible parameters remain in
``best-candidate.json`` and the workflow report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from importlib import resources
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from colorist.corrections import (
    Correction,
    bt1886_decode,
    manifest_dict,
    solve_exposure,
    solve_wb,
)
from colorist.cuts import Shot, frames_to_pts, read_cutlist
from colorist.gates import (
    GateOutcome,
    GateSet,
    RunResult,
    evaluate,
    format_gate_outcome,
    gate_outcome_payload,
    load_gates,
    require_workflow,
)
from colorist.grade import (
    SourceEncodingError,
    _load_delivery_profile,
    _source_convert_params,
    grade_file,
)
from colorist.idt import camera_to_working
from colorist.measure import (
    MaskStat,
    ShotMeasurement,
    measure_shot,
    sample_positions,
    write_mask_sheet,
)
from colorist.render import ConvertParams, read_frame_rgb
from colorist.verify import _aggregate_gate_runs, verify_delivery


_ROOT = Path(__file__).resolve().parents[2]
_WHITE_BALANCE_GATES = {"whites_rb_balance", "whites_green_balance"}
_EXPOSURE_GATES = {"shadow_floor", "highlight_ceiling"}
_LUMA_WEIGHTS = np.array((0.2126, 0.7152, 0.0722), dtype=np.float64)
_SUPPORTED_LOG_ENCODINGS = {
    "slog3_sgamut3cine",
    "logc3ei800_awg3",
    "logc4_awg4",
    "vlog_vgamut",
    "clog3_cgamut",
}


@dataclass(frozen=True)
class WorkflowRunResult(RunResult):
    """A ``RunResult`` with the public iteration count for workflow callers."""

    iteration_count: int = 0
    delivery: Path | None = None

    @property
    def iterations(self) -> int:
        """Alias kept concise for command-line and manifest consumers."""
        return self.iteration_count


@dataclass(frozen=True)
class _ShotPlan:
    measurement: ShotMeasurement
    working_luma_p50: float | None
    correction: Correction
    automatic: bool
    reason: str | None
    short_shot_approved: bool


@dataclass(frozen=True)
class _Candidate:
    iteration: int
    result: RunResult
    corrections: dict[int, Correction]
    failed_gate_ids: list[str]


def run_consistency(
    src: Path | str,
    cutlist_csv: Path | str,
    preset: Path | str,
    delivery_profile: Path | str | Mapping[str, object],
    workdir: Path | str | None,
    curve_gamut: str | None = None,
    input_params: ConvertParams | None = None,
    confirm_metadata_override: bool = False,
    max_iterations: int = 3,
    report_dir: Path | str | None = None,
    mask_review: bool = False,
    approve_short_shots: bool = False,
) -> RunResult:
    """Normalize per-shot white balance and exposure under a bounded contract.

    A source measurement creates the only candidate masks.  Every candidate
    render is then produced by :func:`grade_file` from ``src`` with cumulative
    parameters, never from a previous encode.  A final ``FAIL`` keeps only its
    manifest and reports, not a video delivery.
    """
    source = Path(src)
    output_root = _workdir(source, workdir)
    report_root = output_root if report_dir is None else Path(report_dir)
    attempts: list[dict[str, Any]] = []
    best: _Candidate | None = None
    shot_plans: list[_ShotPlan] = []
    collision = _generated_state_collision(report_root, output_root)
    if collision is not None:
        return _workflow_result(
            RunResult(state="ERROR", gates=[], error=collision), 0
        )

    try:
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least one")
        gates = load_gates(_resolve_preset(preset, "gates"))
        require_workflow(gates, "consistency")
        profile_source = _resolve_profile(delivery_profile)
        profile = _load_delivery_profile(profile_source)
        shots = read_cutlist(Path(cutlist_csv))
        _refuse_existing_published_delivery(source, output_root, profile.container)

        in_params = _source_convert_params(
            source,
            input_params,
            confirm_metadata_override=confirm_metadata_override,
            curve_gamut=curve_gamut,
        )
        _require_supported_encoding(in_params, curve_gamut)
        frozen_measurements = _measure_source_shots(
            source,
            shots,
            in_params,
            curve_gamut,
            report_root / "masks",
        )
        if mask_review:
            _write_mask_review_sheets(
                source,
                shots,
                frozen_measurements,
                in_params,
                curve_gamut,
                report_root / "mask-review",
            )
        shot_plans = _solve_source_corrections(
            source,
            shots,
            frozen_measurements,
            in_params,
            curve_gamut,
            approve_short_shots=approve_short_shots,
        )
        corrections = {
            index: plan.correction for index, plan in enumerate(shot_plans)
        }

        # A required neutral is absent in at least one shot.  The no-correction
        # decision is still recorded, but rendering cannot turn absent source
        # evidence into a truthful consistency pass.
        if any(not plan.automatic for plan in shot_plans):
            source_result = _evaluate_source_measurements(gates, frozen_measurements)
            result = _workflow_result(source_result, 0)
            _write_workflow_reports(
                report_root,
                workflow="consistency",
                result=result,
                attempts=attempts,
                shot_plans=shot_plans,
                best=None,
            )
            return result

        for iteration in range(1, max_iterations + 1):
            candidate_root = output_root / ".consistency-candidates" / f"iteration-{iteration}"
            candidate_root.mkdir(parents=True, exist_ok=True)
            candidate_delivery = grade_file(
                source,
                shots,
                corrections,
                look=None,
                curve_gamut=curve_gamut,
                input_params=input_params,
                confirm_metadata_override=confirm_metadata_override,
                delivery_profile=profile_source,
                workdir=candidate_root,
            )
            candidate_result = verify_delivery(
                candidate_delivery,
                profile,
                gates,
                frozen_measurements,
                shots,
                source_reference=source,
                source_params=in_params,
                source_curve_gamut=curve_gamut,
            )
            failed_gate_ids = [
                gate.gate_id for gate in candidate_result.gates if gate.status == "FAIL"
            ]
            candidate = _Candidate(
                iteration=iteration,
                result=candidate_result,
                corrections=dict(corrections),
                failed_gate_ids=failed_gate_ids,
            )
            if best is None or _candidate_score(candidate) < _candidate_score(best):
                best = candidate

            attempt: dict[str, Any] = {
                "iteration": iteration,
                "state": candidate_result.state,
                "failed_gates": failed_gate_ids,
                "parameters": _corrections_payload(corrections),
                "render_source": str(source),
            }
            attempts.append(attempt)

            if candidate_result.state == "PASS":
                published = output_root / f"{source.stem}.graded.{profile.container}"
                # The refusal above ensures os.replace cannot overwrite a
                # user delivery.  The candidate is now the verified delivery.
                published.parent.mkdir(parents=True, exist_ok=True)
                candidate_delivery.replace(published)
                result = _workflow_result(candidate_result, iteration, published)
                _write_best_manifest(output_root, best)
                _write_workflow_reports(
                    report_root,
                    workflow="consistency",
                    result=result,
                    attempts=attempts,
                    shot_plans=shot_plans,
                    best=best,
                )
                return result

            # A candidate is never a diagnostic artifact by default.  Its
            # reports and deterministic parameters remain, but no failing
            # encoded delivery survives the workflow.
            candidate_delivery.unlink(missing_ok=True)

            if candidate_result.state != "FAIL" or iteration == max_iterations:
                result = _workflow_result(candidate_result, iteration)
                _write_best_manifest(output_root, best)
                _write_workflow_reports(
                    report_root,
                    workflow="consistency",
                    result=result,
                    attempts=attempts,
                    shot_plans=shot_plans,
                    best=best,
                )
                return result

            corrections, adjusted = _adjust_implicated_targets(
                corrections, candidate_result, candidate_root / "report.json"
            )
            attempt["adjusted_solver_targets"] = adjusted
            if not adjusted:
                # A range, tag, clipping, or look-only failure has no allowed
                # consistency solver target.  Rendering it again cannot be a
                # correction, so the workflow terminates honestly.
                result = _workflow_result(candidate_result, iteration)
                _write_best_manifest(output_root, best)
                _write_workflow_reports(
                    report_root,
                    workflow="consistency",
                    result=result,
                    attempts=attempts,
                    shot_plans=shot_plans,
                    best=best,
                )
                return result

        raise AssertionError("iteration loop exited without a terminal state")
    except Exception as error:
        result = _workflow_result(
            RunResult(state="ERROR", gates=[], error=f"{type(error).__name__}: {error}"),
            len(attempts),
        )
        _write_workflow_reports(
            report_root,
            workflow="consistency",
            result=result,
            attempts=attempts,
            shot_plans=shot_plans,
            best=best,
        )
        return result


def run_qc(
    src: Path | str,
    preset: Path | str,
    delivery_profile: Path | str | Mapping[str, object],
    report_dir: Path | str | None = None,
    source_reference: Path | str | None = None,
    curve_gamut: str | None = None,
    input_params: ConvertParams | None = None,
    confirm_metadata_override: bool = False,
    mask_review: bool = False,
) -> RunResult:
    """Verify a decoded delivery against an explicit expected output profile."""
    delivery = Path(src)
    if report_dir is None:
        return _workflow_result(
            RunResult(
                state="ERROR",
                gates=[],
                error="an explicit report_dir is required; no artifacts were written",
            ),
            0,
        )
    report_root = Path(report_dir)
    collision = _generated_state_collision(report_root)
    if collision is not None:
        return _workflow_result(
            RunResult(state="ERROR", gates=[], error=collision), 0
        )
    try:
        gates = load_gates(_resolve_preset(preset, "gates"))
        require_workflow(gates, "qc")
        profile_source = _resolve_profile(delivery_profile)
        profile = _load_delivery_profile(profile_source)
        delivery_params = ConvertParams(
            range=profile.range,
            matrix=profile.colorspace,
            transfer=profile.color_trc,
            primaries=profile.color_primaries,
        )
        frame_count = len(frames_to_pts(delivery))
        frames = sample_positions(frame_count)
        if not frames:
            raise ValueError("delivery has no frames to measure")

        reference = None if source_reference is None else Path(source_reference)
        if reference is None:
            frozen_measurement = measure_shot(
                delivery,
                frames,
                delivery_params,
                None,
                artifact_dir=report_root / "masks",
                shot_frame_count=frame_count,
            )
            source_params = None
            review_source = delivery
            review_params = delivery_params
            review_curve = None
        else:
            source_params = _source_convert_params(
                reference,
                input_params,
                confirm_metadata_override=confirm_metadata_override,
                curve_gamut=curve_gamut,
            )
            _require_supported_encoding(source_params, curve_gamut)
            frozen_measurement = measure_shot(
                reference,
                frames,
                source_params,
                curve_gamut,
                artifact_dir=report_root / "masks",
                shot_frame_count=frame_count,
            )
            review_source = reference
            review_params = source_params
            review_curve = curve_gamut
        if mask_review:
            _write_mask_review_sheets(
                review_source,
                [Shot(0, frame_count)],
                [frozen_measurement],
                review_params,
                review_curve,
                report_root / "mask-review",
            )
        verified = verify_delivery(
            delivery,
            profile,
            gates,
            [frozen_measurement],
            None,
            source_reference=reference,
            source_params=source_params,
            source_curve_gamut=curve_gamut,
            report_dir=report_root,
            workflow="qc",
        )
        return _workflow_result(verified, 0)
    except Exception as error:
        result = _workflow_result(
            RunResult(state="ERROR", gates=[], error=f"{type(error).__name__}: {error}"),
            0,
        )
        _write_workflow_reports(
            report_root,
            workflow="qc",
            result=result,
            attempts=[],
            shot_plans=[],
            best=None,
        )
        return result


def _workdir(source: Path, workdir: Path | str | None) -> Path:
    root = source.parent if workdir is None else Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_preset(preset: Path | str, directory: str) -> Path:
    candidate = Path(preset)
    if candidate.is_file():
        return candidate
    if candidate.suffix:
        repository_candidate = _ROOT / candidate
    else:
        repository_candidate = _ROOT / "presets" / directory / f"{candidate}.yaml"
    if repository_candidate.is_file():
        return repository_candidate
    resource_name = candidate.name if candidate.suffix == ".yaml" else f"{candidate.name}.yaml"
    packaged = resources.files("colorist").joinpath(
        "presets", directory, resource_name
    )
    if packaged.is_file():
        return packaged  # type: ignore[return-value]
    raise FileNotFoundError(f"{directory} preset not found: {preset}")


def _resolve_profile(profile: Path | str | Mapping[str, object]) -> Path | Mapping[str, object]:
    if isinstance(profile, Mapping):
        return profile
    candidate = Path(profile)
    if candidate.is_file():
        return candidate
    if candidate.suffix:
        repository_candidate = _ROOT / candidate
    else:
        repository_candidate = _ROOT / "presets" / "delivery" / f"{candidate}.yaml"
    if repository_candidate.is_file():
        return repository_candidate
    resource_name = candidate.name if candidate.suffix == ".yaml" else f"{candidate.name}.yaml"
    packaged = resources.files("colorist").joinpath(
        "presets", "delivery", resource_name
    )
    if packaged.is_file():
        return packaged  # type: ignore[return-value]
    raise FileNotFoundError(f"delivery profile not found: {profile}")


def _refuse_existing_published_delivery(source: Path, workdir: Path, container: str) -> None:
    published = workdir / f"{source.stem}.graded.{container}"
    if published.exists():
        raise FileExistsError(f"output exists; refusing to overwrite: {published}")


def _measure_source_shots(
    source: Path,
    shots: Sequence[Shot],
    in_params: ConvertParams,
    curve_gamut: str | None,
    artifact_dir: Path,
) -> list[ShotMeasurement]:
    measurements: list[ShotMeasurement] = []
    for index, shot in enumerate(shots):
        frames = [
            shot.start_frame + position
            for position in sample_positions(shot.end_frame - shot.start_frame)
        ]
        if not frames:
            raise ValueError(f"shot {index} has no frames to measure")
        measurements.append(
            measure_shot(
                source,
                frames,
                in_params,
                curve_gamut,
                artifact_dir=artifact_dir,
                shot_frame_count=shot.end_frame - shot.start_frame,
            )
        )
    return measurements


def _solve_source_corrections(
    source: Path,
    shots: Sequence[Shot],
    measurements: Sequence[ShotMeasurement],
    in_params: ConvertParams,
    curve_gamut: str | None,
    *,
    approve_short_shots: bool = False,
) -> list[_ShotPlan]:
    if len(shots) != len(measurements):
        raise ValueError("source shot count and measurement count differ")

    lumas: list[float] = []
    neutral_working: list[np.ndarray | None] = []
    reasons: list[str | None] = []
    for shot, measurement in zip(shots, measurements):
        frames = [
            shot.start_frame + position
            for position in sample_positions(shot.end_frame - shot.start_frame)
        ]
        luma = _working_luma_p50(source, frames, in_params, curve_gamut)
        lumas.append(luma)
        neutral = measurement.neutral
        if not measurement.temporal_coverage_sufficient and not approve_short_shots:
            neutral_working.append(None)
            reasons.append(
                "shot contains fewer than 3 frames: automatic correction requires approval"
            )
        elif neutral is None:
            neutral_working.append(None)
            reasons.append("no neutral evidence: no automatic correction")
        elif neutral.multimodal or neutral.median_rgb is None:
            neutral_working.append(None)
            reasons.append("multimodal neutral evidence: no automatic correction")
        else:
            working = bt1886_decode(np.asarray(neutral.median_rgb))
            if not np.all(np.isfinite(working)) or np.any(working <= 0.0):
                neutral_working.append(None)
                reasons.append("invalid neutral evidence: no automatic correction")
            else:
                neutral_working.append(working)
                reasons.append(None)

    eligible = [index for index, neutral in enumerate(neutral_working) if neutral is not None]
    target_luma = float(np.median([lumas[index] for index in eligible])) if eligible else None
    plans: list[_ShotPlan] = []
    for index, measurement in enumerate(measurements):
        neutral = neutral_working[index]
        if neutral is None or target_luma is None:
            plans.append(
                _ShotPlan(
                    measurement=measurement,
                    working_luma_p50=lumas[index],
                    correction=Correction(),
                    automatic=False,
                    reason=reasons[index],
                    short_shot_approved=False,
                )
            )
            continue
        plans.append(
            _ShotPlan(
                measurement=measurement,
                working_luma_p50=lumas[index],
                correction=Correction(
                    wb_gains=solve_wb(neutral),
                    exposure_ev=solve_exposure(lumas[index], target_luma),
                ),
                automatic=True,
                reason=None,
                short_shot_approved=(
                    not measurement.temporal_coverage_sufficient
                    and approve_short_shots
                ),
            )
        )
    return plans


def _working_luma_p50(
    source: Path,
    frames: Sequence[int],
    in_params: ConvertParams,
    curve_gamut: str | None,
) -> float:
    values: list[np.ndarray] = []
    for frame in frames:
        working = _to_working(
            read_frame_rgb(source, frame, in_params), curve_gamut
        )
        values.append(np.asarray(working @ _LUMA_WEIGHTS, dtype=np.float64).ravel())
    pooled = np.concatenate(values)
    value = float(np.percentile(pooled, 50))
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("source shot has no positive finite working luma")
    return value


def _to_working(code_rgb: np.ndarray, curve_gamut: str | None) -> np.ndarray:
    return (
        bt1886_decode(code_rgb)
        if curve_gamut is None
        else camera_to_working(curve_gamut, code_rgb)
    )


def _evaluate_source_measurements(
    gates: GateSet, measurements: Sequence[ShotMeasurement]
) -> RunResult:
    return _aggregate_gate_runs(
        [evaluate(gates, {"measurement": measurement}) for measurement in measurements]
    )


def _adjust_implicated_targets(
    corrections: Mapping[int, Correction],
    result: RunResult,
    verification_report: Path,
) -> tuple[dict[int, Correction], list[str]]:
    """Refine only source solvers corresponding to failed gate categories."""
    failed = {gate.gate_id for gate in result.gates if gate.status == "FAIL"}
    adjusted: list[str] = []
    updated = dict(corrections)
    report = _read_json(verification_report)

    if failed & _WHITE_BALANCE_GATES:
        for measurement in report.get("measurements", []):
            if not isinstance(measurement, Mapping):
                continue
            shot = measurement.get("shot")
            neutral = measurement.get("neutral")
            if not isinstance(shot, int) or not isinstance(neutral, Mapping):
                continue
            median = neutral.get("median_rgb")
            if shot not in updated or not _valid_rgb(median):
                continue
            residual = solve_wb(
                bt1886_decode(np.asarray(median, dtype=np.float64))
            )
            prior = updated[shot]
            gains = np.asarray(prior.wb_gains) * np.asarray(residual)
            if gains.shape != (3,) or np.any(gains <= 0.0):
                raise ValueError("white-balance gain adjustment must be positive RGB")
            updated[shot] = replace(prior, wb_gains=tuple(float(value) for value in gains))
            adjusted.append(f"shot-{shot}: white_balance")

    if failed & _EXPOSURE_GATES:
        outcomes = {gate.gate_id: gate for gate in result.gates if gate.status == "FAIL"}
        for gate_id in sorted(failed & _EXPOSURE_GATES):
            outcome = outcomes[gate_id]
            if not isinstance(outcome.observed, (int, float)) or not isinstance(
                outcome.threshold, (int, float)
            ):
                continue
            observed = float(outcome.observed)
            threshold = float(outcome.threshold)
            if observed <= 0.0:
                continue
            # A zero highlight ceiling has no finite exposure solution for
            # positive image data.  It remains a valid declarative failure:
            # move only the implicated exposure target one stop toward black
            # on each permitted retry, then preserve the best candidate at
            # the cap rather than manufacturing a deliverable.
            delta = -1.0 if threshold <= 0.0 else solve_exposure(observed, threshold)
            for shot, prior in updated.items():
                updated[shot] = replace(prior, exposure_ev=prior.exposure_ev + delta)
            adjusted.append(f"all-shots: exposure ({gate_id})")

    return updated, adjusted


def _valid_rgb(value: object) -> bool:
    try:
        rgb = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return False
    return rgb.shape == (3,) and np.all(np.isfinite(rgb)) and np.all(rgb > 0.0)


def _candidate_score(candidate: _Candidate) -> tuple[int, int, int]:
    statuses = [gate.status for gate in candidate.result.gates]
    return (
        statuses.count("FAIL"),
        statuses.count("INDETERMINATE_ABSENT_EVIDENCE")
        + statuses.count("SKIPPED_ABSENT_EVIDENCE"),
        candidate.iteration,
    )


def _workflow_result(
    result: RunResult, iteration_count: int, delivery: Path | None = None
) -> WorkflowRunResult:
    return WorkflowRunResult(
        state=result.state,
        gates=list(result.gates),
        error=result.error,
        iteration_count=iteration_count,
        delivery=delivery,
    )


def _corrections_payload(corrections: Mapping[int, Correction]) -> dict[str, dict[str, Any]]:
    return {str(index): manifest_dict(correction) for index, correction in corrections.items()}


def _shot_plans_payload(shot_plans: Sequence[_ShotPlan]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for index, plan in enumerate(shot_plans):
        payload.append(
            {
                "shot": index,
                "automatic_correction": plan.automatic,
                "reason": plan.reason,
                "temporal_coverage_sufficient": (
                    plan.measurement.temporal_coverage_sufficient
                ),
                "short_shot_approved": plan.short_shot_approved,
                "working_luma_p50": plan.working_luma_p50,
                "correction": manifest_dict(plan.correction),
                "neutral": _mask_payload(plan.measurement.neutral),
                "skin": _mask_payload(plan.measurement.skin),
            }
        )
    return payload


def _mask_payload(mask: MaskStat | None) -> dict[str, Any] | None:
    if mask is None:
        return None
    return {
        "median_rgb": None if mask.median_rgb is None else list(mask.median_rgb),
        "sample_px": mask.sample_px,
        "frames_used": mask.frames_used,
        "multimodal": mask.multimodal,
        "multimodal_axes": list(mask.multimodal_axes),
        "frozen_mask_path": str(mask.frozen_mask_path),
        "regions": [
            {
                "median_rgb": list(region.median_rgb),
                "px": region.px,
                "bbox": list(region.bbox),
            }
            for region in mask.regions
        ],
    }


def _gate_payload(gates: Sequence[GateOutcome]) -> list[dict[str, Any]]:
    return [gate_outcome_payload(gate) for gate in gates]


def _write_best_manifest(output_root: Path, best: _Candidate | None) -> None:
    if best is None:
        return
    payload = {
        "schema": "colorist/best-candidate/v1",
        "iteration": best.iteration,
        "state": best.result.state,
        "failed_gates": best.failed_gate_ids,
        "parameters": _corrections_payload(best.corrections),
    }
    _write_new_text(
        output_root / "best-candidate.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


def _write_workflow_reports(
    report_root: Path,
    *,
    workflow: str,
    result: WorkflowRunResult,
    attempts: Sequence[Mapping[str, Any]],
    shot_plans: Sequence[_ShotPlan],
    best: _Candidate | None,
) -> None:
    report_root.mkdir(parents=True, exist_ok=True)
    report = {
        "run": {
            "workflow": workflow,
            "state": result.state,
            "error": result.error,
            "iteration_count": result.iteration_count,
            "delivery": None if result.delivery is None else str(result.delivery),
        },
        "gates": _gate_payload(result.gates),
        "shots": _shot_plans_payload(shot_plans),
        "attempts": list(attempts),
        "best_candidate": (
            None
            if best is None
            else {
                "iteration": best.iteration,
                "state": best.result.state,
                "manifest": "best-candidate.json",
                "failed_gates": best.failed_gate_ids,
            }
        ),
    }
    _write_new_text(
        report_root / "report.json",
        json.dumps(report, indent=2, sort_keys=True) + "\n",
    )
    lines = [
        f"# {workflow.upper()} report",
        "",
        f"Result: **{result.state}**",
        f"Iterations: {result.iteration_count}",
        "",
        "## Gates",
        "",
    ]
    lines.extend(format_gate_outcome(gate) for gate in result.gates)
    if shot_plans:
        lines.extend(["", "## Shots", ""])
        for shot in report["shots"]:
            lines.append(
                f"- Shot {shot['shot']}: automatic correction "
                f"{str(shot['automatic_correction']).lower()}"
            )
            if shot["reason"]:
                lines.append(f"  Reason: {shot['reason']}")
            for mask_name in ("neutral", "skin"):
                mask = shot[mask_name]
                if mask is None:
                    continue
                if mask["multimodal"]:
                    lines.append(
                        f"  {mask_name} multimodal on: "
                        + ", ".join(mask["multimodal_axes"])
                    )
                for region_index, region in enumerate(mask["regions"]):
                    lines.append(
                        f"  {mask_name} region {region_index}: "
                        f"median_rgb={region['median_rgb']}, px={region['px']}, "
                        f"bbox={region['bbox']}"
                    )
    if best is not None:
        lines.extend(
            [
                "",
                "## Best candidate",
                "",
                f"- Iteration: {best.iteration}",
                "- Parameters: `best-candidate.json`",
            ]
        )
    if result.error:
        lines.extend(["", "## Error", "", result.error])
    _write_new_text(report_root / "report.md", "\n".join(lines) + "\n")


def _require_supported_encoding(
    in_params: ConvertParams, curve_gamut: str | None
) -> None:
    if curve_gamut is not None:
        if curve_gamut not in _SUPPORTED_LOG_ENCODINGS:
            raise SourceEncodingError(
                f"unsupported source encoding: {curve_gamut}; supported log encodings are "
                + ", ".join(sorted(_SUPPORTED_LOG_ENCODINGS))
            )
        return
    encoding = (
        f"range={in_params.range}, matrix={in_params.matrix}, "
        f"transfer={in_params.transfer}, primaries={in_params.primaries}"
    )
    if (
        in_params.range not in {"full", "limited"}
        or in_params.matrix != "bt709"
        or in_params.transfer != "bt709"
        or in_params.primaries != "bt709"
    ):
        raise SourceEncodingError(
            f"unsupported display encoding: {encoding}; v1 supports Rec.709 display input"
        )


def _write_mask_review_sheets(
    source: Path,
    shots: Sequence[Shot],
    measurements: Sequence[ShotMeasurement],
    in_params: ConvertParams,
    curve_gamut: str | None,
    destination: Path,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for shot_index, (shot, measurement) in enumerate(zip(shots, measurements)):
        frames = [
            shot.start_frame + position
            for position in sample_positions(shot.end_frame - shot.start_frame)
        ]
        if not frames:
            continue
        for mask_name in ("neutral", "skin"):
            mask_stat = getattr(measurement, mask_name)
            if mask_stat is None:
                continue
            with np.load(mask_stat.frozen_mask_path, allow_pickle=False) as archive:
                mask = np.asarray(archive["mask"], dtype=bool)
            for frame in frames:
                write_mask_sheet(
                    source,
                    frame,
                    mask,
                    destination
                    / f"shot-{shot_index:04d}-frame-{frame:08d}-{mask_name}.png",
                    in_params,
                    curve_gamut,
                )


def _generated_state_collision(
    report_root: Path, output_root: Path | None = None
) -> str | None:
    paths = [report_root / "report.json", report_root / "report.md"]
    if output_root is not None:
        paths.append(output_root / "best-candidate.json")
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return "generated artifact exists; refusing to overwrite: " + ", ".join(
        str(path) for path in existing
    )


def _write_new_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        handle.write(text)


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}
