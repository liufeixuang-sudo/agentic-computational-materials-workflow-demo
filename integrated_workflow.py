"""Deterministic Planner + Validator + interchangeable Runner + Reviewer.

Run: python integrated_workflow.py
The standalone examples use synthetic data and do not read credentials or run simulations.
"""

import json
from dataclasses import asdict

from fixture_adapter import FixtureRunnerAdapter
from planner_fixture_lookup import build_plan
from reviewer import review_result
from simulation_adapter import MockRunner, Runtime, SimulationAdapter, SimulationInput
from validator import validate_input, validate_output


def run_workflow(request: dict, structure: dict, *,
                 allow_mock: bool = False, allow_demo: bool = False) -> dict:
    report = {
        "request": request, "trace": [], "plan": None,
        "execution": None, "review": None,
    }
    # Reject invalid input before planning or querying the local database.
    report["trace"].append("input_validation")
    input_check = validate_input(request, structure)
    report["input_validation"] = input_check.to_dict()
    if not input_check.can_continue:
        report["status"] = "blocked_input"
        return report

    report["trace"].append("planner")
    try:
        plan = build_plan(request["task_id"], request["catalyst"],
                          request["threshold_ev"], allow_mock)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report.update(status="planning_failed", error_type=type(exc).__name__)
        return report  # A database error must not silently fall back to MockRunner.
    report["plan"] = asdict(plan)
    if plan.backend == "manual_review":
        report["status"] = "needs_data"
        return report  # Request data without instantiating or executing a Runner.

    # Backend selection is isolated here; downstream code uses only the common interface.
    runner: SimulationAdapter
    if plan.backend == "fixture":
        runner = FixtureRunnerAdapter()
    elif plan.backend == "mock":
        runner = MockRunner()
    else:
        report["status"] = "unsupported_backend"
        return report

    task = SimulationInput(**{
        "task_id": plan.parameters["task_id"],
        "catalyst": plan.parameters["catalyst"],
        "energy_barrier_threshold_ev": plan.parameters["threshold_ev"],
    })
    runtime = Runtime(plan.backend, "outputs/demo")
    try:
        report["trace"].append("runner_prepare")
        prepared = runner.prepare(task, runtime)
        report["trace"].append("runner_execute")
        raw = runner.execute(prepared, runtime)
        report["trace"].append("runner_parse")
        output = asdict(runner.parse(raw))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report.update(status="runner_failed", error_type=type(exc).__name__)
        return report

    report["execution"] = output
    report["trace"].append("output_validation")
    output_check = validate_output(request, output, allow_demo)
    report["output_validation"] = output_check.to_dict()
    if not output_check.can_continue:
        report["status"] = "blocked_output"
        return report

    report["trace"].append("reviewer")
    report["review"] = review_result(request, output, output_check)
    report["status"] = "completed"  # Workflow completion is not scientific approval.
    return report


def main() -> None:
    request = {"task_id": "co2_hydrogenation_001", "catalyst": "Pt", "threshold_ev": 1.0}
    structure = {"structure_type": "molecule", "num_sites": 3}
    cases = (
        ("local_demo_result", request, False, True),
        ("missing_fixture_with_mock", {**request, "task_id": "new_reaction"}, True, True),
        ("missing_fixture_without_mock", {**request, "task_id": "new_reaction"}, False, True),
        ("invalid_input", {**request, "threshold_ev": -1.0}, True, True),
        ("demo_not_authorized", request, False, False),
        ("local_high_barrier", {**request, "task_id": "co2_hydrogenation_002", "catalyst": "Ni"}, False, True),
        ("mock_without_demo_review", {**request, "task_id": "new_reaction"}, True, False),
    )
    for name, task_request, allow_mock, allow_demo in cases:
        print(f"\nCase: {name}")
        report = run_workflow(task_request, structure,
                              allow_mock=allow_mock, allow_demo=allow_demo)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
