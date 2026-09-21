"""Deterministic task planner and backend router.

Run: python planner_router.py
This module does not call an LLM or simulation package.
"""

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PlanningRequest:
    task_id: str
    catalyst: str
    threshold_ev: float
    fixture_available: bool
    allow_mock: bool


@dataclass(frozen=True)
class Plan:
    task_id: str
    backend: str
    reason: str
    steps: tuple[str, ...]
    parameters: dict


def plan_task(request: PlanningRequest) -> Plan:
    """Select a backend from data availability and explicit permissions."""
    if request.threshold_ev < 0:
        raise ValueError("The barrier screening threshold cannot be negative")
    if not request.task_id or not request.catalyst:
        raise ValueError("task_id and catalyst must be non-empty")

    parameters = {
        "task_id": request.task_id,
        "catalyst": request.catalyst,
        "threshold_ev": request.threshold_ev,
    }
    if request.fixture_available:
        backend = "fixture"
        reason = "A matching local fixture is available and must be reviewed for provenance"
        steps = ("validate_input", "lookup_fixture", "review", "report")
    elif request.allow_mock:
        backend = "mock"
        reason = "No local result is available; use an explicitly labeled mock demonstration"
        steps = ("validate_input", "run_mock", "review", "report")
    else:
        backend = "manual_review"
        reason = "No local result is available and mock execution is not authorized"
        steps = ("validate_input", "request_data")

    return Plan(request.task_id, backend, reason, steps, parameters)


def main() -> None:
    scenarios = (
        PlanningRequest("reaction_pt", "Pt", 1.0, True, False),
        PlanningRequest("reaction_new", "Cu", 1.0, False, True),
        PlanningRequest("reaction_unknown", "Ni", 1.0, False, False),
    )
    for request in scenarios:
        print(json.dumps(asdict(plan_task(request)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
