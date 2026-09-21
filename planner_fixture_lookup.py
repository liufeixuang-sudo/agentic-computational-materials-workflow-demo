"""Check the local fixture before routing a task through the planner."""

import json
from dataclasses import asdict
from pathlib import Path

from planner_router import PlanningRequest, plan_task


FIXTURE_PATH = Path(__file__).parent / "data" / "fixtures" / "catalysis_results.json"


def has_fixture(task_id: str, catalyst: str, path: Path = FIXTURE_PATH) -> bool:
    """Return True only when both task identifier and catalyst match."""
    with path.open(encoding="utf-8") as file:
        records = json.load(file)
    if not isinstance(records, list):
        raise ValueError("Fixture data must be a JSON array")
    return any(
        record.get("reaction_id") == task_id
        and record.get("catalyst") == catalyst
        for record in records
    )


def build_plan(task_id: str, catalyst: str, threshold_ev: float, allow_mock: bool):
    available = has_fixture(task_id, catalyst)
    request = PlanningRequest(task_id, catalyst, threshold_ev, available, allow_mock)
    return plan_task(request)


def main() -> None:
    scenarios = (
        ("co2_hydrogenation_001", "Ni", 1.0, False),
        ("co2_hydrogenation_001", "Ni", 1.0, True),
        ("unknown_reaction", "Ni", 1.0, False),
    )
    for task_id, catalyst, threshold_ev, allow_mock in scenarios:
        print(json.dumps(asdict(build_plan(task_id, catalyst, threshold_ev, allow_mock)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
