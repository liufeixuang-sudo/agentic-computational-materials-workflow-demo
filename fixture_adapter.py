"""Adapter that exposes the local fixture data through SimulationAdapter."""

import json
from pathlib import Path

from simulation_adapter import (
    Runtime,
    SimulationAdapter,
    SimulationInput,
    SimulationOutput,
)


FIXTURE_PATH = Path(__file__).parent / "data" / "fixtures" / "catalysis_results.json"


class FixtureRunnerAdapter(SimulationAdapter):
    def prepare(self, task: SimulationInput, runtime: Runtime) -> SimulationInput:
        print(f"Preparing fixture lookup for task {task.task_id}")
        return task

    def execute(self, simulation_input: SimulationInput, runtime: Runtime) -> SimulationOutput:
        with FIXTURE_PATH.open(encoding="utf-8") as file:
            records = json.load(file)
            # The JSON fixture emulates normalized results from a calculation database.

        matches = [
            record for record in records
            if record["reaction_id"] == simulation_input.task_id
            and record["catalyst"] == simulation_input.catalyst
        ]
        # Match both task and catalyst so unrelated records cannot enter the workflow.
        if not matches:
            return SimulationOutput(
                task_id=simulation_input.task_id,
                status="not_found",
                energy_barrier_ev=None,
                result_type="no_result",
                source=str(FIXTURE_PATH),
            )

        record = matches[0]
        return SimulationOutput(
            task_id=simulation_input.task_id,
            status="completed",
            energy_barrier_ev=record["energy_barrier_ev"],
            result_type=record["result_type"],
            source=record["source"],
        )

    def parse(self, raw_output: object) -> SimulationOutput:
        if not isinstance(raw_output, SimulationOutput):
            raise TypeError("FixtureRunnerAdapter expects a SimulationOutput instance")
        return raw_output


def run_workflow(runner: SimulationAdapter) -> SimulationOutput:
    """Run a task through the common adapter interface."""
    task = SimulationInput("co2_hydrogenation_001", "Pt", 1.0)
    runtime = Runtime("fixture", "outputs/reaction_001")
    prepared = runner.prepare(task, runtime)
    output = runner.execute(prepared, runtime)
    return runner.parse(output)


if __name__ == "__main__":
    print("Unified workflow output:", run_workflow(FixtureRunnerAdapter()))
