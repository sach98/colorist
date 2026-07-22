# SPDX-License-Identifier: MIT
"""Declarative QC gates, frozen-measurement evidence, and run state rules."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math
import numbers
from pathlib import Path
from typing import Any, Literal

from colorist.measure import ShotMeasurement

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised only without dependency install
    yaml = None  # type: ignore[assignment]


GateClass = Literal["hard", "soft"]
GateStatus = Literal[
    "PASS",
    "FAIL",
    "INDETERMINATE_ABSENT_EVIDENCE",
    "SKIPPED_ABSENT_EVIDENCE",
    "WAIVED",
]
RunState = Literal["PASS", "FAIL", "INDETERMINATE", "ERROR"]
_MISSING = object()
_MEASUREMENT_SECTIONS = {"shadows", "highlights", "whites", "skin"}


@dataclass(frozen=True)
class Gate:
    """One declarative threshold against a named item of evaluation evidence."""

    gate_id: str
    gate_class: GateClass
    coverage: str
    domain: str
    statistic: str
    operator: str
    threshold: float | bool | tuple[float, float]
    evidence_key: str
    rationale: str
    validation_status: str


@dataclass(frozen=True)
class GateSet:
    """A validated gate preset and soft coverage required for a passing run.

    Hard gates are always required. ``required_coverage`` only promotes absent
    soft-gate evidence from an optional skip to an indeterminate run.
    """

    gates: list[Gate]
    required_coverage: list[str]
    workflow: str | tuple[str, ...] | None = None


@dataclass(frozen=True)
class Waiver:
    """A recorded decision to waive a soft gate for a stated scope."""

    gate_id: str
    reason: str
    scope: str


@dataclass(frozen=True)
class GateOutcome:
    """One gate result with its observed and configured numeric values."""

    gate_id: str
    status: GateStatus
    observed: float | bool | None
    threshold: float | bool | tuple[float, float]
    domain: str
    operator: str
    numbers: dict[str, float]
    waiver: Waiver | None = None
    reason: str | None = None

    @property
    def state(self) -> GateStatus:
        """Alias for callers that use state terminology at every result level."""
        return self.status


@dataclass(frozen=True)
class RunResult:
    """The complete result of evaluating a gate set against one evidence bundle."""

    state: RunState
    gates: list[GateOutcome]
    error: str | None = None


class GateSchemaError(ValueError):
    """Raised when a gate-preset YAML document does not meet the schema."""


class HardGateWaiverError(ValueError):
    """Raised when a caller attempts to waive a non-waivable hard gate."""


def load_gates(path: Path | Any) -> GateSet:
    """Load and validate a YAML gate preset."""
    raw = _load_yaml(Path(path) if isinstance(path, (str, Path)) else path)
    if not isinstance(raw, Mapping):
        raise GateSchemaError("gate preset root must be a mapping")

    required_coverage = raw.get("required_coverage", [])
    if not isinstance(required_coverage, list) or not all(
        isinstance(item, str) and item for item in required_coverage
    ):
        raise GateSchemaError("required_coverage must be a list of non-empty strings")

    raw_gates = raw.get("gates")
    if not isinstance(raw_gates, list) or not raw_gates:
        raise GateSchemaError("gate preset must define a non-empty gates list")
    gates = [_parse_gate(item, index) for index, item in enumerate(raw_gates)]
    ids = [gate.gate_id for gate in gates]
    if len(set(ids)) != len(ids):
        raise GateSchemaError("gate ids must be unique")

    soft_coverage = {
        gate.coverage for gate in gates if gate.gate_class == "soft"
    }
    unknown_required = set(required_coverage) - soft_coverage
    if unknown_required:
        raise GateSchemaError(
            "required coverage has no matching soft gates: "
            f"{sorted(unknown_required)}"
        )
    workflow = raw.get("workflow")
    if isinstance(workflow, list):
        if not workflow or not all(isinstance(item, str) and item for item in workflow):
            raise GateSchemaError(
                "workflow must be a non-empty string or list of non-empty strings"
            )
        workflow = tuple(workflow)
    elif workflow is not None and (not isinstance(workflow, str) or not workflow):
        raise GateSchemaError(
            "workflow must be a non-empty string or list of non-empty strings"
        )
    return GateSet(gates=gates, required_coverage=list(required_coverage), workflow=workflow)


def require_workflow(gates: GateSet, workflow: str) -> None:
    """Refuse a preset that does not declare support for the active workflow."""
    declared = gates.workflow
    if declared is None:
        raise GateSchemaError("gate preset must declare its workflow")
    supported = (declared,) if isinstance(declared, str) else declared
    if workflow not in supported:
        raise GateSchemaError(
            f"gate preset supports {list(supported)}, not workflow {workflow}"
        )


def evaluate(
    gates: GateSet,
    evidence: Mapping[str, Any],
    waivers: Iterable[Waiver] = (),
) -> RunResult:
    """Evaluate gates against evidence and apply only valid soft-gate waivers.

    Missing hard-gate evidence produces ``INDETERMINATE_ABSENT_EVIDENCE`` and
    always makes the run ``INDETERMINATE``. Missing soft-gate evidence remains
    ``SKIPPED_ABSENT_EVIDENCE`` and affects the run only when its coverage is
    in ``required_coverage``. A known numeric or schema error makes the run
    ``ERROR`` instead of being misreported as a threshold failure.
    """
    waiver_by_id = _validate_waivers(gates, waivers)
    merged_evidence = _merge_measurement_evidence(evidence)
    outcomes: list[GateOutcome] = []
    hard_absent = False
    required_soft_absent = False
    measurement_indeterminate = False

    for gate in gates.gates:
        waiver = waiver_by_id.get(gate.gate_id)
        observed = _lookup(merged_evidence, gate.evidence_key)
        indeterminate_reason = _measurement_indeterminate_reason(
            merged_evidence, gate
        )
        if indeterminate_reason is not None:
            outcomes.append(
                GateOutcome(
                    gate_id=gate.gate_id,
                    status="INDETERMINATE_ABSENT_EVIDENCE",
                    observed=None,
                    threshold=gate.threshold,
                    domain=gate.domain,
                    operator=gate.operator,
                    numbers=_numbers(_MISSING, gate.threshold),
                    reason=indeterminate_reason,
                )
            )
            measurement_indeterminate = True
            continue
        if waiver is not None:
            outcomes.append(
                GateOutcome(
                    gate_id=gate.gate_id,
                    status="WAIVED",
                    observed=None if observed is _MISSING else observed,
                    threshold=gate.threshold,
                    domain=gate.domain,
                    operator=gate.operator,
                    numbers=_numbers(observed, gate.threshold),
                    waiver=waiver,
                )
            )
            continue
        if observed is _MISSING or observed is None:
            status: GateStatus = (
                "INDETERMINATE_ABSENT_EVIDENCE"
                if gate.gate_class == "hard"
                else "SKIPPED_ABSENT_EVIDENCE"
            )
            outcomes.append(
                GateOutcome(
                    gate_id=gate.gate_id,
                    status=status,
                    observed=None,
                    threshold=gate.threshold,
                    domain=gate.domain,
                    operator=gate.operator,
                    numbers=_numbers(observed, gate.threshold),
                    reason=f"absent evidence: {gate.evidence_key}",
                )
            )
            hard_absent |= gate.gate_class == "hard"
            required_soft_absent |= (
                gate.gate_class == "soft"
                and gate.coverage in gates.required_coverage
            )
            continue

        try:
            status = "PASS" if _passes(gate, observed) else "FAIL"
            outcomes.append(
                GateOutcome(
                    gate_id=gate.gate_id,
                    status=status,
                    observed=observed,
                    threshold=gate.threshold,
                    domain=gate.domain,
                    operator=gate.operator,
                    numbers=_numbers(observed, gate.threshold),
                )
            )
        except (TypeError, ValueError) as error:
            return RunResult(state="ERROR", gates=outcomes, error=f"{gate.gate_id}: {error}")

    if any(outcome.status == "FAIL" for outcome in outcomes):
        return RunResult(state="FAIL", gates=outcomes)
    if hard_absent or required_soft_absent or measurement_indeterminate:
        return RunResult(state="INDETERMINATE", gates=outcomes)
    return RunResult(state="PASS", gates=outcomes)


def evidence_from_measurement(measurement: ShotMeasurement) -> dict[str, dict[str, float]]:
    """Adapt frozen-mask measurements to the interview preset evidence keys."""
    if not measurement.temporal_coverage_sufficient:
        return {}
    evidence: dict[str, dict[str, float]] = {
        "shadows": {"p1": measurement.luma_percentiles["p1"]},
        "highlights": {"p99": measurement.luma_percentiles["p99"]},
    }
    if (
        measurement.neutral is not None
        and measurement.neutral.median_rgb is not None
        and measurement.neutral.regions
    ):
        # The declared statistic is the median of the per-pixel |R - B| within a
        # region, not |median(R) - median(B)|; the worst region gates the shot.
        evidence["whites"] = {
            "r_minus_b": 255
            * max(region.r_minus_b_median for region in measurement.neutral.regions),
            "green_balance": 255
            * max(region.green_balance_median for region in measurement.neutral.regions),
        }
    if (
        measurement.skin is not None
        and measurement.skin.median_rgb is not None
        and measurement.skin.saturation_median is not None
    ):
        evidence["skin"] = {
            "saturation_percent": measurement.skin.saturation_median * 100
        }
    return evidence


def gate_outcome_payload(outcome: GateOutcome) -> dict[str, Any]:
    """Serialize one outcome with the gate schema needed to audit its decision."""
    payload: dict[str, Any] = {
        "id": outcome.gate_id,
        "outcome": outcome.status,
        "measured": _measured_value(outcome.observed),
        "threshold": outcome.threshold,
        "domain": outcome.domain,
        "units": outcome.domain,
        "operator": outcome.operator,
        # Keep the earlier report fields available for existing consumers.
        "status": outcome.status,
        "observed": outcome.observed,
        "numbers": outcome.numbers,
        "waiver": (
            None
            if outcome.waiver is None
            else {
                "reason": outcome.waiver.reason,
                "scope": outcome.waiver.scope,
            }
        ),
    }
    if outcome.reason is not None:
        payload["reason"] = outcome.reason
    return payload


def format_gate_outcome(outcome: GateOutcome) -> str:
    """Return a Markdown gate line containing the exact evaluated values."""
    details = [f"measured {_format_measured(outcome.observed)}"]
    if outcome.reason is not None:
        details.append(f"reason: {outcome.reason}")
    details.extend(
        [
            f"gate {_format_gate_threshold(outcome.operator, outcome.threshold)}",
            outcome.domain,
        ]
    )
    return f"- {outcome.gate_id}: {outcome.status} ({', '.join(details)})"


def _parse_gate(raw: object, index: int) -> Gate:
    if not isinstance(raw, Mapping):
        raise GateSchemaError(f"gate {index} must be a mapping")
    required = {
        "id",
        "class",
        "coverage",
        "domain",
        "statistic",
        "operator",
        "threshold",
        "evidence_key",
        "rationale",
        "validation_status",
    }
    missing = required - set(raw)
    if missing:
        raise GateSchemaError(f"gate {index} missing fields: {sorted(missing)}")
    string_fields = (
        "id",
        "class",
        "coverage",
        "domain",
        "statistic",
        "operator",
        "evidence_key",
        "rationale",
        "validation_status",
    )
    if any(not isinstance(raw[field], str) or not raw[field] for field in string_fields):
        raise GateSchemaError(f"gate {index} has an empty or non-string text field")
    gate_class = raw["class"]
    if gate_class not in {"hard", "soft"}:
        raise GateSchemaError(f"gate {index} class must be hard or soft")
    operator = raw["operator"]
    threshold = _parse_threshold(operator, raw["threshold"], index)
    return Gate(
        gate_id=raw["id"],
        gate_class=gate_class,
        coverage=raw["coverage"],
        domain=raw["domain"],
        statistic=raw["statistic"],
        operator=operator,
        threshold=threshold,
        evidence_key=raw["evidence_key"],
        rationale=raw["rationale"],
        validation_status=raw["validation_status"],
    )


def _parse_threshold(
    operator: str, value: object, index: int
) -> float | bool | tuple[float, float]:
    if operator == "equals":
        if not isinstance(value, bool):
            raise GateSchemaError(f"gate {index} equals threshold must be boolean")
        return value
    if operator == "between_inclusive":
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(not _is_number(item) for item in value)
        ):
            raise GateSchemaError(f"gate {index} range threshold must have two numbers")
        lower, upper = (float(item) for item in value)
        if not lower <= upper:
            raise GateSchemaError(f"gate {index} range threshold must be ordered")
        return (lower, upper)
    if operator not in {"less_than_or_equal", "greater_than_or_equal"}:
        raise GateSchemaError(f"gate {index} has unsupported operator {operator}")
    if not _is_number(value):
        raise GateSchemaError(f"gate {index} numeric threshold must be a number")
    threshold = float(value)
    if not math.isfinite(threshold):
        raise GateSchemaError(f"gate {index} numeric threshold must be finite")
    return threshold


def _validate_waivers(gates: GateSet, waivers: Iterable[Waiver]) -> dict[str, Waiver]:
    by_id = {gate.gate_id: gate for gate in gates.gates}
    selected: dict[str, Waiver] = {}
    for waiver in waivers:
        gate = by_id.get(waiver.gate_id)
        if gate is None:
            raise ValueError(f"cannot waive unknown gate {waiver.gate_id}")
        if gate.gate_class == "hard":
            raise HardGateWaiverError(f"cannot waive hard gate {waiver.gate_id}")
        if not waiver.reason or not waiver.scope:
            raise ValueError("waiver reason and scope must be non-empty")
        if waiver.gate_id in selected:
            raise ValueError(f"duplicate waiver for gate {waiver.gate_id}")
        selected[waiver.gate_id] = waiver
    return selected


def _merge_measurement_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Merge optional ``ShotMeasurement`` evidence without mutating caller input."""
    merged = dict(evidence)
    measurement = merged.pop("measurement", None)
    if measurement is None:
        return merged
    if not isinstance(measurement, ShotMeasurement):
        raise TypeError("measurement evidence must be a ShotMeasurement")
    merged["_measurement_context"] = {
        "temporal_coverage_sufficient": measurement.temporal_coverage_sufficient,
        "multimodal_axes": (
            []
            if measurement.neutral is None
            else list(measurement.neutral.multimodal_axes)
        ),
    }
    for section, values in evidence_from_measurement(measurement).items():
        current = merged.get(section)
        if current is None:
            merged[section] = values
        elif isinstance(current, Mapping):
            merged[section] = {**values, **current}
        else:
            raise TypeError(f"evidence section {section} must be a mapping")
    return merged


def _measurement_indeterminate_reason(
    evidence: Mapping[str, Any], gate: Gate
) -> str | None:
    section = gate.evidence_key.split(".", maxsplit=1)[0]
    if section not in _MEASUREMENT_SECTIONS:
        return None
    context = evidence.get("_measurement_context")
    if not isinstance(context, Mapping):
        return None
    if context.get("temporal_coverage_sufficient") is False:
        return "shot contains fewer than 3 frames; measured values are not gateable"
    axes = context.get("multimodal_axes")
    if section == "whites" and isinstance(axes, list) and axes:
        return "multimodal neutral regions disagree on: " + ", ".join(
            str(axis) for axis in axes
        )
    return None


def _lookup(evidence: Mapping[str, Any], key: str) -> object:
    value: object = evidence
    for part in key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _passes(gate: Gate, observed: object) -> bool:
    if gate.operator == "equals":
        if not isinstance(observed, bool):
            raise TypeError("boolean evidence is required")
        return observed is gate.threshold
    if not _is_number(observed):
        raise TypeError("numeric evidence is required")
    value = float(observed)
    if not math.isfinite(value):
        raise ValueError("numeric evidence must be finite")
    if gate.operator == "less_than_or_equal":
        return value <= gate.threshold
    if gate.operator == "greater_than_or_equal":
        return value >= gate.threshold
    lower, upper = gate.threshold
    return lower <= value <= upper


def _numbers(
    observed: object, threshold: float | bool | tuple[float, float]
) -> dict[str, float]:
    numbers_out: dict[str, float] = {}
    if _is_number(observed):
        numbers_out["observed"] = float(observed)
    elif isinstance(observed, bool):
        numbers_out["observed"] = float(observed)
    if isinstance(threshold, tuple):
        numbers_out["minimum"] = threshold[0]
        numbers_out["maximum"] = threshold[1]
    elif isinstance(threshold, bool):
        numbers_out["threshold"] = float(threshold)
    else:
        numbers_out["threshold"] = threshold
    return numbers_out


def _measured_value(observed: object) -> float | bool | None:
    if _is_number(observed):
        return float(observed)
    if isinstance(observed, bool):
        return observed
    return None


def _format_measured(observed: object) -> str:
    measured = _measured_value(observed)
    if isinstance(measured, bool):
        return str(measured).lower()
    if measured is None:
        return "absent"
    return f"{measured:+}"


def _format_gate_threshold(
    operator: str, threshold: float | bool | tuple[float, float]
) -> str:
    if operator == "between_inclusive":
        lower, upper = threshold
        return f"between {lower} and {upper}"
    if operator == "equals":
        return f"== {str(threshold).lower()}"
    symbol = {
        "less_than_or_equal": "<=",
        "greater_than_or_equal": ">=",
    }[operator]
    return f"{symbol} {threshold}"


def _is_number(value: object) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, bool)


def _load_yaml(path: Any) -> object:
    """Load YAML with PyYAML, or the preset's strict subset when offline."""
    text = path.read_text()
    if yaml is not None:
        return yaml.safe_load(text)
    return _load_simple_yaml(text)


def _load_simple_yaml(text: str) -> dict[str, object]:
    """Read the small mapping-and-list YAML subset used by gate presets.

    PyYAML is the normal dependency.  This fallback exists only so the checked
    in preset remains readable in an offline verification environment where the
    declared package cannot be installed.
    """
    root: dict[str, object] = {}
    current_section: str | None = None
    current_gate: dict[str, object] | None = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0:
            key, value = _split_yaml_item(line, line_number)
            current_section = key
            current_gate = None
            root[key] = _parse_yaml_scalar(value) if value else []
        elif indent == 2 and line.startswith("- "):
            if current_section is None:
                raise GateSchemaError(f"YAML line {line_number} has no parent key")
            item = line[2:].strip()
            if current_section == "gates":
                key, value = _split_yaml_item(item, line_number)
                current_gate = {key: _parse_yaml_scalar(value)}
                gates = root[current_section]
                if not isinstance(gates, list):
                    raise GateSchemaError(f"YAML line {line_number} has invalid gates list")
                gates.append(current_gate)
            else:
                values = root[current_section]
                if not isinstance(values, list):
                    raise GateSchemaError(f"YAML line {line_number} has invalid list")
                values.append(_parse_yaml_scalar(item))
        elif indent == 4 and current_section == "gates" and current_gate is not None:
            key, value = _split_yaml_item(line, line_number)
            current_gate[key] = _parse_yaml_scalar(value)
        else:
            raise GateSchemaError(f"unsupported YAML structure at line {line_number}")
    return root


def _split_yaml_item(line: str, line_number: int) -> tuple[str, str]:
    if ":" not in line:
        raise GateSchemaError(f"YAML line {line_number} must contain a colon")
    key, value = line.split(":", maxsplit=1)
    if not key:
        raise GateSchemaError(f"YAML line {line_number} has an empty key")
    return key.strip(), value.strip()


def _parse_yaml_scalar(value: str) -> object:
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [] if not inner else [_parse_yaml_scalar(item.strip()) for item in inner.split(",")]
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value.strip('"\'')
