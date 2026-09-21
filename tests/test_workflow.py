"""Offline tests for workflow gates and deterministic routing."""

from integrated_workflow import run_workflow


STRUCTURE = {"structure_type": "molecule", "num_sites": 3}
REQUEST = {
    "task_id": "co2_hydrogenation_001",
    "catalyst": "Pt",
    "threshold_ev": 1.0,
}


def test_fixture_demo_completes_with_explicit_permission():
    report = run_workflow(REQUEST, STRUCTURE, allow_demo=True)
    assert report["status"] == "completed"
    assert report["execution"]["energy_barrier_ev"] == 0.82
    assert report["review"]["decision"] == "demo_candidate"


def test_missing_fixture_without_mock_requests_data():
    report = run_workflow(
        {**REQUEST, "task_id": "missing_reaction"},
        STRUCTURE,
        allow_mock=False,
        allow_demo=True,
    )
    assert report["status"] == "needs_data"
    assert all(not step.startswith("runner_") for step in report["trace"])


def test_mock_output_is_blocked_when_demo_is_not_authorized():
    report = run_workflow(
        {**REQUEST, "task_id": "missing_reaction"},
        STRUCTURE,
        allow_mock=True,
        allow_demo=False,
    )
    assert report["status"] == "blocked_output"
    assert "reviewer" not in report["trace"]
    assert report["review"] is None


def test_invalid_threshold_stops_before_planning():
    report = run_workflow(
        {**REQUEST, "threshold_ev": -1.0},
        STRUCTURE,
        allow_mock=True,
        allow_demo=True,
    )
    assert report["status"] == "blocked_input"
    assert report["trace"] == ["input_validation"]
