# Architecture

## System Overview

```mermaid
flowchart LR
    U[User request] --> A[agent_workflow.py]
    A -->|Constrained function call| LLM[DeepSeek-compatible Responses API]
    LLM -->|task_id, catalyst, threshold_ev| A

    CLI[Offline CLI] --> R[run.py]
    R --> SF[structure_file_workflow.py]
    A --> S{Local structure exists?}
    S -->|Yes| SF
    S -->|No and lookup denied| NS[needs_structure]
    S -->|No and --allow-mp| MPA[materials_project_structure_agent.py]
    MPA -->|formula, symmetry, limit| LLM
    MPA -->|Controlled Python query| MP[Materials Project]
    MP -->|CIF and metadata| MPA
    MPA -->|Human-selected structure| SF

    SF --> SM[structure_molecule_summary.py]
    SF --> W[integrated_workflow.py]
    W --> P[Planner]
    W --> V[Validator]
    W --> X[SimulationAdapter]
    X --> F[FixtureRunnerAdapter]
    X --> M[MockRunner]
    W --> RV[Reviewer]
    SF --> O[report.json and report.md]
    A -->|Tool result for bounded review| LLM
```

The language model never selects its own execution permissions. Local command-line
flags control Mock execution, demonstration-data review, and Materials Project access.
API keys remain inside the Python process.

## Deterministic Workflow

```mermaid
flowchart TD
    I[Request and structure summary] --> VI[validate_input]
    VI -->|Errors| BI[blocked_input]
    VI -->|Valid| P[build_plan]
    P -->|Matching fixture| F[FixtureRunnerAdapter]
    P -->|No fixture and allow_mock| M[MockRunner]
    P -->|No fixture and Mock denied| ND[needs_data]
    F --> C[prepare -> execute -> parse]
    M --> C
    C --> VO[validate_output]
    VO -->|Errors| BO[blocked_output]
    VO -->|Valid| R[review_result]
    R --> D[Decision, provenance, limitations]
    D --> OK[completed]
```

`completed` means that the software reached the Reviewer. It does not mean that a real
simulation succeeded, uncertainty was quantified, or a scientist approved the result.

## Structure Acquisition

```mermaid
flowchart TD
    Q[Natural-language structure request] --> L[LLM parameter extraction]
    L --> V[Local whitelist and range validation]
    V -->|Formula only and no limit| C[Ask candidate-count clarification]
    C --> V
    V --> MP[MPRester summary search]
    MP --> T[Sort and display candidate metadata]
    T --> CIF[Save candidate CIF files]
    CIF --> H{Number of candidates}
    H -->|One| S[Select automatically]
    H -->|Multiple| U[User selects index or MP ID]
    S --> W[Deterministic workflow]
    U --> W
```

Candidate metadata include formula, space group, energy above hull, band gap, and file
name. A downloaded bulk structure is only an initial structural candidate.

## Module Responsibilities

| Module | Responsibility | Primary output |
|---|---|---|
| `run.py` | One-command offline entry | Console status and report directory |
| `agent_workflow.py` | Task function call, optional structure acquisition, bounded model review | Plan, trace, review, token usage |
| `materials_project_structure_agent.py` | Parse, validate, query, save, display, and select MP candidates | CIF files and acquisition metadata |
| `structure_file_workflow.py` | Connect structure parsing, core workflow, and reporting | JSON and Markdown reports |
| `structure_molecule_summary.py` | Read molecular or periodic structures with ASE/pymatgen | Normalized structure summary |
| `integrated_workflow.py` | Enforce gates and early returns | Status, trace, plan, execution, review |
| `planner_fixture_lookup.py` | Check local data availability | Planner input |
| `planner_router.py` | Select fixture, Mock, or manual data request | Deterministic plan |
| `validator.py` | Separate invalid data from scientific ranking | Errors, warnings, `can_continue` |
| `simulation_adapter.py` | Define the interchangeable backend interface | Standard input/output/runtime types |
| `fixture_adapter.py` | Expose synthetic local results through the common interface | Standard execution output |
| `reviewer.py` | Apply threshold screening and preserve scientific limitations | Decision and review metadata |

## Permission Boundaries

| Capability | Default | Explicit control |
|---|---|---|
| Read project-local structure | Allowed | `--structure` |
| Use synthetic fixture in review | Denied | `--allow-demo` |
| Fall back to MockRunner | Denied | `--allow-mock` |
| Query Materials Project | Denied | `--allow-mp` |
| Select among multiple MP structures | Human input | index or `--select-material-id` |
| Execute VASP/LAMMPS | Not implemented | future adapter and runtime policy |

## Extension Interface

A production backend should implement `SimulationAdapter.prepare`, `execute`, and
`parse`. The adapter can translate normalized tasks into VASP, LAMMPS, CP2K, Gaussian,
or post-processing inputs while keeping planning, validation, review, and reporting
independent of backend-specific details.
