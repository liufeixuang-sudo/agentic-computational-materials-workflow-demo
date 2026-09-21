"""Minimal abstraction for interchangeable simulation backends.

MockRunner is provided for the reproducible demo. VASP, LAMMPS, or other
backends can later implement the same interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SimulationInput:
    task_id: str
    catalyst: str
    energy_barrier_threshold_ev: float


@dataclass
class SimulationOutput:
    task_id: str
    status: str
    energy_barrier_ev: float | None
    result_type: str
    source: str


@dataclass
class Runtime:
    backend: str
    workdir: str
    timeout_seconds: int = 300


class SimulationAdapter(ABC):
    @abstractmethod
    def prepare(self, task: SimulationInput, runtime: Runtime) -> SimulationInput:
        raise NotImplementedError

    @abstractmethod
    def execute(self, simulation_input: SimulationInput, runtime: Runtime) -> SimulationOutput:
        raise NotImplementedError

    @abstractmethod
    def parse(self, raw_output: object) -> SimulationOutput:
        raise NotImplementedError


class MockRunner(SimulationAdapter):
    def prepare(self, task: SimulationInput, runtime: Runtime) -> SimulationInput:
        print(f"Preparing task {task.task_id} for backend {runtime.backend}")
        return task

    def execute(self, simulation_input: SimulationInput, runtime: Runtime) -> SimulationOutput:
        print("Executing MockRunner with a synthetic local result; no real simulation is run")
        return SimulationOutput(
            task_id=simulation_input.task_id,
            status="completed",
            energy_barrier_ev=0.82,
            result_type="mock",
            source="hardcoded_demo_value",
        )

    def parse(self, raw_output: object) -> SimulationOutput:
        if not isinstance(raw_output, SimulationOutput):
            raise TypeError("MockRunner expects a SimulationOutput instance")
        return raw_output


def main() -> None:
    task = SimulationInput("reaction_001", "Pt", 1.0)
    runtime = Runtime("mock", "outputs/reaction_001")
    runner = MockRunner()
    prepared = runner.prepare(task, runtime)
    output = runner.execute(prepared, runtime)
    parsed = runner.parse(output)
    print("Normalized output:", parsed)


if __name__ == "__main__":
    main()
