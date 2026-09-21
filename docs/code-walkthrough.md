# Code Walkthrough

## Entry Points

### `run.py`

The offline entry supplies `pt.xyz --allow-demo` when no arguments are given and then
calls `structure_file_workflow.main()`. It does not load `.env` or call external APIs.

### `agent_workflow.py`

The online entry performs two bounded model roles:

1. Convert a natural-language screening task into the whitelisted fields
   `task_id`, `catalyst`, and `threshold_ev`.
2. Summarize the deterministic Python result without turning workflow completion into
   a scientific claim.

If a local structure is missing and `--allow-mp` is present, the same client can parse
a separate structure request. Python still validates every field and performs the
Materials Project query.

## Structure Layer

### `structure_molecule_summary.py`

`summarize_structure()` reads a file through ASE. A zero-volume cell is converted to a
pymatgen `Molecule`; a non-zero cell becomes a periodic `Structure`. Periodic summaries
also include lattice parameters, volume, space-group symbol/number, and crystal system.

### `materials_project_structure_agent.py`

The acquisition sequence is:

```text
parse_structure_request
  -> validate_structure_query
  -> fetch_materials_project_candidates
  -> save_candidate_structures
  -> print_candidate_table
  -> select_candidate
```

The query is limited to whitelisted fields and a maximum of ten candidates. The API key
is read by Python only and is excluded from all report metadata.

### `structure_file_workflow.py`

`run_from_structure()` restricts input paths to the project directory, creates a
normalized structure summary, and calls the deterministic workflow. `save_reports()`
writes `report.json` and `report.md` to one unique run directory.

## Planning and Execution

### `planner_fixture_lookup.py`

`has_fixture()` requires both the task identifier and catalyst to match a local record.
A database error is raised explicitly and is not treated as missing data.

### `planner_router.py`

`plan_task()` applies deterministic routing:

- matching local record -> `fixture`;
- no record plus explicit Mock permission -> `mock`;
- no record and no Mock permission -> `manual_review` / `needs_data`.

### `simulation_adapter.py`

The common backend contract defines:

- `prepare`: translate normalized task information into backend input;
- `execute`: run or call the selected backend;
- `parse`: convert backend-specific output into `SimulationOutput`.

`MockRunner` is intentionally synthetic and exists only to demonstrate the contract.

### `fixture_adapter.py`

`FixtureRunnerAdapter` reads a synthetic JSON record and exposes it through the same
`prepare`, `execute`, and `parse` methods. Future simulation backends can be substituted
without changing the upper workflow.

## Validation and Review

### `validator.py`

Input validation rejects missing identifiers, invalid thresholds, unknown structure
types, and invalid periodic-cell volumes. Output validation checks task identity,
completion state, finite barriers, provenance, result type, and demonstration permission.
High barriers remain valid data and are ranked only by the Reviewer.

### `reviewer.py`

The Reviewer compares a validated barrier with the requested threshold. Demonstration
results produce explicitly prefixed decisions. Non-demonstration results require a
defined free-energy barrier, eV units, and positive temperature before preliminary
screening. Every result retains a human-review flag and scientific limitations.

### `integrated_workflow.py`

The orchestrator records a trace and stops immediately at failed gates:

```text
input_validation
  -> planner
  -> runner_prepare
  -> runner_execute
  -> runner_parse
  -> output_validation
  -> reviewer
```

The trace records reached stages; early `return` statements enforce control flow.

## Dependencies

| Dependency | Purpose |
|---|---|
| ASE | Structure-file input |
| pymatgen | Molecular/periodic representations, symmetry, CIF output |
| OpenAI Python SDK | DeepSeek-compatible Responses API calls |
| python-dotenv | Local environment-file loading |
| mp-api | Official Materials Project client |
| pytest | Offline regression tests |

All other named modules in the repository are project code or Python standard-library
modules.
