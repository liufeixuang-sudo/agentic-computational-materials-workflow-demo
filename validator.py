"""Validation gates for task input, structure metadata, and execution output.

This module validates supplied data only. It does not read credentials or call APIs.
Run: python validator.py
"""

import json
import math
from dataclasses import asdict, dataclass, field


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def can_continue(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {**asdict(self), "can_continue": self.can_continue}


def is_finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_input(request: dict, structure_summary: dict) -> ValidationReport:
    report = ValidationReport()
    for key in ("task_id", "catalyst"):
        if not isinstance(request.get(key), str) or not request[key].strip():
            report.errors.append(f"{key} must be a non-empty string")
    threshold = request.get("threshold_ev")
    if not is_finite_number(threshold) or threshold < 0:
        report.errors.append("threshold_ev must be a finite non-negative value in eV")

    count = structure_summary.get("num_sites")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        report.errors.append("The structure site count must be a positive integer")
    kind = structure_summary.get("structure_type")
    if kind == "periodic_structure":
        volume = structure_summary.get("volume_angstrom3")
        if not is_finite_number(volume) or volume <= 0:
            report.errors.append("A periodic structure must have a finite positive cell volume")
    elif kind != "molecule":
        report.errors.append("Unknown structure type")
    return report


def validate_output(request: dict, output: dict, allow_demo: bool) -> ValidationReport:
    report = ValidationReport()
    if output.get("task_id") != request.get("task_id"):
        report.errors.append("The output task_id does not match the request")
    if output.get("status") != "completed":
        report.errors.append("The task is incomplete and cannot enter barrier screening")
    if not is_finite_number(output.get("energy_barrier_ev")):
        report.errors.append("energy_barrier_ev must be finite and cannot be None, NaN, or infinity")
    source = output.get("source")
    if not isinstance(source, str) or not source.strip():
        report.errors.append("The execution output is missing provenance")
    result_type = output.get("result_type")
    if result_type in ("mock", "synthetic_demo_fixture"):
        if allow_demo:
            report.warnings.append(
                "This is demonstration data; scientific interpretation requires human review"
            )
        else:
            report.errors.append("Demonstration data are not authorized for this task")
    elif result_type in ("real_calculation", "database_fixture"):
        report.warnings.append(
            "A provenance label does not prove reliability; verify settings, barrier definition, and units"
        )
    else:
        report.errors.append("Unknown result type")
    # A high barrier is still valid data; threshold ranking belongs in the Reviewer.
    return report


def main() -> None:
    request = {"task_id": "reaction_001", "catalyst": "Pt", "threshold_ev": 1.0}
    structure = {"structure_type": "molecule", "num_sites": 3}
    output = {
        "task_id": "reaction_001",
        "status": "completed",
        "energy_barrier_ev": 1.18,
        "source": "synthetic_demo_fixture_001",
        "result_type": "synthetic_demo_fixture",
    }
    cases = {
        "valid_input": validate_input(request, structure),
        "high_barrier_demo": validate_output(request, output, allow_demo=True),
        "missing_source": validate_output(request, {**output, "source": ""}, allow_demo=True),
        "demo_not_allowed": validate_output(request, output, allow_demo=False),
        "periodic_structure_without_cell": validate_input(
            request, {"structure_type": "periodic_structure", "num_sites": 3, "volume_angstrom3": 0}
        ),
    }
    for name, report in cases.items():
        print(name)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
